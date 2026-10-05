"""The Postgres unit of work: one transaction with the tenant setting for row-level security,
the repositories on it, the outbox writer as the event sink and ``py_common.audit``'s writer as
the audit sink, so a decision commits or rolls back with its ``applicability.decided`` row, its
review item and its directory entries, and a resolution with its ``audit.event`` row.

``PostgresUnitOfWorkFactory.on_connection(connection)`` makes units inside a transaction someone
else owns, such as the profile.updated consumer's inbox transaction (``py_common.outbox.sync``):
the decisions, their outbox rows and the ``processed_event`` row then commit together.

``business_directory`` is a routing directory (migration 0002): the unit writes its tenant's
entries under the tenant setting, which the write policy checks, and ``PostgresBusinessDirectory``
reads the ids across tenants for a fan-out that then opens one tenant's unit at a time.

``PostgresFanOutUnitOfWorkFactory`` opens units over ``fanout_run`` and ``fanout_hold``
(migration 0003) with no tenant setting: both tables are rule-level, and the audit entries of
their controls are of no tenant, which ``audit.event``'s platform insert admits.
``PostgresFanOutUnitOfWorkFactory.on_connection(connection)`` makes them inside the rule events
consumer's inbox transaction.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC
from typing import Any, Self
from uuid import UUID

from sqlalchemy import (
    Connection,
    Engine,
    and_,
    create_engine,
    delete,
    func,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session, aliased
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import Subquery

from applicability_engine.domain.directory import DirectoryEntry, DirectoryKey
from applicability_engine.domain.fanout import (
    FanOutCounters,
    FanOutHold,
    FanOutRun,
    FanOutRunKey,
    FanOutStatus,
)
from applicability_engine.domain.impact import ImpactEntry
from applicability_engine.domain.model import Decision, DecisionKey, Trigger
from applicability_engine.domain.repository import (
    FanOutUnitOfWork,
    FanOutUnitOfWorkFactory,
    UnitOfWork,
    UnitOfWorkFactory,
)
from applicability_engine.domain.review import (
    Resolution,
    ReviewItem,
    ReviewItemId,
    ReviewItemKey,
    ReviewReason,
    ReviewStatus,
)
from applicability_engine.infrastructure.models import (
    GLOBAL_HOLD,
    TENANT_SETTING,
    BusinessDirectoryRow,
    DecisionRow,
    FanOutHoldRow,
    FanOutRunRow,
    ReviewItemRow,
)
from domain_kernel.confidence import Confidence
from domain_kernel.events import DomainEvent
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, EventId, RuleVersionId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import (
    Applicability,
    Predicate,
    PredicateResult,
    specification_from_mapping,
    specification_to_mapping,
)
from py_common.audit.writer import PostgresAuditSink
from py_common.outbox import OutboxWriter


class SqlAlchemyDecisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, decision: Decision) -> None:
        self._session.add(_to_row(decision))
        self._session.flush()

    def add_if_absent(self, decision: Decision) -> bool:
        statement = (
            insert(DecisionRow)
            .values(_row_values(decision))
            .on_conflict_do_nothing()
            .returning(DecisionRow.id)
        )
        return self._session.execute(statement).first() is not None

    def get(self, decision_id: DecisionId) -> Decision | None:
        row = self._session.get(DecisionRow, decision_id.value)
        return None if row is None else _to_decision(row)

    def get_many(self, decision_ids: Sequence[DecisionId]) -> Sequence[Decision]:
        if not decision_ids:
            return []
        statement = select(DecisionRow).where(
            DecisionRow.id.in_([decision_id.value for decision_id in decision_ids])
        )
        return [_to_decision(row) for row in self._session.scalars(statement).all()]

    def latest(self, business_id: BusinessId, rule_version_id: RuleVersionId) -> Decision | None:
        statement = (
            select(DecisionRow)
            .where(
                DecisionRow.business_id == business_id.value,
                DecisionRow.rule_version_id == rule_version_id.value,
            )
            .order_by(DecisionRow.decided_at.desc(), DecisionRow.id.desc())
            .limit(1)
        )
        row = self._session.scalars(statement).first()
        return None if row is None else _to_decision(row)

    def list_for_business(
        self,
        business_id: BusinessId,
        *,
        rule_version_id: RuleVersionId | None,
        after: DecisionKey | None,
        limit: int,
    ) -> Sequence[Decision]:
        statement = (
            select(DecisionRow)
            .where(DecisionRow.business_id == business_id.value)
            .order_by(DecisionRow.decided_at.desc(), DecisionRow.id.desc())
            .limit(limit)
        )
        if rule_version_id is not None:
            statement = statement.where(DecisionRow.rule_version_id == rule_version_id.value)
        if after is not None:
            statement = statement.where(
                tuple_(DecisionRow.decided_at, DecisionRow.id)
                < tuple_(after.decided_at, after.decision_id.value)
            )
        return [_to_decision(row) for row in self._session.scalars(statement).all()]


class SqlAlchemyDirectoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: DirectoryEntry) -> bool:
        statement = (
            insert(BusinessDirectoryRow)
            .values(
                business_id=entry.business_id.value,
                tenant_id=entry.tenant_id.value,
                level=entry.level.value,
                parent_id=None if entry.parent_id is None else entry.parent_id.value,
                entity_id=entry.entity_id.value,
            )
            .on_conflict_do_nothing(index_elements=["business_id"])
            .returning(BusinessDirectoryRow.business_id)
        )
        return self._session.execute(statement).first() is not None


class SqlAlchemyReviewItemRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, item: ReviewItem) -> bool:
        statement = (
            insert(ReviewItemRow)
            .values(_review_values(item))
            .on_conflict_do_nothing()
            .returning(ReviewItemRow.id)
        )
        return self._session.execute(statement).first() is not None

    def get(self, item_id: ReviewItemId, *, for_update: bool = False) -> ReviewItem | None:
        statement = select(ReviewItemRow).where(ReviewItemRow.id == item_id.value)
        if for_update:
            statement = statement.with_for_update()
        row = self._session.execute(statement.execution_options(populate_existing=True))
        found = row.scalars().first()
        return None if found is None else _to_review_item(found)

    def open_for(
        self, business_id: BusinessId, rule_version_id: RuleVersionId
    ) -> ReviewItem | None:
        statement = (
            select(ReviewItemRow)
            .where(
                ReviewItemRow.business_id == business_id.value,
                ReviewItemRow.rule_version_id == rule_version_id.value,
                ReviewItemRow.status == ReviewStatus.OPEN.value,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        found = self._session.scalars(statement).first()
        return None if found is None else _to_review_item(found)

    def save(self, item: ReviewItem) -> None:
        values = _review_values(item)
        values.pop("id")
        self._session.execute(
            update(ReviewItemRow).where(ReviewItemRow.id == item.item_id.value).values(values)
        )

    def list(
        self, *, status: ReviewStatus | None, after: ReviewItemKey | None, limit: int
    ) -> Sequence[ReviewItem]:
        statement = (
            select(ReviewItemRow)
            .order_by(ReviewItemRow.opened_at, ReviewItemRow.id)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        if status is not None:
            statement = statement.where(ReviewItemRow.status == status.value)
        if after is not None:
            statement = statement.where(
                tuple_(ReviewItemRow.opened_at, ReviewItemRow.id)
                > tuple_(after.opened_at, after.item_id.value)
            )
        return [_to_review_item(row) for row in self._session.scalars(statement).all()]


class SqlAlchemyImpactRepository:
    """The latest decision of a version per business: ``DISTINCT ON (business_id)`` over the
    tenant's decisions of the version, newest first, which a backward scan of
    ``ix_applicability_decision_impact`` serves in order. Row-level security keeps the decisions
    to the unit's tenant; the directory, which every session reads, is joined on the decision's
    tenant too."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def latest_by_entity(
        self,
        rule_version_id: RuleVersionId,
        *,
        result: Applicability | None,
        after: BusinessId | None,
        limit: int,
    ) -> Sequence[ImpactEntry]:
        row = aliased(DecisionRow, _latest_of(rule_version_id))
        entity = func.coalesce(BusinessDirectoryRow.entity_id, row.business_id)
        placed = select(row, entity.label("entity_id"), BusinessDirectoryRow.level).outerjoin(
            BusinessDirectoryRow,
            and_(
                BusinessDirectoryRow.business_id == row.business_id,
                BusinessDirectoryRow.tenant_id == row.tenant_id,
            ),
        )
        if result is not None:
            placed = placed.where(row.result == result.value)
        chosen = placed.subquery("placed")
        entities = select(chosen.c.entity_id).distinct().order_by(chosen.c.entity_id).limit(limit)
        if after is not None:
            entities = entities.where(chosen.c.entity_id > after.value)
        wanted: list[UUID] = list(self._session.scalars(entities).all())
        if not wanted:
            return []
        statement = placed.where(entity.in_(wanted)).order_by(entity, row.business_id)
        return [
            ImpactEntry(
                entity_id=BusinessId(entity_id),
                level=None if level is None else AttributeLevel(level),
                decision=_to_decision(found),
            )
            for found, entity_id, level in self._session.execute(statement).all()
        ]

    def result_counts(self, rule_version_id: RuleVersionId) -> Mapping[Applicability, int]:
        latest = _latest_of(rule_version_id)
        statement = select(latest.c.result, func.count()).group_by(latest.c.result)
        return {
            Applicability(found): int(count)
            for found, count in self._session.execute(statement).all()
        }


def _latest_of(rule_version_id: RuleVersionId) -> Subquery:
    """The newest decision of the version per business (decided_at, then id), all columns
    descending so a backward scan of ``ix_applicability_decision_impact`` gives them in order."""
    return (
        select(DecisionRow)
        .where(DecisionRow.rule_version_id == rule_version_id.value)
        .ext(distinct_on(DecisionRow.business_id))
        .order_by(
            DecisionRow.business_id.desc(), DecisionRow.decided_at.desc(), DecisionRow.id.desc()
        )
        .subquery("latest")
    )


class OutboxSink:
    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def publish(self, event: DomainEvent) -> None:
        self._writer.write(self._connection, event)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session, tenant_id: TenantId, writer: OutboxWriter) -> None:
        connection = session.connection()
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
        self.decisions = SqlAlchemyDecisionRepository(session)
        self.directory = SqlAlchemyDirectoryRepository(session)
        self.reviews = SqlAlchemyReviewItemRepository(session)
        self.impact = SqlAlchemyImpactRepository(session)
        self.events = OutboxSink(connection, writer)
        self.audit = PostgresAuditSink(connection)


class ConnectionUnitOfWorkFactory:
    """Units of work inside the transaction of ``connection``, which the owner of the connection
    commits or rolls back; a unit never does. A connection with no transaction yet (a consumer
    unit that begins on write) gets one begun on it, still the owner's to end. The tenant setting
    holds until that transaction ends, so every unit on one connection should be of one
    tenant."""

    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        if not self._connection.in_transaction():
            # A session given a connection without a transaction would begin one of its own and
            # roll it back when it closes; begun here, the session joins it instead.
            self._connection.begin()
        with Session(bind=self._connection, expire_on_commit=False) as session:
            yield SqlAlchemyUnitOfWork(session, tenant_id, self._writer)
            session.flush()


class PostgresUnitOfWorkFactory:
    """``factory(tenant_id)`` opens a transaction with ``app.tenant_id`` set for its duration;
    ``PostgresUnitOfWorkFactory.on_connection(connection)`` makes units inside a transaction
    the caller owns."""

    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    @property
    def engine(self) -> Engine:
        """The engine the units of work run on; the idempotency store shares it."""
        return self._engine

    @staticmethod
    def on_connection(
        connection: Connection, *, writer: OutboxWriter | None = None
    ) -> UnitOfWorkFactory:
        return ConnectionUnitOfWorkFactory(connection, writer or OutboxWriter())

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyUnitOfWork(session, tenant_id, self._writer)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


class PostgresBusinessDirectory:
    """The ``business_directory`` entries across tenants, read without a tenant setting: the
    table's read policy admits every row, and it holds nothing but ids and levels. Each read is
    a session of its own that ends before the call returns, so no transaction stays open while
    a fan-out reads profiles over HTTP."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def entries(
        self,
        *,
        level: AttributeLevel | None = None,
        after: DirectoryKey | None = None,
        limit: int = 1_000,
        tenant_id: TenantId | None = None,
    ) -> Sequence[DirectoryEntry]:
        """Entries by tenant then node, of one level or all, of one tenant or all, after
        ``after``, at most ``limit``."""
        statement = (
            select(BusinessDirectoryRow)
            .order_by(BusinessDirectoryRow.tenant_id, BusinessDirectoryRow.business_id)
            .limit(limit)
        )
        if level is not None:
            statement = statement.where(BusinessDirectoryRow.level == level.value)
        if tenant_id is not None:
            statement = statement.where(BusinessDirectoryRow.tenant_id == tenant_id.value)
        if after is not None:
            statement = statement.where(
                tuple_(BusinessDirectoryRow.tenant_id, BusinessDirectoryRow.business_id)
                > tuple_(after.tenant_id.value, after.business_id.value)
            )
        with Session(self._engine) as session:
            return [_to_entry(row) for row in session.scalars(statement).all()]

    def count(self, *, level: AttributeLevel, tenant_id: TenantId | None = None) -> int:
        statement = select(func.count()).where(BusinessDirectoryRow.level == level.value)
        if tenant_id is not None:
            statement = statement.where(BusinessDirectoryRow.tenant_id == tenant_id.value)
        with Session(self._engine) as session:
            return int(session.execute(statement).scalar_one())


class SqlAlchemyFanOutRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_if_absent(self, run: FanOutRun) -> bool:
        statement = (
            insert(FanOutRunRow)
            .values(_run_values(run))
            .on_conflict_do_nothing(index_elements=["rule_version_id"])
            .returning(FanOutRunRow.rule_version_id)
        )
        return self._session.execute(statement).first() is not None

    def get(self, rule_version_id: RuleVersionId, *, for_update: bool = False) -> FanOutRun | None:
        statement = select(FanOutRunRow).where(
            FanOutRunRow.rule_version_id == rule_version_id.value
        )
        if for_update:
            statement = statement.with_for_update()
        found = self._session.scalars(statement.execution_options(populate_existing=True)).first()
        return None if found is None else _to_run(found)

    def save(self, run: FanOutRun) -> None:
        values = _run_values(run)
        values.pop("rule_version_id")
        self._session.execute(
            update(FanOutRunRow)
            .where(FanOutRunRow.rule_version_id == run.rule_version_id.value)
            .values(values)
        )

    def list(self, *, after: FanOutRunKey | None, limit: int) -> Sequence[FanOutRun]:
        statement = (
            select(FanOutRunRow)
            .order_by(FanOutRunRow.started_at.desc(), FanOutRunRow.rule_version_id.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        if after is not None:
            statement = statement.where(
                tuple_(FanOutRunRow.started_at, FanOutRunRow.rule_version_id)
                < tuple_(after.started_at, after.rule_version_id.value)
            )
        return [_to_run(row) for row in self._session.scalars(statement).all()]

    def with_status(self, status: FanOutStatus) -> Sequence[FanOutRun]:
        statement = (
            select(FanOutRunRow)
            .where(FanOutRunRow.status == status.value)
            .order_by(FanOutRunRow.started_at, FanOutRunRow.rule_version_id)
            .execution_options(populate_existing=True)
        )
        return [_to_run(row) for row in self._session.scalars(statement).all()]


class SqlAlchemyFanOutHoldRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, *, for_update: bool = False) -> FanOutHold | None:
        statement = select(FanOutHoldRow).where(FanOutHoldRow.id == GLOBAL_HOLD)
        if for_update:
            statement = statement.with_for_update()
        found = self._session.scalars(statement.execution_options(populate_existing=True)).first()
        if found is None:
            return None
        return FanOutHold(
            reason=found.reason, set_by=found.set_by, set_at=found.set_at.astimezone(UTC)
        )

    def put(self, hold: FanOutHold) -> None:
        values = {"reason": hold.reason, "set_by": hold.set_by, "set_at": hold.set_at}
        statement = (
            insert(FanOutHoldRow)
            .values(id=GLOBAL_HOLD, **values)
            .on_conflict_do_update(index_elements=["id"], set_=values)
        )
        self._session.execute(statement)

    def clear(self) -> bool:
        statement = (
            delete(FanOutHoldRow).where(FanOutHoldRow.id == GLOBAL_HOLD).returning(FanOutHoldRow.id)
        )
        return self._session.execute(statement).first() is not None


class SqlAlchemyFanOutUnitOfWork:
    """The fan-out tables and the audit sink on one transaction, with no tenant setting."""

    def __init__(self, session: Session) -> None:
        self.runs = SqlAlchemyFanOutRunRepository(session)
        self.hold = SqlAlchemyFanOutHoldRepository(session)
        self.audit = PostgresAuditSink(session.connection())


class ConnectionFanOutUnitOfWorkFactory:
    """Fan-out units inside the transaction of ``connection``, which its owner commits or rolls
    back, as ``ConnectionUnitOfWorkFactory`` does for tenant units."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def __call__(self) -> AbstractContextManager[FanOutUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[FanOutUnitOfWork]:
        if not self._connection.in_transaction():
            self._connection.begin()
        with Session(bind=self._connection, expire_on_commit=False) as session:
            yield SqlAlchemyFanOutUnitOfWork(session)
            session.flush()


class PostgresFanOutUnitOfWorkFactory:
    """``factory()`` opens a transaction over the fan-out tables and the audit log;
    ``PostgresFanOutUnitOfWorkFactory.on_connection(connection)`` makes units inside a
    transaction the caller owns."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def on_connection(connection: Connection) -> FanOutUnitOfWorkFactory:
        return ConnectionFanOutUnitOfWorkFactory(connection)

    def __call__(self) -> AbstractContextManager[FanOutUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[FanOutUnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyFanOutUnitOfWork(session)


def evaluated_to_json(evaluated: Sequence[PredicateResult]) -> list[dict[str, Any]]:
    """The predicate results as the ``evaluated`` column stores them: each predicate in the
    kernel's specification mapping, with its outcome, confidence and reason."""
    return [
        {
            "predicate": specification_to_mapping(item.predicate),
            "outcome": item.outcome.value,
            "confidence": item.confidence.value,
            "reason": item.reason,
        }
        for item in evaluated
    ]


def evaluated_from_json(items: Sequence[Mapping[str, Any]]) -> tuple[PredicateResult, ...]:
    results: list[PredicateResult] = []
    for item in items:
        predicate = specification_from_mapping(item["predicate"])
        if not isinstance(predicate, Predicate):
            raise ValueError(f"an evaluated entry holds a {type(predicate).__name__}")
        results.append(
            PredicateResult(
                predicate,
                Applicability(item["outcome"]),
                Confidence(float(item["confidence"])),
                str(item["reason"]),
            )
        )
    return tuple(results)


def _row_values(decision: Decision) -> dict[str, Any]:
    return {
        "id": decision.decision_id.value,
        "tenant_id": decision.tenant_id.value,
        "business_id": decision.business_id.value,
        "rule_version_id": decision.rule_version_id.value,
        "result": decision.result.value,
        "confidence": decision.confidence.value,
        "profile_version": decision.profile_version,
        "as_of_fy": None if decision.as_of_fy is None else decision.as_of_fy.label,
        "trigger": decision.trigger.value,
        "trigger_ref": decision.trigger_ref,
        "evaluated": evaluated_to_json(decision.evaluated),
        "decided_at": decision.decided_at,
    }


def _to_row(decision: Decision) -> DecisionRow:
    return DecisionRow(**_row_values(decision))


def _to_decision(row: DecisionRow) -> Decision:
    return Decision(
        decision_id=DecisionId(row.id),
        tenant_id=TenantId(row.tenant_id),
        business_id=BusinessId(row.business_id),
        rule_version_id=RuleVersionId(row.rule_version_id),
        result=Applicability(row.result),
        confidence=Confidence(row.confidence),
        evaluated=evaluated_from_json(row.evaluated),
        profile_version=row.profile_version,
        decided_at=row.decided_at.astimezone(UTC),
        trigger=Trigger(row.trigger),
        as_of_fy=None if row.as_of_fy is None else FinancialYear.parse(row.as_of_fy),
        trigger_ref=row.trigger_ref,
    )


def _review_values(item: ReviewItem) -> dict[str, Any]:
    return {
        "id": item.item_id.value,
        "tenant_id": item.tenant_id.value,
        "business_id": item.business_id.value,
        "rule_version_id": item.rule_version_id.value,
        "decision_id": item.decision_id.value,
        "reason": item.reason.value,
        "status": item.status.value,
        "opened_at": item.opened_at,
        "resolution": None if item.resolution is None else item.resolution.value,
        "resolved_by": None if item.resolved_by is None else item.resolved_by.value,
        "resolved_at": item.resolved_at,
        "note": item.note,
        "resolution_decision_id": None
        if item.resolution_decision_id is None
        else item.resolution_decision_id.value,
    }


def _to_review_item(row: ReviewItemRow) -> ReviewItem:
    return ReviewItem(
        item_id=ReviewItemId(row.id),
        tenant_id=TenantId(row.tenant_id),
        business_id=BusinessId(row.business_id),
        rule_version_id=RuleVersionId(row.rule_version_id),
        decision_id=DecisionId(row.decision_id),
        reason=ReviewReason(row.reason),
        opened_at=row.opened_at.astimezone(UTC),
        status=ReviewStatus(row.status),
        resolution=None if row.resolution is None else Resolution(row.resolution),
        resolved_by=None if row.resolved_by is None else UserId(row.resolved_by),
        resolved_at=None if row.resolved_at is None else row.resolved_at.astimezone(UTC),
        note=row.note,
        resolution_decision_id=None
        if row.resolution_decision_id is None
        else DecisionId(row.resolution_decision_id),
    )


def _to_entry(row: BusinessDirectoryRow) -> DirectoryEntry:
    return DirectoryEntry(
        tenant_id=TenantId(row.tenant_id),
        business_id=BusinessId(row.business_id),
        level=AttributeLevel(row.level),
        parent_id=None if row.parent_id is None else BusinessId(row.parent_id),
        entity_id=BusinessId(row.entity_id),
    )


def _run_values(run: FanOutRun) -> dict[str, Any]:
    counters = run.counters
    return {
        "rule_version_id": run.rule_version_id.value,
        "rule_key": run.rule_key,
        "level": run.level.value,
        "status": run.status.value,
        "trigger_event_id": run.trigger_event_id.value,
        "supersedes": [str(superseded) for superseded in run.supersedes],
        "businesses_total": counters.businesses_total,
        "evaluated": counters.evaluated,
        "applies": counters.applies,
        "flips_compared": counters.flips_compared,
        "flips": counters.flips,
        "started_at": run.started_at,
        "updated_at": run.updated_at,
        "finished_at": run.finished_at,
        "status_reason": run.status_reason,
        "status_by": run.status_by,
        "last_error": run.last_error,
    }


def _to_run(row: FanOutRunRow) -> FanOutRun:
    return FanOutRun(
        rule_version_id=RuleVersionId(row.rule_version_id),
        rule_key=row.rule_key,
        level=AttributeLevel(row.level),
        status=FanOutStatus(row.status),
        trigger_event_id=EventId(row.trigger_event_id),
        started_at=row.started_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
        supersedes=tuple(RuleVersionId(UUID(str(item))) for item in row.supersedes),
        counters=FanOutCounters(
            businesses_total=row.businesses_total,
            evaluated=row.evaluated,
            applies=row.applies,
            flips_compared=row.flips_compared,
            flips=row.flips,
        ),
        finished_at=None if row.finished_at is None else row.finished_at.astimezone(UTC),
        status_reason=row.status_reason,
        status_by=row.status_by,
        last_error=row.last_error,
    )
