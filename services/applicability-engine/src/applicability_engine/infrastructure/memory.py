"""In-memory repository and unit of work: the fakes for tests and the app before Postgres.

A unit of work appends to a pending list and adds it to the store when the block exits cleanly;
its reads see the committed decisions of its tenant and its own appends. Units run one at a time
(a store-level lock held from open to commit or rollback), like the obligation service's.
"""

import threading
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from uuid import UUID

from applicability_engine.domain.model import Decision, DecisionKey
from applicability_engine.domain.repository import UnitOfWork
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId


class MemoryDecisionRepository:
    def __init__(self, committed: dict[DecisionId, Decision], tenant_id: TenantId) -> None:
        self._committed = committed
        self._tenant_id = tenant_id
        self.pending: dict[DecisionId, Decision] = {}

    def add(self, decision: Decision) -> None:
        if decision.tenant_id != self._tenant_id:
            raise ValueError(f"decision {decision.decision_id} belongs to another tenant")
        if decision.decision_id in self._committed or decision.decision_id in self.pending:
            raise ValueError(f"duplicate decision {decision.decision_id}")
        self.pending[decision.decision_id] = decision

    def get(self, decision_id: DecisionId) -> Decision | None:
        decision = self.pending.get(decision_id) or self._committed.get(decision_id)
        return decision if decision and decision.tenant_id == self._tenant_id else None

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
            for decision in (*self._committed.values(), *self.pending.values())
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
        self, store: dict[DecisionId, Decision], events: list[DomainEvent], tenant_id: TenantId
    ) -> None:
        self.decisions = MemoryDecisionRepository(store, tenant_id)
        self.events = MemoryEventSink(events)

    def __enter__(self) -> "MemoryUnitOfWork":
        return self

    def __exit__(self, exc_type: object, *exc_info: object) -> None:
        if exc_type is None:
            self.decisions.commit()
            self.events.commit()


class MemoryStore:
    """Holds every tenant's decisions and published events; makes units of work."""

    def __init__(self) -> None:
        self.decisions: dict[DecisionId, Decision] = {}
        self.events: list[DomainEvent] = []
        self._lock = threading.Lock()

    def ping(self) -> bool:
        return True

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with self._lock, MemoryUnitOfWork(self.decisions, self.events, tenant_id) as uow:
            yield uow
