"""In-memory repository and unit of work: the fakes for tests and the app before Postgres.

A unit of work works on a copy of the obligations and replaces them when the block exits cleanly.
Units run one at a time (a store-level lock held from open to commit or rollback), so two
overlapping requests, of one tenant or of two, cannot both start from the same copy and lose each
other's writes.
"""

import threading
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date, datetime
from uuid import UUID

from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from obligation.domain.history import ObligationChange
from obligation.domain.model import Obligation, period_matches
from obligation.domain.reminders import Reminder
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
        self,
        rule_version_id: RuleVersionId,
        period_label: str | None = None,
        *,
        business_id: BusinessId | None = None,
    ) -> Sequence[Obligation]:
        found = [
            obligation
            for obligation in self._store.values()
            if obligation.tenant_id == self._tenant_id
            and obligation.rule_version_id == rule_version_id
            and obligation.is_open
            and period_matches(obligation, period_label)
            and (business_id is None or obligation.business_id == business_id)
        ]
        return sorted(found, key=_rule_version_order)

    def open_due_between(self, due_after: datetime, due_before: datetime) -> Sequence[Obligation]:
        found = [
            obligation
            for obligation in self._store.values()
            if obligation.tenant_id == self._tenant_id
            and obligation.is_open
            and obligation.due_at is not None
            and due_after <= obligation.due_at < due_before
        ]
        return sorted(found, key=lambda o: (o.due_at, o.id.value))

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


def _rule_version_order(obligation: Obligation) -> tuple[bool, date | None, datetime, UUID]:
    """Period start with none first, creation and id: the Postgres order."""
    period = obligation.period
    return (
        period is not None,
        None if period is None else period.start,
        obligation.created_at,
        obligation.id.value,
    )


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
        reminders: list[Reminder] | None = None,
    ) -> None:
        self._committed = store
        self._working: dict[ObligationId, Obligation] = {}
        self.obligations = MemoryObligationRepository(self._working, tenant_id)
        self.events = MemoryEventSink(events)
        self.history = MemoryChangeLog([] if changes is None else changes, tenant_id)
        self.reminders = MemoryReminderLog([] if reminders is None else reminders, tenant_id)

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
            self.reminders.commit()


class MemoryStore:
    """Holds every tenant's obligations, published events, changes and reminders; makes units
    of work, and is the tenant directory of the sweeps (``tenants``)."""

    def __init__(self) -> None:
        self.obligations: dict[ObligationId, Obligation] = {}
        self.events: list[DomainEvent] = []
        self.changes: list[ObligationChange] = []
        self.reminders: list[Reminder] = []
        self._lock = threading.Lock()

    def ping(self) -> bool:
        return True

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with (
            self._lock,
            MemoryUnitOfWork(
                self.obligations, self.events, tenant_id, self.changes, self.reminders
            ) as uow,
        ):
            yield uow

    def of_tenant(self, tenant_id: TenantId) -> list[Obligation]:
        return [o for o in self.obligations.values() if o.tenant_id == tenant_id]

    def tenants(self) -> Sequence[TenantId]:
        found = {o.tenant_id for o in list(self.obligations.values())}
        return sorted(found, key=lambda tenant: tenant.value)


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


class MemoryReminderLog:
    """Adds wait in ``pending`` until the unit of work commits; reads see the committed
    reminders of the tenant and this unit's own adds. Refuses what Postgres's unique
    constraints refuse."""

    def __init__(self, committed: list[Reminder], tenant_id: TenantId) -> None:
        self._committed = committed
        self._tenant_id = tenant_id
        self.pending: list[Reminder] = []

    def for_obligation(self, obligation_id: ObligationId) -> Sequence[Reminder]:
        found = [
            reminder
            for reminder in (*self._committed, *self.pending)
            if reminder.tenant_id == self._tenant_id and reminder.obligation_id == obligation_id
        ]
        return sorted(found, key=lambda reminder: reminder.reminder_index)

    def add(self, reminder: Reminder) -> None:
        if reminder.tenant_id != self._tenant_id:
            raise ValueError(f"reminder {reminder.id} belongs to another tenant")
        for other in (*self._committed, *self.pending):
            if other.obligation_id != reminder.obligation_id:
                continue
            if (other.due_at, other.threshold_days) == (reminder.due_at, reminder.threshold_days):
                raise ValueError(f"duplicate reminder of obligation {reminder.obligation_id}")
            if other.reminder_index == reminder.reminder_index:
                raise ValueError(f"duplicate reminder index of obligation {reminder.obligation_id}")
        self.pending.append(reminder)

    def commit(self) -> None:
        self._committed.extend(self.pending)
        self.pending.clear()
