"""In-memory repository and unit of work: the fakes for tests and the app before Postgres."""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager

from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
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

    def add(self, obligation: Obligation) -> None:
        if obligation.id in self._store:
            raise ValueError(f"duplicate obligation {obligation.id}")
        self._store[obligation.id] = obligation

    def save(self, obligation: Obligation) -> None:
        self._store[obligation.id] = obligation


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
        self, store: dict[ObligationId, Obligation], events: list[DomainEvent], tenant_id: TenantId
    ) -> None:
        self._committed = store
        self._working: dict[ObligationId, Obligation] = {}
        self.obligations = MemoryObligationRepository(self._working, tenant_id)
        self.events = MemoryEventSink(events)

    def __enter__(self) -> "MemoryUnitOfWork":
        self._working.clear()
        self._working.update(self._committed)
        return self

    def __exit__(self, exc_type: object, *exc_info: object) -> None:
        if exc_type is None:
            self._committed.clear()
            self._committed.update(self._working)
            self.events.commit()


class MemoryStore:
    """Holds every tenant's obligations and published events; makes units of work."""

    def __init__(self) -> None:
        self.obligations: dict[ObligationId, Obligation] = {}
        self.events: list[DomainEvent] = []

    def ping(self) -> bool:
        return True

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with MemoryUnitOfWork(self.obligations, self.events, tenant_id) as uow:
            yield uow

    def of_tenant(self, tenant_id: TenantId) -> list[Obligation]:
        return [o for o in self.obligations.values() if o.tenant_id == tenant_id]
