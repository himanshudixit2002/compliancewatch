"""The Postgres unit of work: one transaction with the tenant setting for row-level security,
the obligation repository on it, the outbox writer as the event sink, and the change log on the
same session, so a change row commits or rolls back with its outbox row."""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Self

from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.events import DomainEvent
from domain_kernel.ids import (
    BusinessId,
    CorrelationId,
    DecisionId,
    EventId,
    ObligationId,
    RuleVersionId,
    TenantId,
    UserId,
)
from domain_kernel.recurrence import Period
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.domain.history import ChangeKind, ObligationChange
from obligation.domain.model import Obligation
from obligation.domain.repository import UnitOfWork
from obligation.infrastructure.models import TENANT_SETTING, ObligationChangeRow, ObligationRow
from py_common.outbox import OutboxWriter


class SqlAlchemyObligationRepository:
    def __init__(self, session: Session, tenant_id: TenantId) -> None:
        self._session = session
        self._tenant_id = tenant_id

    def get(self, obligation_id: ObligationId) -> Obligation | None:
        row = self._session.get(ObligationRow, obligation_id.value)
        return None if row is None else _to_obligation(row)

    def find(
        self, business_id: BusinessId, rule_version_id: RuleVersionId, period_label: str | None
    ) -> Obligation | None:
        statement = select(ObligationRow).where(
            ObligationRow.business_id == business_id.value,
            ObligationRow.rule_version_id == rule_version_id.value,
            ObligationRow.period_label.is_(None)
            if period_label is None
            else ObligationRow.period_label == period_label,
        )
        row = self._session.scalars(statement).first()
        return None if row is None else _to_obligation(row)

    def open_for_rule_version(
        self, rule_version_id: RuleVersionId, period_label: str | None = None
    ) -> Sequence[Obligation]:
        statement = (
            select(ObligationRow)
            .where(
                ObligationRow.rule_version_id == rule_version_id.value,
                ObligationRow.status.in_(("open", "in_progress")),
            )
            .order_by(
                ObligationRow.period_start.nulls_first(), ObligationRow.created_at, ObligationRow.id
            )
        )
        if period_label is not None:
            statement = statement.where(ObligationRow.period_label == period_label)
        return [_to_obligation(row) for row in self._session.scalars(statement).all()]

    def list_for_business(
        self,
        business_id: BusinessId,
        *,
        due_after: datetime | None,
        due_before: datetime | None,
        rule_version_id: RuleVersionId | None,
        limit: int,
    ) -> Sequence[Obligation]:
        statement = (
            select(ObligationRow)
            .where(ObligationRow.business_id == business_id.value)
            .order_by(
                ObligationRow.due_at.asc().nulls_last(),
                ObligationRow.period_start.asc().nulls_last(),
                ObligationRow.created_at,
                ObligationRow.id,
            )
            .limit(limit)
        )
        if due_after is not None:
            statement = statement.where(ObligationRow.due_at >= due_after)
        if due_before is not None:
            statement = statement.where(ObligationRow.due_at < due_before)
        if rule_version_id is not None:
            statement = statement.where(ObligationRow.rule_version_id == rule_version_id.value)
        return [_to_obligation(row) for row in self._session.scalars(statement).all()]

    def add(self, obligation: Obligation) -> None:
        self._session.add(_to_row(obligation))
        self._session.flush()

    def save(self, obligation: Obligation) -> None:
        self._session.merge(_to_row(obligation))
        self._session.flush()


class OutboxSink:
    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def publish(self, event: DomainEvent) -> None:
        self._writer.write(self._connection, event)


class SqlAlchemyUnitOfWork:
    def __init__(self, session: Session, tenant_id: TenantId, writer: OutboxWriter) -> None:
        self._session = session
        connection = session.connection()
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
        self.obligations = SqlAlchemyObligationRepository(session, tenant_id)
        self.events = OutboxSink(connection, writer)
        self.history = SqlAlchemyChangeLog(session)


class PostgresUnitOfWorkFactory:
    """``factory(tenant_id)`` opens a transaction with ``app.tenant_id`` set for its duration."""

    def __init__(self, engine: Engine, *, writer: OutboxWriter | None = None) -> None:
        self._engine = engine
        self._writer = writer or OutboxWriter()

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    @property
    def engine(self) -> Engine:
        return self._engine

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


def _to_row(obligation: Obligation) -> ObligationRow:
    period = obligation.period
    return ObligationRow(
        id=obligation.id.value,
        tenant_id=obligation.tenant_id.value,
        business_id=obligation.business_id.value,
        rule_version_id=obligation.rule_version_id.value,
        decision_id=obligation.decision_id.value,
        title=obligation.title,
        steps=list(obligation.steps),
        evidence_type=obligation.evidence_type,
        period_label=None if period is None else period.label,
        period_start=None if period is None else period.start,
        period_end=None if period is None else period.end,
        due_at=obligation.due_at,
        status=obligation.status.value,
        created_at=obligation.created_at,
        updated_at=obligation.updated_at,
        closed_at=obligation.closed_at,
        closed_reason=None if obligation.closed_reason is None else obligation.closed_reason.value,
        closed_by=None if obligation.closed_by is None else obligation.closed_by.value,
    )


def _to_obligation(row: ObligationRow) -> Obligation:
    period = (
        None
        if row.period_label is None or row.period_start is None or row.period_end is None
        else Period(row.period_start, row.period_end, row.period_label)
    )
    return Obligation(
        id=ObligationId(row.id),
        tenant_id=TenantId(row.tenant_id),
        business_id=BusinessId(row.business_id),
        rule_version_id=RuleVersionId(row.rule_version_id),
        decision_id=DecisionId(row.decision_id),
        title=row.title,
        steps=tuple(row.steps),
        evidence_type=row.evidence_type,
        period=period,
        due_at=None if row.due_at is None else row.due_at.astimezone(UTC),
        status=ObligationStatus(row.status),
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
        closed_at=None if row.closed_at is None else row.closed_at.astimezone(UTC),
        closed_reason=None if row.closed_reason is None else ClosureReason(row.closed_reason),
        closed_by=None if row.closed_by is None else UserId(row.closed_by),
    )


class SqlAlchemyChangeLog:
    """The change log on the unit of work's session; row-level security scopes it to the
    tenant, and the table's trigger refuses UPDATE and DELETE."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, change: ObligationChange) -> None:
        self._session.add(_to_change_row(change))
        self._session.flush()

    def for_obligation(self, obligation_id: ObligationId) -> Sequence[ObligationChange]:
        statement = (
            select(ObligationChangeRow)
            .where(ObligationChangeRow.obligation_id == obligation_id.value)
            .order_by(
                ObligationChangeRow.occurred_at,
                ObligationChangeRow.created_at,
                ObligationChangeRow.id,
            )
        )
        return [_to_change(row) for row in self._session.scalars(statement).all()]


def _to_change_row(change: ObligationChange) -> ObligationChangeRow:
    return ObligationChangeRow(
        id=change.id.value,
        tenant_id=change.tenant_id.value,
        obligation_id=change.obligation_id.value,
        business_id=change.business_id.value,
        rule_version_id=change.rule_version_id.value,
        kind=change.kind.value,
        occurred_at=change.occurred_at,
        previous_due_at=change.previous_due_at,
        new_due_at=change.new_due_at,
        status_after=change.status_after.value,
        reason=change.reason,
        caused_by_rule_version_id=None
        if change.caused_by_rule_version_id is None
        else change.caused_by_rule_version_id.value,
        actor=None if change.actor is None else change.actor.value,
        correlation_id=change.correlation_id.value,
    )


def _to_change(row: ObligationChangeRow) -> ObligationChange:
    return ObligationChange(
        id=EventId(row.id),
        tenant_id=TenantId(row.tenant_id),
        obligation_id=ObligationId(row.obligation_id),
        business_id=BusinessId(row.business_id),
        rule_version_id=RuleVersionId(row.rule_version_id),
        kind=ChangeKind(row.kind),
        occurred_at=row.occurred_at.astimezone(UTC),
        previous_due_at=None
        if row.previous_due_at is None
        else row.previous_due_at.astimezone(UTC),
        new_due_at=None if row.new_due_at is None else row.new_due_at.astimezone(UTC),
        status_after=ObligationStatus(row.status_after),
        reason=row.reason,
        caused_by_rule_version_id=None
        if row.caused_by_rule_version_id is None
        else RuleVersionId(row.caused_by_rule_version_id),
        actor=None if row.actor is None else UserId(row.actor),
        correlation_id=CorrelationId(row.correlation_id),
    )
