"""The Postgres unit of work: one transaction with the tenant setting for row-level security,
the obligation repository on it, the outbox writer as the event sink, and the change log, the
reminder log, the cached rule versions and the applied decisions on the same session, so each of
their rows commits or rolls back with the outbox rows.

``PostgresUnitOfWorkFactory.on_connection(connection)`` makes units inside a transaction someone
else owns, such as a consumer's inbox transaction (``py_common.outbox.sync``): the handler's
writes, their outbox rows and the ``processed_event`` row then commit together. Units of several
tenants may run one after the other on one connection: each sets its tenant when it opens.

``obligation_tenant`` lists the tenants that have obligations. The repository records the tenant
of the unit when it adds the unit's first obligation, under the tenant's own setting (the
directory's write policy checks it); ``PostgresTenantDirectory`` reads the ids across tenants for
the sweeps, which then open one unit of work per tenant (migration 0003), and
``ConnectionTenantDirectory`` reads them on a connection whose transaction is open, as the rule
events consumer does.

``rule_version_ref`` is rule-level (migration 0004): ``SqlAlchemyRuleVersionRefs`` works on any
connection, with or without a tenant setting. ``merge`` locks the version's row, inserting it
first when it is missing, so a rule event and a decision about the same version run one after
the other: whichever comes second sees what the first one wrote.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any, Final, Self
from uuid import UUID

from sqlalchemy import Connection, Engine, RowMapping, create_engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
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
from domain_kernel.status import ClosureReason, ObligationStatus, RuleVersionStatus
from obligation.domain.history import ChangeKind, ObligationChange
from obligation.domain.model import Obligation
from obligation.domain.reminders import Reminder
from obligation.domain.repository import UnitOfWork, UnitOfWorkFactory
from obligation.domain.rule_versions import AppliedDecision, Citation, RuleVersionRef
from obligation.infrastructure.models import (
    TENANT_SETTING,
    ObligationChangeRow,
    ObligationDecisionRow,
    ObligationReminderRow,
    ObligationRow,
    ObligationTenantRow,
    RuleVersionRefRow,
)
from py_common.outbox import OutboxWriter

OPEN_STATUSES = ("open", "in_progress")
MERGE_ATTEMPTS: Final = 2
"""A version cached by another transaction between the read and the insert is merged on the
second attempt."""


class SqlAlchemyObligationRepository:
    def __init__(self, session: Session, tenant_id: TenantId) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._tenant_listed = False

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
        self,
        rule_version_id: RuleVersionId,
        period_label: str | None = None,
        *,
        business_id: BusinessId | None = None,
    ) -> Sequence[Obligation]:
        statement = (
            select(ObligationRow)
            .where(
                ObligationRow.rule_version_id == rule_version_id.value,
                ObligationRow.status.in_(OPEN_STATUSES),
            )
            .order_by(
                ObligationRow.period_start.nulls_first(), ObligationRow.created_at, ObligationRow.id
            )
        )
        if period_label is not None:
            statement = statement.where(ObligationRow.period_label == period_label)
        if business_id is not None:
            statement = statement.where(ObligationRow.business_id == business_id.value)
        return [_to_obligation(row) for row in self._session.scalars(statement).all()]

    def open_due_between(self, due_after: datetime, due_before: datetime) -> Sequence[Obligation]:
        statement = (
            select(ObligationRow)
            .where(
                ObligationRow.status.in_(OPEN_STATUSES),
                ObligationRow.due_at >= due_after,
                ObligationRow.due_at < due_before,
            )
            .order_by(ObligationRow.due_at, ObligationRow.id)
        )
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
        if not self._tenant_listed:
            self._session.execute(
                insert(ObligationTenantRow)
                .values(tenant_id=self._tenant_id.value)
                .on_conflict_do_nothing(index_elements=["tenant_id"])
            )
            self._tenant_listed = True

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
        self.reminders = SqlAlchemyReminderLog(session)
        self.rule_versions = SqlAlchemyRuleVersionRefs(connection)
        self.decisions = SqlAlchemyAppliedDecisions(connection, tenant_id)


class ConnectionUnitOfWorkFactory:
    """Units of work inside the transaction of ``connection``, begun on it when it has none yet.
    A unit neither commits nor rolls back: the owner of the connection does. Each unit sets its
    tenant when it opens, and the setting holds until the next unit sets another or the
    transaction ends, so units of several tenants may follow one another on one connection but
    never interleave."""

    def __init__(self, connection: Connection, writer: OutboxWriter) -> None:
        self._connection = connection
        self._writer = writer

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._open(tenant_id)

    @contextmanager
    def _open(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        if not self._connection.in_transaction():
            # A consumer unit that begins on write has no transaction yet. A session given such
            # a connection would begin one of its own and roll it back when it closes; begun
            # here, the session joins it, and the owner of the connection still ends it.
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


class SqlAlchemyReminderLog:
    """The reminders on the unit of work's session; row-level security scopes it to the
    tenant."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def for_obligation(self, obligation_id: ObligationId) -> Sequence[Reminder]:
        statement = (
            select(ObligationReminderRow)
            .where(ObligationReminderRow.obligation_id == obligation_id.value)
            .order_by(ObligationReminderRow.reminder_index)
        )
        return [_to_reminder(row) for row in self._session.scalars(statement).all()]

    def add(self, reminder: Reminder) -> None:
        self._session.add(
            ObligationReminderRow(
                id=reminder.id.value,
                tenant_id=reminder.tenant_id.value,
                obligation_id=reminder.obligation_id.value,
                due_at=reminder.due_at,
                threshold_days=reminder.threshold_days,
                reminder_index=reminder.reminder_index,
                sent_at=reminder.sent_at,
            )
        )
        self._session.flush()


def _to_reminder(row: ObligationReminderRow) -> Reminder:
    return Reminder(
        id=EventId(row.id),
        tenant_id=TenantId(row.tenant_id),
        obligation_id=ObligationId(row.obligation_id),
        due_at=row.due_at.astimezone(UTC),
        threshold_days=row.threshold_days,
        reminder_index=row.reminder_index,
        sent_at=row.sent_at.astimezone(UTC),
    )


class PostgresTenantDirectory:
    """The ``obligation_tenant`` ids, read without a tenant setting: the table's read policy
    admits every row, and it holds nothing but the ids."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def tenants(self) -> Sequence[TenantId]:
        statement = select(ObligationTenantRow.tenant_id).order_by(ObligationTenantRow.tenant_id)
        with self._engine.connect() as connection:
            return [TenantId(value) for value in connection.execute(statement).scalars()]


class ConnectionTenantDirectory:
    """The ``obligation_tenant`` ids, read on a connection whose transaction is open, whatever
    tenant it has set: the table's read policy admits every row."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def tenants(self) -> Sequence[TenantId]:
        statement = select(ObligationTenantRow.tenant_id).order_by(ObligationTenantRow.tenant_id)
        return [TenantId(value) for value in self._connection.execute(statement).scalars()]


class SqlAlchemyRuleVersionRefs:
    """The cached rule versions on a connection (``rule_version_ref``, rule-level rows)."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(self, rule_version_id: RuleVersionId, *, lock: bool = False) -> RuleVersionRef | None:
        statement = select(RuleVersionRefRow.__table__).where(
            RuleVersionRefRow.rule_version_id == rule_version_id.value
        )
        if lock:
            statement = statement.with_for_update()
        row = self._connection.execute(statement).mappings().first()
        return None if row is None else _to_ref(row)

    def merge(self, ref: RuleVersionRef) -> RuleVersionRef:
        for _ in range(MERGE_ATTEMPTS):
            current = self.get(ref.rule_version_id, lock=True)
            if current is None:
                inserted = self._connection.execute(
                    insert(RuleVersionRefRow)
                    .values(_ref_values(ref))
                    .on_conflict_do_nothing(index_elements=["rule_version_id"])
                    .returning(RuleVersionRefRow.rule_version_id)
                ).first()
                if inserted is not None:
                    return ref
                continue
            merged = current.merge(ref)
            if merged != current:
                self._connection.execute(
                    update(RuleVersionRefRow)
                    .where(RuleVersionRefRow.rule_version_id == ref.rule_version_id.value)
                    .values(_ref_values(merged))
                )
            return merged
        raise RuntimeError(f"rule version {ref.rule_version_id} could not be cached")


def _ref_values(ref: RuleVersionRef) -> dict[str, Any]:
    return {
        "rule_version_id": ref.rule_version_id.value,
        "rule_key": ref.rule_key,
        "status": ref.status.value,
        "title": ref.title,
        "effective_from": ref.effective_from,
        "effective_to": ref.effective_to,
        "seed_status": ref.seed_status,
        "approved_by": [approver.value for approver in ref.approved_by],
        "published_at": ref.published_at,
        "citations": [_citation_mapping(citation) for citation in ref.citations],
        "fetched_at": ref.fetched_at,
    }


def _citation_mapping(citation: Citation) -> dict[str, object]:
    return {
        "citation_id": str(citation.citation_id),
        "clause_id": str(citation.clause_id),
        "document_id": str(citation.document_id),
        "clause_ref": citation.clause_ref,
        "quote": citation.quote,
        "match_score": citation.match_score,
        "verified_at": None if citation.verified_at is None else citation.verified_at.isoformat(),
    }


def _citation(data: Mapping[str, Any]) -> Citation:
    verified_at = data.get("verified_at")
    score = data.get("match_score")
    return Citation(
        citation_id=UUID(str(data["citation_id"])),
        clause_id=UUID(str(data["clause_id"])),
        document_id=UUID(str(data["document_id"])),
        clause_ref=str(data["clause_ref"]),
        quote=str(data["quote"]),
        match_score=None if score is None else float(score),
        verified_at=None if verified_at is None else datetime.fromisoformat(str(verified_at)),
    )


def _to_ref(row: RowMapping) -> RuleVersionRef:
    published_at = row["published_at"]
    return RuleVersionRef(
        rule_version_id=RuleVersionId(row["rule_version_id"]),
        rule_key=row["rule_key"],
        status=RuleVersionStatus(row["status"]),
        title=row["title"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        seed_status=row["seed_status"],
        approved_by=tuple(UserId(approver) for approver in row["approved_by"]),
        published_at=None if published_at is None else published_at.astimezone(UTC),
        citations=tuple(_citation(item) for item in row["citations"]),
        fetched_at=row["fetched_at"].astimezone(UTC),
    )


class SqlAlchemyAppliedDecisions:
    """The tenant's latest decision per business and rule version on the unit's connection;
    row-level security scopes it to the tenant the unit set."""

    def __init__(self, connection: Connection, tenant_id: TenantId) -> None:
        self._connection = connection
        self._tenant_id = tenant_id

    def record(self, decision: AppliedDecision) -> bool:
        values = insert(ObligationDecisionRow).values(
            tenant_id=decision.tenant_id.value,
            business_id=decision.business_id.value,
            rule_version_id=decision.rule_version_id.value,
            decision_id=decision.decision_id.value,
            applies=decision.applies,
            decided_at=decision.decided_at,
        )
        statement = values.on_conflict_do_update(
            index_elements=["business_id", "rule_version_id"],
            set_={
                "decision_id": values.excluded.decision_id,
                "applies": values.excluded.applies,
                "decided_at": values.excluded.decided_at,
                "recorded_at": func.now(),
            },
            where=ObligationDecisionRow.decided_at <= values.excluded.decided_at,
        ).returning(ObligationDecisionRow.business_id)
        return self._connection.execute(statement).first() is not None

    def applying(self) -> Sequence[AppliedDecision]:
        statement = (
            select(ObligationDecisionRow.__table__)
            .where(
                ObligationDecisionRow.tenant_id == self._tenant_id.value,
                ObligationDecisionRow.applies.is_(True),
            )
            .order_by(ObligationDecisionRow.business_id, ObligationDecisionRow.rule_version_id)
        )
        return [
            AppliedDecision(
                tenant_id=TenantId(row["tenant_id"]),
                business_id=BusinessId(row["business_id"]),
                rule_version_id=RuleVersionId(row["rule_version_id"]),
                decision_id=DecisionId(row["decision_id"]),
                applies=row["applies"],
                decided_at=row["decided_at"].astimezone(UTC),
            )
            for row in self._connection.execute(statement).mappings()
        ]
