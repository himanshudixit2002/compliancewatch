"""In-memory repository and unit of work: the fakes for tests and the app before Postgres."""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date, datetime
from uuid import UUID

from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from obligation.domain.history import ObligationChange
from obligation.domain.model import Obligation, period_matches
from obligation.domain.repository import UnitOfWork


class MemoryObligationRepository:
    def __init__(self, store: dict[ObligationId, Obligation], tenant_id: TenantId) -> None:
        self._store = store
        self._tenant_id = tenant_id

    def get(self, obligation_id: ObligationId) -> Obligation | None:
        obligation = self._store.get(obligation_id)
        return obligation if obligation and obligation.tenant_id == self._tenant_id else None

    def find(
        self, business_id: BusinessId, rule_version_id: RuleVersionId, period_label: str | None
    ) -> Obligation | None:
        for obligation in self._store.values():
            if (
                obligation.tenant_id == self._tenant_id
                and obligation.business_id == business_id
                and obligation.rule_version_id == rule_version_id
                and obligation.period_label == period_label
            ):
                return obligation
        return None

    def open_for_rule_version(
        self, rule_version_id: RuleVersionId, period_label: str | None = None
    ) -> Sequence[Obligation]:
        return [
            obligation
            for obligation in self._store.values()
            if obligation.tenant_id == self._tenant_id
            and obligation.rule_version_id == rule_version_id
            and obligation.is_open
            and period_matches(obligation, period_label)
        ]

    def list_for_business(
        self,
        business_id: BusinessId,
        *,
        due_after: datetime | None,
        due_before: datetime | None,
        rule_version_id: RuleVersionId | None,
        limit: int,
    ) -> Sequence[Obligation]:
        bounded = due_after is not None or due_before is not None
        found = [
            obligation
            for obligation in self._store.values()
            if obligation.tenant_id == self._tenant_id
            and obligation.business_id == business_id
            and (rule_version_id is None or obligation.rule_version_id == rule_version_id)
            and not (bounded and obligation.due_at is None)
            and (
                due_after is None
                or (obligation.due_at is not None and obligation.due_at >= due_after)
            )
            and (
                due_before is None
                or (obligation.due_at is not None and obligation.due_at < due_before)
            )
        ]
        return sorted(found, key=_listing_order)[:limit]

    def add(self, obligation: Obligation) -> None:
        if obligation.id in self._store:
            raise ValueError(f"duplicate obligation {obligation.id}")
        self._store[obligation.id] = obligation

    def save(self, obligation: Obligation) -> None:
        self._store[obligation.id] = obligation


def _listing_order(
    obligation: Obligation,
) -> tuple[bool, datetime | None, bool, date | None, datetime, UUID]:
    """Due date with none last, then period start with none last, creation and id: the
    Postgres order."""
    period = obligation.period
    return (
        obligation.due_at is None,
        obligation.due_at,
        period is None,
        None if period is None else period.start,
        obligation.created_at,
        obligation.id.value,
    )


class MemoryEventSink:
    def __init__(self, published: list[DomainEvent]) -> None:
        self._published = published
        self.pending: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.pending.append(event)

    def commit(self) -> None:
        self._published.extend(self.pending)
        self.pending.clear()


class MemoryUnitOfWork:
    def __init__(
        self,
        store: dict[ObligationId, Obligation],
        events: list[DomainEvent],
        tenant_id: TenantId,
        changes: list[ObligationChange] | None = None,
    ) -> None:
        self._committed = store
        self._working: dict[ObligationId, Obligation] = {}
        self.obligations = MemoryObligationRepository(self._working, tenant_id)
        self.events = MemoryEventSink(events)
        self.history = MemoryChangeLog([] if changes is None else changes, tenant_id)

    def __enter__(self) -> "MemoryUnitOfWork":
        self._working.clear()
        self._working.update(self._committed)
        return self

    def __exit__(self, exc_type: object, *exc_info: object) -> None:
        if exc_type is None:
            self._committed.clear()
            self._committed.update(self._working)
            self.events.commit()
            self.history.commit()


class MemoryStore:
    """Holds every tenant's obligations and published events; makes units of work."""

    def __init__(self) -> None:
        self.obligations: dict[ObligationId, Obligation] = {}
        self.events: list[DomainEvent] = []
        self.changes: list[ObligationChange] = []

    def ping(self) -> bool:
        return True

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with MemoryUnitOfWork(self.obligations, self.events, tenant_id, self.changes) as uow:
            yield uow

    def of_tenant(self, tenant_id: TenantId) -> list[Obligation]:
        return [o for o in self.obligations.values() if o.tenant_id == tenant_id]


class MemoryChangeLog:
    """Appends wait in ``pending`` until the unit of work commits, like the event sink; reads
    see the committed log of the tenant and this unit's own appends."""

    def __init__(self, committed: list[ObligationChange], tenant_id: TenantId) -> None:
        self._committed = committed
        self._tenant_id = tenant_id
        self.pending: list[ObligationChange] = []

    def append(self, change: ObligationChange) -> None:
        if change.tenant_id != self._tenant_id:
            raise ValueError(f"change {change.id} belongs to another tenant")
        if any(c.id == change.id for c in (*self._committed, *self.pending)):
            raise ValueError(f"duplicate change {change.id}")
        self.pending.append(change)

    def for_obligation(self, obligation_id: ObligationId) -> Sequence[ObligationChange]:
        found = [
            change
            for change in (*self._committed, *self.pending)
            if change.tenant_id == self._tenant_id and change.obligation_id == obligation_id
        ]
        return sorted(found, key=lambda change: change.occurred_at)

    def commit(self) -> None:
        self._committed.extend(self.pending)
        self.pending.clear()
