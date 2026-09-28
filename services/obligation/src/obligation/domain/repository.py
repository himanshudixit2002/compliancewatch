"""What the application layer needs from persistence, as protocols the infrastructure implements."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from obligation.domain.model import Obligation


class ObligationRepository(Protocol):
    """Reads and writes are scoped to the tenant the unit of work was opened for."""

    def get(self, obligation_id: ObligationId) -> Obligation | None: ...

    def find(
        self, business_id: BusinessId, rule_version_id: RuleVersionId, period_label: str | None
    ) -> Obligation | None: ...

    def open_for_rule_version(
        self, rule_version_id: RuleVersionId, period_label: str | None = None
    ) -> Sequence[Obligation]: ...

    def add(self, obligation: Obligation) -> None: ...

    def save(self, obligation: Obligation) -> None: ...


class EventSink(Protocol):
    """Where events go inside the transaction: the outbox."""

    def publish(self, event: DomainEvent) -> None: ...


class UnitOfWork(Protocol):
    """One transaction: the repository and the event sink commit or roll back together. The
    factory returns it as a context manager; leaving the block cleanly commits."""

    @property
    def obligations(self) -> ObligationRepository: ...

    @property
    def events(self) -> EventSink: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]: ...
