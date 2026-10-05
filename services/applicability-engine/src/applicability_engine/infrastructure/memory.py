"""In-memory repositories and unit of work: the fakes for tests and the app before Postgres.

A unit of work collects its writes and adds them to the store when the block exits cleanly; its
reads see the committed rows of its tenant and its own writes. Units run one at a time (a
store-level lock held from open to commit or rollback), like the obligation service's. The
rules the Postgres tables enforce hold here too: a write of another tenant's row is refused
(row-level security), a decision is stored once per id and per (trigger_ref, business, rule
version), and at most one review item is open per business and rule version. The directory is
the one table whose reads cross tenants (``MemoryStore.directory``). Audit entries go to
``MemoryStore.audit`` through ``py_common.audit``'s twin of the audit table, with the unit.
"""

import threading
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from uuid import UUID

from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.model import Decision, DecisionKey
from applicability_engine.domain.repository import UnitOfWork
from applicability_engine.domain.review import (
    ReviewItem,
    ReviewItemId,
    ReviewItemKey,
    ReviewStatus,
)
from domain_kernel.audit import AuditEntry
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
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


class MemoryStore:
    """Holds every tenant's decisions, directory entries, review items, published events and
    audit entries; makes units of work."""

    def __init__(self) -> None:
        self.decisions: dict[DecisionId, Decision] = {}
        self.directory: dict[BusinessId, DirectoryEntry] = {}
        self.reviews: dict[ReviewItemId, ReviewItem] = {}
        self.events: list[DomainEvent] = []
        self.audit: list[AuditEntry] = []
        self._lock = threading.Lock()

    def ping(self) -> bool:
        return True

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with self._lock, MemoryUnitOfWork(self, tenant_id) as uow:
            yield uow
