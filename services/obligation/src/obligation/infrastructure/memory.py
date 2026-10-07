"""In-memory repository and unit of work: the fakes for tests and the app before Postgres.

A unit of work works on a copy of the obligations, the cached rule versions and the applied
decisions, and replaces them when the block exits cleanly; the events, changes, comments,
reminders and audit entries it writes wait until then too. Units run one at a time (a store-level
lock held from open to commit or rollback), so two overlapping requests, of one tenant or of two,
cannot both start from the same copy and lose each other's writes, and a ``lock``ed read needs no
lock of its own. ``MemoryStore.rule_version_refs`` reads and writes the cached versions outside a
unit, under the same lock, as the rule events consumer does on its connection.
"""

import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import date, datetime
from uuid import UUID

from domain_kernel.audit import AuditEntry
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from domain_kernel.status import ObligationStatus
from obligation.domain.comments import ObligationComment
from obligation.domain.history import ObligationChange
from obligation.domain.model import Obligation, period_matches
from obligation.domain.reminders import Reminder
from obligation.domain.repository import ExportAfter, ListingAfter, UnitOfWork
from obligation.domain.rule_versions import AppliedDecision, RuleVersionRef
from py_common.audit import MemoryAuditSink

DecisionKey = tuple[BusinessId, RuleVersionId]


class MemoryObligationRepository:
    def __init__(self, store: dict[ObligationId, Obligation], tenant_id: TenantId) -> None:
        self._store = store
        self._tenant_id = tenant_id

    def get(self, obligation_id: ObligationId, *, lock: bool = False) -> Obligation | None:
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

    def page_for_business(
        self,
        business_id: BusinessId,
        *,
        statuses: frozenset[ObligationStatus],
        due_after: datetime | None,
        due_before: datetime | None,
        after: ListingAfter | None,
        limit: int,
    ) -> Sequence[Obligation]:
        bounded = due_after is not None or due_before is not None
        found = [
            obligation
            for obligation in self._store.values()
            if obligation.tenant_id == self._tenant_id
            and obligation.business_id == business_id
            and (not statuses or obligation.status in statuses)
            and not (bounded and obligation.due_at is None)
            and (
                due_after is None
                or (obligation.due_at is not None and obligation.due_at >= due_after)
            )
            and (
                due_before is None
                or (obligation.due_at is not None and obligation.due_at < due_before)
            )
            and (after is None or _page_key(obligation) > _after_key(after))
        ]
        return sorted(found, key=_page_key)[:limit]

    def export_page(self, after: ExportAfter | None, limit: int) -> Sequence[Obligation]:
        found = [
            obligation
            for obligation in self._store.values()
            if obligation.tenant_id == self._tenant_id
        ]
        return _export_page(found, lambda o: (o.created_at, o.id.value), after, limit)

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


def _page_key(obligation: Obligation) -> tuple[bool, datetime | None, UUID]:
    """Due date with none last, then id: the order of the public list, as Postgres sorts it."""
    return (obligation.due_at is None, obligation.due_at, obligation.id.value)


def _after_key(after: ListingAfter) -> tuple[bool, datetime | None, UUID]:
    return (after.due_at is None, after.due_at, after.obligation_id.value)


def _export_page[T](
    rows: Iterable[T],
    key: Callable[[T], tuple[datetime, UUID]],
    after: ExportAfter | None,
    limit: int,
) -> list[T]:
    """The rows after ``after`` in the order of ``key`` (a time and an id), at most ``limit``:
    the keyset page Postgres reads."""
    start = None if after is None else (after.at, after.id)
    found = [row for row in rows if start is None or key(row) > start]
    return sorted(found, key=key)[:limit]


class MemoryEventSink:
    def __init__(self, published: list[DomainEvent]) -> None:
        self._published = published
        self.pending: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.pending.append(event)

    def commit(self) -> None:
        self._published.extend(self.pending)
        self.pending.clear()


class MemoryRuleVersionRefs:
    """The cached rule versions in a dict; the store's lock, or the unit's, keeps one writer."""

    def __init__(self, refs: dict[RuleVersionId, RuleVersionRef]) -> None:
        self._refs = refs

    def get(self, rule_version_id: RuleVersionId, *, lock: bool = False) -> RuleVersionRef | None:
        return self._refs.get(rule_version_id)

    def merge(self, ref: RuleVersionRef) -> RuleVersionRef:
        current = self._refs.get(ref.rule_version_id)
        merged = ref if current is None else current.merge(ref)
        self._refs[ref.rule_version_id] = merged
        return merged


class MemoryAppliedDecisions:
    """The latest decision per business and rule version; reads and writes see one tenant."""

    def __init__(self, decisions: dict[DecisionKey, AppliedDecision], tenant_id: TenantId) -> None:
        self._decisions = decisions
        self._tenant_id = tenant_id

    def record(self, decision: AppliedDecision) -> bool:
        if decision.tenant_id != self._tenant_id:
            raise ValueError(f"decision {decision.decision_id} belongs to another tenant")
        key = (decision.business_id, decision.rule_version_id)
        if not decision.supersedes(self._decisions.get(key)):
            return False
        self._decisions[key] = decision
        return True

    def applying(self) -> Sequence[AppliedDecision]:
        found = [
            decision
            for decision in self._decisions.values()
            if decision.tenant_id == self._tenant_id and decision.applies
        ]
        return sorted(found, key=lambda d: (d.business_id.value, d.rule_version_id.value))


class MemoryUnitOfWork:
    def __init__(
        self,
        store: dict[ObligationId, Obligation],
        events: list[DomainEvent],
        tenant_id: TenantId,
        changes: list[ObligationChange] | None = None,
        reminders: list[Reminder] | None = None,
        refs: dict[RuleVersionId, RuleVersionRef] | None = None,
        decisions: dict[DecisionKey, AppliedDecision] | None = None,
        comments: list[ObligationComment] | None = None,
        audit: list[AuditEntry] | None = None,
    ) -> None:
        self._committed = store
        self._working: dict[ObligationId, Obligation] = {}
        self._committed_refs = {} if refs is None else refs
        self._working_refs: dict[RuleVersionId, RuleVersionRef] = {}
        self._committed_decisions = {} if decisions is None else decisions
        self._working_decisions: dict[DecisionKey, AppliedDecision] = {}
        self.obligations = MemoryObligationRepository(self._working, tenant_id)
        self.events = MemoryEventSink(events)
        self.history = MemoryChangeLog([] if changes is None else changes, tenant_id)
        self.comments = MemoryCommentLog([] if comments is None else comments, tenant_id)
        self.reminders = MemoryReminderLog([] if reminders is None else reminders, tenant_id)
        self.rule_versions = MemoryRuleVersionRefs(self._working_refs)
        self.decisions = MemoryAppliedDecisions(self._working_decisions, tenant_id)
        self.audit = MemoryAuditSink([] if audit is None else audit, tenant_id=tenant_id)

    def __enter__(self) -> "MemoryUnitOfWork":
        self._working.clear()
        self._working.update(self._committed)
        self._working_refs.clear()
        self._working_refs.update(self._committed_refs)
        self._working_decisions.clear()
        self._working_decisions.update(self._committed_decisions)
        return self

    def __exit__(self, exc_type: object, *exc_info: object) -> None:
        if exc_type is None:
            self._committed.clear()
            self._committed.update(self._working)
            self._committed_refs.clear()
            self._committed_refs.update(self._working_refs)
            self._committed_decisions.clear()
            self._committed_decisions.update(self._working_decisions)
            self.events.commit()
            self.history.commit()
            self.comments.commit()
            self.reminders.commit()
            self.audit.commit()


class MemoryStore:
    """Holds every tenant's obligations, published events, changes, comments, reminders, applied
    decisions and audit entries, and the cached rule versions; makes units of work, and is the
    tenant directory of the sweeps (``tenants``)."""

    def __init__(self) -> None:
        self.obligations: dict[ObligationId, Obligation] = {}
        self.events: list[DomainEvent] = []
        self.changes: list[ObligationChange] = []
        self.comments: list[ObligationComment] = []
        self.reminders: list[Reminder] = []
        self.rule_versions: dict[RuleVersionId, RuleVersionRef] = {}
        self.decisions: dict[DecisionKey, AppliedDecision] = {}
        self.audit: list[AuditEntry] = []
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
                self.obligations,
                self.events,
                tenant_id,
                self.changes,
                self.reminders,
                self.rule_versions,
                self.decisions,
                self.comments,
                self.audit,
            ) as uow,
        ):
            yield uow

    def rule_version_refs(self) -> "LockedRuleVersionRefs":
        """The cached rule versions outside a unit of work, each call under the store's lock."""
        return LockedRuleVersionRefs(self)

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

    def export_page(self, after: ExportAfter | None, limit: int) -> Sequence[ObligationChange]:
        found = [
            change
            for change in (*self._committed, *self.pending)
            if change.tenant_id == self._tenant_id
        ]
        return _export_page(found, lambda c: (c.occurred_at, c.id.value), after, limit)

    def commit(self) -> None:
        self._committed.extend(self.pending)
        self.pending.clear()


class MemoryCommentLog:
    """Adds wait in ``pending`` until the unit of work commits; reads see the committed comments
    of the tenant and this unit's own adds. Refuses another tenant's comment and a second one
    with an id already stored, as the table does."""

    def __init__(self, committed: list[ObligationComment], tenant_id: TenantId) -> None:
        self._committed = committed
        self._tenant_id = tenant_id
        self.pending: list[ObligationComment] = []

    def add(self, comment: ObligationComment) -> None:
        if comment.tenant_id != self._tenant_id:
            raise ValueError(f"comment {comment.id} belongs to another tenant")
        if any(c.id == comment.id for c in (*self._committed, *self.pending)):
            raise ValueError(f"duplicate comment {comment.id}")
        self.pending.append(comment)

    def for_obligation(self, obligation_id: ObligationId) -> Sequence[ObligationComment]:
        found = [
            comment
            for comment in (*self._committed, *self.pending)
            if comment.tenant_id == self._tenant_id and comment.obligation_id == obligation_id
        ]
        return sorted(found, key=lambda comment: (comment.created_at, comment.id.value))

    def export_page(self, after: ExportAfter | None, limit: int) -> Sequence[ObligationComment]:
        found = [
            comment
            for comment in (*self._committed, *self.pending)
            if comment.tenant_id == self._tenant_id
        ]
        return _export_page(found, lambda c: (c.created_at, c.id.value), after, limit)

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


class LockedRuleVersionRefs:
    """``RuleVersionRefs`` on a store's committed cache, each call under the store's lock; it
    must not be used while a unit of the same store is open on the thread."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def get(self, rule_version_id: RuleVersionId, *, lock: bool = False) -> RuleVersionRef | None:
        with self._store._lock:
            return MemoryRuleVersionRefs(self._store.rule_versions).get(rule_version_id)

    def merge(self, ref: RuleVersionRef) -> RuleVersionRef:
        with self._store._lock:
            return MemoryRuleVersionRefs(self._store.rule_versions).merge(ref)
