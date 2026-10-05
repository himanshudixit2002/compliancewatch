"""In-memory repositories and unit of work: the fakes for tests and the app before Postgres.

A unit of work collects its writes and adds them to the store when the block exits cleanly; its
reads see the committed rows of its tenant and its own writes. Units run one at a time (a
store-level lock held from open to commit or rollback), like the obligation service's. The
rules the Postgres tables enforce hold here too: a write of another tenant's row is refused
(row-level security), a decision is stored once per id and per (trigger_ref, business, rule
version), and at most one review item is open per business and rule version. The directory is
the one table whose reads cross tenants (``MemoryStore.directory``; ``MemoryBusinessDirectory``
reads it as ``PostgresBusinessDirectory`` does). Audit entries go to ``MemoryStore.audit`` through
``py_common.audit``'s twin of the audit table, with the unit.

``MemoryStore.fanouts`` makes the units over the fan-out runs and the global hold, of no tenant,
like ``PostgresFanOutUnitOfWorkFactory``; their audit entries are of no tenant too.
"""

import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from uuid import UUID

from applicability_engine.domain.directory import DirectoryEntry, DirectoryKey
from applicability_engine.domain.fanout import FanOutHold, FanOutRun, FanOutRunKey, FanOutStatus
from applicability_engine.domain.impact import ImpactEntry
from applicability_engine.domain.model import Decision, DecisionKey
from applicability_engine.domain.repository import FanOutUnitOfWork, UnitOfWork
from applicability_engine.domain.review import (
    ReviewItem,
    ReviewItemId,
    ReviewItemKey,
    ReviewStatus,
)
from domain_kernel.audit import AuditEntry
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability
from py_common.audit import MemoryAuditSink


def _require_tenant(owner: TenantId, tenant_id: TenantId, what: str) -> None:
    if owner != tenant_id:
        raise ValueError(f"{what} belongs to another tenant")


class MemoryDecisionRepository:
    def __init__(self, committed: dict[DecisionId, Decision], tenant_id: TenantId) -> None:
        self._committed = committed
        self._tenant_id = tenant_id
        self.pending: dict[DecisionId, Decision] = {}

    def _all(self) -> Iterator[Decision]:
        yield from self._committed.values()
        yield from self.pending.values()

    def _clashes(self, decision: Decision) -> bool:
        if decision.decision_id in self._committed or decision.decision_id in self.pending:
            return True
        if decision.trigger_ref is None:
            return False
        key = (decision.trigger_ref, decision.business_id, decision.rule_version_id)
        return any(
            (other.trigger_ref, other.business_id, other.rule_version_id) == key
            for other in self._all()
        )

    def add(self, decision: Decision) -> None:
        _require_tenant(decision.tenant_id, self._tenant_id, f"decision {decision.decision_id}")
        if self._clashes(decision):
            raise ValueError(f"duplicate decision {decision.decision_id}")
        self.pending[decision.decision_id] = decision

    def add_if_absent(self, decision: Decision) -> bool:
        _require_tenant(decision.tenant_id, self._tenant_id, f"decision {decision.decision_id}")
        if self._clashes(decision):
            return False
        self.pending[decision.decision_id] = decision
        return True

    def get(self, decision_id: DecisionId) -> Decision | None:
        decision = self.pending.get(decision_id) or self._committed.get(decision_id)
        return decision if decision and decision.tenant_id == self._tenant_id else None

    def get_many(self, decision_ids: Sequence[DecisionId]) -> Sequence[Decision]:
        found = (self.get(decision_id) for decision_id in dict.fromkeys(decision_ids))
        return [decision for decision in found if decision is not None]

    def latest(self, business_id: BusinessId, rule_version_id: RuleVersionId) -> Decision | None:
        found = self.list_for_business(
            business_id, rule_version_id=rule_version_id, after=None, limit=1
        )
        return found[0] if found else None

    def list_for_business(
        self,
        business_id: BusinessId,
        *,
        rule_version_id: RuleVersionId | None,
        after: DecisionKey | None,
        limit: int,
    ) -> Sequence[Decision]:
        bound = None if after is None else (after.decided_at, after.decision_id.value)
        found = [
            decision
            for decision in self._all()
            if decision.tenant_id == self._tenant_id
            and decision.business_id == business_id
            and (rule_version_id is None or decision.rule_version_id == rule_version_id)
            and (bound is None or _order(decision) < bound)
        ]
        return sorted(found, key=_order, reverse=True)[:limit]

    def visible(self) -> list[Decision]:
        """The tenant's decisions, stored or written in this unit."""
        return [decision for decision in self._all() if decision.tenant_id == self._tenant_id]

    def commit(self) -> None:
        self._committed.update(self.pending)
        self.pending.clear()


def _order(decision: Decision) -> tuple[datetime, UUID]:
    """Decided at, then id: the Postgres order (descending in the listing)."""
    return (decision.decided_at, decision.decision_id.value)


class MemoryDirectoryRepository:
    def __init__(self, committed: dict[BusinessId, DirectoryEntry], tenant_id: TenantId) -> None:
        self._committed = committed
        self._tenant_id = tenant_id
        self.pending: dict[BusinessId, DirectoryEntry] = {}

    def add(self, entry: DirectoryEntry) -> bool:
        _require_tenant(entry.tenant_id, self._tenant_id, f"directory entry {entry.business_id}")
        if entry.business_id in self._committed or entry.business_id in self.pending:
            return False
        self.pending[entry.business_id] = entry
        return True

    def get(self, business_id: BusinessId) -> DirectoryEntry | None:
        """The tenant's entry of the node, stored or written in this unit."""
        entry = self.pending.get(business_id) or self._committed.get(business_id)
        return entry if entry is not None and entry.tenant_id == self._tenant_id else None

    def commit(self) -> None:
        self._committed.update(self.pending)
        self.pending.clear()


class MemoryReviewItemRepository:
    def __init__(self, committed: dict[ReviewItemId, ReviewItem], tenant_id: TenantId) -> None:
        self._committed = committed
        self._tenant_id = tenant_id
        self.pending: dict[ReviewItemId, ReviewItem] = {}

    def _current(self) -> dict[ReviewItemId, ReviewItem]:
        return {**self._committed, **self.pending}

    def _visible(self) -> list[ReviewItem]:
        return [item for item in self._current().values() if item.tenant_id == self._tenant_id]

    def add(self, item: ReviewItem) -> bool:
        _require_tenant(item.tenant_id, self._tenant_id, f"review item {item.item_id}")
        current = self._current()
        if item.item_id in current:
            return False
        if item.is_open and any(
            other.is_open
            and (other.business_id, other.rule_version_id)
            == (item.business_id, item.rule_version_id)
            for other in current.values()
        ):
            return False
        self.pending[item.item_id] = item
        return True

    def get(self, item_id: ReviewItemId, *, for_update: bool = False) -> ReviewItem | None:
        item = self._current().get(item_id)
        return item if item is not None and item.tenant_id == self._tenant_id else None

    def open_for(
        self, business_id: BusinessId, rule_version_id: RuleVersionId
    ) -> ReviewItem | None:
        for item in self._visible():
            if item.is_open and (item.business_id, item.rule_version_id) == (
                business_id,
                rule_version_id,
            ):
                return item
        return None

    def save(self, item: ReviewItem) -> None:
        _require_tenant(item.tenant_id, self._tenant_id, f"review item {item.item_id}")
        if item.item_id not in self._current():
            raise ValueError(f"review item {item.item_id} is not stored")
        self.pending[item.item_id] = item

    def list(
        self, *, status: ReviewStatus | None, after: ReviewItemKey | None, limit: int
    ) -> Sequence[ReviewItem]:
        bound = None if after is None else (after.opened_at, after.item_id.value)
        found = [
            item
            for item in self._visible()
            if (status is None or item.status is status)
            and (bound is None or (item.opened_at, item.item_id.value) > bound)
        ]
        return sorted(found, key=lambda item: (item.opened_at, item.item_id.value))[:limit]

    def commit(self) -> None:
        self._committed.update(self.pending)
        self.pending.clear()


class MemoryImpactRepository:
    """The latest decision of a version per business, placed by the unit's directory, as
    ``SqlAlchemyImpactRepository`` reads them."""

    def __init__(
        self, decisions: MemoryDecisionRepository, directory: MemoryDirectoryRepository
    ) -> None:
        self._decisions = decisions
        self._directory = directory

    def _latest(self, rule_version_id: RuleVersionId) -> list[Decision]:
        latest: dict[BusinessId, Decision] = {}
        for decision in self._decisions.visible():
            if decision.rule_version_id != rule_version_id:
                continue
            known = latest.get(decision.business_id)
            if known is None or _order(decision) > _order(known):
                latest[decision.business_id] = decision
        return list(latest.values())

    def latest_by_entity(
        self,
        rule_version_id: RuleVersionId,
        *,
        result: Applicability | None,
        after: BusinessId | None,
        limit: int,
    ) -> Sequence[ImpactEntry]:
        placed: list[ImpactEntry] = []
        for decision in self._latest(rule_version_id):
            if result is not None and decision.result is not result:
                continue
            entry = self._directory.get(decision.business_id)
            placed.append(
                ImpactEntry(
                    entity_id=decision.business_id if entry is None else entry.entity_id,
                    level=None if entry is None else entry.level,
                    decision=decision,
                )
            )
        entities = sorted(
            {
                entry.entity_id.value
                for entry in placed
                if after is None or entry.entity_id.value > after.value
            }
        )[:limit]
        kept = [entry for entry in placed if entry.entity_id.value in set(entities)]
        return sorted(kept, key=lambda entry: (entry.entity_id.value, entry.business_id.value))

    def result_counts(self, rule_version_id: RuleVersionId) -> Mapping[Applicability, int]:
        counts: dict[Applicability, int] = {}
        for decision in self._latest(rule_version_id):
            counts[decision.result] = counts.get(decision.result, 0) + 1
        return counts


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
    def __init__(self, store: "MemoryStore", tenant_id: TenantId) -> None:
        self.decisions = MemoryDecisionRepository(store.decisions, tenant_id)
        self.directory = MemoryDirectoryRepository(store.directory, tenant_id)
        self.reviews = MemoryReviewItemRepository(store.reviews, tenant_id)
        self.impact = MemoryImpactRepository(self.decisions, self.directory)
        self.events = MemoryEventSink(store.events)
        self.audit = MemoryAuditSink(store.audit, tenant_id=tenant_id)

    def __enter__(self) -> "MemoryUnitOfWork":
        return self

    def __exit__(self, exc_type: object, *exc_info: object) -> None:
        if exc_type is None:
            self.decisions.commit()
            self.directory.commit()
            self.reviews.commit()
            self.events.commit()
            self.audit.commit()


class MemoryFanOutRunRepository:
    def __init__(self, committed: dict[RuleVersionId, FanOutRun]) -> None:
        self._committed = committed
        self.pending: dict[RuleVersionId, FanOutRun] = {}

    def _current(self) -> dict[RuleVersionId, FanOutRun]:
        return {**self._committed, **self.pending}

    def add_if_absent(self, run: FanOutRun) -> bool:
        if run.rule_version_id in self._current():
            return False
        self.pending[run.rule_version_id] = run
        return True

    def get(self, rule_version_id: RuleVersionId, *, for_update: bool = False) -> FanOutRun | None:
        return self._current().get(rule_version_id)

    def save(self, run: FanOutRun) -> None:
        if run.rule_version_id not in self._current():
            raise ValueError(f"no fan-out of {run.rule_version_id} is stored")
        self.pending[run.rule_version_id] = run

    def list(self, *, after: FanOutRunKey | None, limit: int) -> Sequence[FanOutRun]:
        bound = None if after is None else (after.started_at, after.rule_version_id.value)
        found = [
            run
            for run in self._current().values()
            if bound is None or (run.started_at, run.rule_version_id.value) < bound
        ]
        found.sort(key=lambda run: (run.started_at, run.rule_version_id.value), reverse=True)
        return found[:limit]

    def with_status(self, status: FanOutStatus) -> Sequence[FanOutRun]:
        found = [run for run in self._current().values() if run.status is status]
        return sorted(found, key=lambda run: (run.started_at, run.rule_version_id.value))

    def commit(self) -> None:
        self._committed.update(self.pending)
        self.pending.clear()


class MemoryFanOutHoldRepository:
    """The hold as a one-element list: empty while released."""

    def __init__(self, committed: list[FanOutHold]) -> None:
        self._committed = committed
        self._pending: list[FanOutHold] | None = None

    def _current(self) -> list[FanOutHold]:
        return self._committed if self._pending is None else self._pending

    def get(self, *, for_update: bool = False) -> FanOutHold | None:
        current = self._current()
        return current[0] if current else None

    def put(self, hold: FanOutHold) -> None:
        self._pending = [hold]

    def clear(self) -> bool:
        held = bool(self._current())
        self._pending = []
        return held

    def commit(self) -> None:
        if self._pending is not None:
            self._committed[:] = self._pending
            self._pending = None


class MemoryFanOutUnitOfWork:
    def __init__(self, store: "MemoryStore") -> None:
        self.runs = MemoryFanOutRunRepository(store.fanout_runs)
        self.hold = MemoryFanOutHoldRepository(store.fanout_hold)
        self.audit = MemoryAuditSink(store.audit, tenant_id=None)

    def __enter__(self) -> "MemoryFanOutUnitOfWork":
        return self

    def __exit__(self, exc_type: object, *exc_info: object) -> None:
        if exc_type is None:
            self.runs.commit()
            self.hold.commit()
            self.audit.commit()


class MemoryFanOutUnits:
    """The ``FanOutUnitOfWorkFactory`` of a memory store: one unit at a time, under the store's
    lock, like its tenant units."""

    def __init__(self, store: "MemoryStore") -> None:
        self._store = store

    def __call__(self) -> AbstractContextManager[FanOutUnitOfWork]:
        return self._unit()

    @contextmanager
    def _unit(self) -> Iterator[FanOutUnitOfWork]:
        with self._store.lock, MemoryFanOutUnitOfWork(self._store) as uow:
            yield uow


class MemoryBusinessDirectory:
    """The directory across tenants, as ``PostgresBusinessDirectory`` reads it: by tenant then
    node."""

    def __init__(self, store: "MemoryStore") -> None:
        self._store = store

    def entries(
        self,
        *,
        level: AttributeLevel | None = None,
        after: DirectoryKey | None = None,
        limit: int = 1_000,
        tenant_id: TenantId | None = None,
    ) -> Sequence[DirectoryEntry]:
        bound = None if after is None else (after.tenant_id.value, after.business_id.value)
        with self._store.lock:
            found = [
                entry
                for entry in self._store.directory.values()
                if (level is None or entry.level is level)
                and (tenant_id is None or entry.tenant_id == tenant_id)
                and (bound is None or (entry.tenant_id.value, entry.business_id.value) > bound)
            ]
        found.sort(key=lambda entry: (entry.tenant_id.value, entry.business_id.value))
        return found[:limit]

    def count(self, *, level: AttributeLevel, tenant_id: TenantId | None = None) -> int:
        with self._store.lock:
            return sum(
                1
                for entry in self._store.directory.values()
                if entry.level is level and (tenant_id is None or entry.tenant_id == tenant_id)
            )


class MemoryStore:
    """Holds every tenant's decisions, directory entries, review items, published events and
    audit entries, and the fan-out runs and the hold; makes units of work."""

    def __init__(self) -> None:
        self.decisions: dict[DecisionId, Decision] = {}
        self.directory: dict[BusinessId, DirectoryEntry] = {}
        self.reviews: dict[ReviewItemId, ReviewItem] = {}
        self.events: list[DomainEvent] = []
        self.audit: list[AuditEntry] = []
        self.fanout_runs: dict[RuleVersionId, FanOutRun] = {}
        self.fanout_hold: list[FanOutHold] = []
        self.lock = threading.Lock()
        self.fanouts = MemoryFanOutUnits(self)
        """The units over the fan-out runs and the hold."""

    def ping(self) -> bool:
        return True

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with self.lock, MemoryUnitOfWork(self, tenant_id) as uow:
            yield uow
