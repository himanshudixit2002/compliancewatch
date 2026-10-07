"""The Postgres unit of work: one transaction with the tenant setting for row-level security,
the profile repository on it, the outbox writer as the event sink, the audit writer
(``audit.event``) on the same connection, and an optional JSON-lines recorder for eval cases."""

import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date
from decimal import Decimal
from pathlib import Path
from typing import Self

from sqlalchemy import Connection, Engine, create_engine, exists, or_, select, text, tuple_
from sqlalchemy.orm import Session, aliased
from sqlalchemy.pool import NullPool

from domain_kernel.events import DomainEvent
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel, AttributeSource
from profile_service.domain.errors import ProfileNodeNotFoundError
from profile_service.domain.model import (
    AttributeKey,
    AttributeRecord,
    ProfileNode,
    ReviewReason,
    ReviewTask,
    ValueState,
)
from profile_service.domain.repository import EvalCaseRecorder, UnitOfWork
from profile_service.infrastructure.models import (
    TENANT_SETTING,
    ProfileAttributeRow,
    ProfileNodeRow,
    ProfileVersionRow,
    ReviewTaskRow,
)
from py_common.audit.writer import PostgresAuditSink
from py_common.outbox import OutboxWriter


class SqlAlchemyProfileRepository:
    def __init__(self, session: Session, tenant_id: TenantId) -> None:
        self._session = session
        self._tenant = tenant_id

    def get(self, node_id: BusinessId) -> ProfileNode | None:
        row = self._session.get(ProfileNodeRow, node_id.value)
        return None if row is None else self._to_nodes([row])[0]

    def find_by_key(self, level: AttributeLevel, key: str) -> ProfileNode | None:
        row = self._session.scalars(
            select(ProfileNodeRow).where(
                ProfileNodeRow.level == level.value, ProfileNodeRow.key == key
            )
        ).first()
        return None if row is None else self._to_nodes([row])[0]

    def lineage(self, node: ProfileNode) -> Sequence[ProfileNode]:
        chain: list[ProfileNode] = []
        parent_id = node.parent_id
        while parent_id is not None:
            parent = self.get(parent_id)
            if parent is None:
                break
            chain.insert(0, parent)
            parent_id = parent.parent_id
        return chain

    def children(self, node_id: BusinessId) -> Sequence[ProfileNode]:
        rows = self._session.scalars(
            select(ProfileNodeRow)
            .where(ProfileNodeRow.parent_id == node_id.value)
            .order_by(ProfileNodeRow.created_at, ProfileNodeRow.id)
        ).all()
        return self._to_nodes(rows)

    def entities(self) -> Sequence[ProfileNode]:
        rows = self._session.scalars(
            select(ProfileNodeRow)
            .where(ProfileNodeRow.level == AttributeLevel.ENTITY.value)
            .order_by(ProfileNodeRow.created_at, ProfileNodeRow.id)
        ).all()
        return self._to_nodes(rows)

    def page_entities(
        self, after: BusinessId | None, limit: int, query: str = ""
    ) -> Sequence[ProfileNode]:
        """Keyset paging on ix_profile_node_tenant_level_name (tenant_id, level, name, id)."""
        node = ProfileNodeRow
        statement = select(node).where(node.level == AttributeLevel.ENTITY.value)
        if after is not None:
            start = self._session.execute(
                select(node.name, node.id).where(
                    node.id == after.value, node.level == AttributeLevel.ENTITY.value
                )
            ).first()
            if start is None:
                raise ProfileNodeNotFoundError(str(after))
            statement = statement.where(tuple_(node.name, node.id) > tuple_(start.name, start.id))
        if query:
            pattern = f"%{_escape_like(query)}%"
            registration = aliased(ProfileNodeRow)
            statement = statement.where(
                or_(
                    node.name.ilike(pattern, escape=LIKE_ESCAPE),
                    node.key.ilike(pattern, escape=LIKE_ESCAPE),
                    exists().where(
                        registration.parent_id == node.id,
                        registration.level == AttributeLevel.REGISTRATION.value,
                        registration.key.ilike(pattern, escape=LIKE_ESCAPE),
                    ),
                )
            )
        rows = self._session.scalars(statement.order_by(node.name, node.id).limit(limit)).all()
        return self._to_nodes(rows)

    def registrations_of(
        self, entity_ids: Sequence[BusinessId]
    ) -> Mapping[BusinessId, Sequence[ProfileNode]]:
        found: dict[BusinessId, list[ProfileNode]] = {entity_id: [] for entity_id in entity_ids}
        if not found:
            return found
        rows = self._session.scalars(
            select(ProfileNodeRow)
            .where(
                ProfileNodeRow.parent_id.in_([entity_id.value for entity_id in entity_ids]),
                ProfileNodeRow.level == AttributeLevel.REGISTRATION.value,
            )
            .order_by(ProfileNodeRow.created_at, ProfileNodeRow.id)
        ).all()
        for registration in self._to_nodes(rows):
            if registration.parent_id is not None:
                found[registration.parent_id].append(registration)
        return found

    def add(self, node: ProfileNode) -> None:
        self._session.add(_node_row(node))
        self._session.flush()

    def save(self, node: ProfileNode) -> None:
        self._session.merge(_node_row(node))
        for record in node.attributes.values():
            self._session.merge(_attribute_row(node, record))
        self._session.add(
            ProfileVersionRow(
                node_id=node.id.value,
                tenant_id=node.tenant_id.value,
                version=node.version,
                changed_attributes=[],
                attributes={
                    f"{key}@{fy or ''}": _json(record.value)
                    for (key, fy), record in node.attributes.items()
                    if record.state is ValueState.KNOWN
                },
                source="user_input",
                changed_by=None,
                at=node.updated_at,
            )
        )
        self._session.flush()

    def add_review_task(self, task: ReviewTask) -> None:
        self._session.add(
            ReviewTaskRow(
                id=task.id.value,
                tenant_id=task.tenant_id.value,
                node_id=task.node_id.value,
                attribute_key=task.attribute_key,
                reason=task.reason.value,
                fy_label="" if task.as_of_fy is None else task.as_of_fy.label,
                open=task.open,
                created_at=task.created_at,
            )
        )
        self._session.flush()

    def open_review_tasks(self, node_id: BusinessId | None = None) -> Sequence[ReviewTask]:
        statement = select(ReviewTaskRow).where(ReviewTaskRow.open.is_(True))
        if node_id is not None:
            statement = statement.where(ReviewTaskRow.node_id == node_id.value)
        rows = self._session.scalars(statement.order_by(ReviewTaskRow.created_at)).all()
        return [
            ReviewTask(
                id=BusinessId(row.id),
                tenant_id=TenantId(row.tenant_id),
                node_id=BusinessId(row.node_id),
                attribute_key=row.attribute_key,
                reason=ReviewReason(row.reason),
                as_of_fy=None if row.fy_label == "" else FinancialYear.parse(row.fy_label),
                open=row.open,
                created_at=row.created_at.astimezone(UTC),
            )
            for row in rows
        ]

    def _to_nodes(self, rows: Sequence[ProfileNodeRow]) -> list[ProfileNode]:
        """The nodes of ``rows`` with their attribute values, read in one query."""
        if not rows:
            return []
        attribute_rows = self._session.scalars(
            select(ProfileAttributeRow).where(
                ProfileAttributeRow.node_id.in_([row.id for row in rows])
            )
        ).all()
        records: dict[uuid.UUID, dict[AttributeKey, AttributeRecord]] = {row.id: {} for row in rows}
        for item in attribute_rows:
            record = AttributeRecord(
                key=item.key,
                state=ValueState(item.state),
                value=None if item.value is None else _from_json(item.value),
                as_of_fy=None if item.fy_label == "" else FinancialYear.parse(item.fy_label),
                source=AttributeSource(item.source),
                updated_at=item.updated_at.astimezone(UTC),
            )
            records[item.node_id][record.storage_key] = record
        return [
            ProfileNode(
                id=BusinessId(row.id),
                tenant_id=TenantId(row.tenant_id),
                level=AttributeLevel(row.level),
                key=row.key,
                name=row.name,
                parent_id=None if row.parent_id is None else BusinessId(row.parent_id),
                version=row.version,
                created_at=row.created_at.astimezone(UTC),
                updated_at=row.updated_at.astimezone(UTC),
                attributes=records[row.id],
            )
            for row in rows
        ]


LIKE_ESCAPE = "\\"


def _escape_like(text: str) -> str:
    """``text`` matched literally inside a LIKE pattern: its wildcards and the escape escaped."""
    return (
        text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2)
        .replace("%", LIKE_ESCAPE + "%")
        .replace("_", LIKE_ESCAPE + "_")
    )


def _node_row(node: ProfileNode) -> ProfileNodeRow:
    return ProfileNodeRow(
        id=node.id.value,
        tenant_id=node.tenant_id.value,
        level=node.level.value,
        key=node.key,
        name=node.name,
        parent_id=None if node.parent_id is None else node.parent_id.value,
        version=node.version,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def _attribute_row(node: ProfileNode, record: AttributeRecord) -> ProfileAttributeRow:
    return ProfileAttributeRow(
        node_id=node.id.value,
        tenant_id=node.tenant_id.value,
        key=record.key,
        fy_label="" if record.as_of_fy is None else record.as_of_fy.label,
        state=record.state.value,
        value=None if record.value is None else {"v": _json(record.value)},
        source=record.source.value,
        updated_at=record.updated_at or node.updated_at,
    )


def _json(value: object) -> object:
    """Canonical ontology values as JSON: sets become sorted lists, dates and decimals text."""
    if isinstance(value, frozenset | set):
        return sorted(str(item) for item in value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _from_json(stored: Mapping[str, object]) -> object:
    """The ontology re-coerces text on evaluation; lists become frozensets again."""
    value = stored.get("v")
    if isinstance(value, list):
        return frozenset(str(item) for item in value)
    return value


class OutboxSink:
    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def publish(self, event: DomainEvent) -> None:
        self._writer.write(self._connection, event)


class NoEvalRecorder:
    def record(self, case: Mapping[str, object]) -> None:
        return None


class JsonLinesEvalRecorder:
    """Appends one JSON object per line; the file is a golden-set seed an analyst labels."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def record(self, case: Mapping[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(dict(case), sort_keys=True, ensure_ascii=False, default=_json) + "\n"
            )


class SqlAlchemyUnitOfWork:
    def __init__(
        self,
        session: Session,
        tenant_id: TenantId,
        writer: OutboxWriter,
        eval_cases: EvalCaseRecorder,
    ) -> None:
        connection = session.connection()
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
        self.profiles = SqlAlchemyProfileRepository(session, tenant_id)
        self.events = OutboxSink(connection, writer)
        self.eval_cases = eval_cases
        self.audit = PostgresAuditSink(connection)


class PostgresUnitOfWorkFactory:
    def __init__(
        self,
        engine: Engine,
        *,
        writer: OutboxWriter | None = None,
        eval_cases: EvalCaseRecorder | None = None,
    ) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()
        self._eval_cases = eval_cases or NoEvalRecorder()

    @classmethod
    def from_url(cls, database_url: str, *, eval_cases: EvalCaseRecorder | None = None) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool), eval_cases=eval_cases)

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyUnitOfWork(session, tenant_id, self._writer, self._eval_cases)

    @property
    def engine(self) -> Engine:
        """The engine the units of work run on; the idempotency store shares it."""
        return self._engine

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
