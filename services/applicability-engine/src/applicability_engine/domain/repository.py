"""What the application layer needs from persistence, as protocols the infrastructure implements."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from applicability_engine.domain.model import Decision, DecisionKey
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId


class DecisionRepository(Protocol):
    """Append-only; reads and writes are scoped to the tenant the unit of work was opened for."""

    def add(self, decision: Decision) -> None: ...

    def get(self, decision_id: DecisionId) -> Decision | None: ...

    def list_for_business(
        self,
        business_id: BusinessId,
        *,
        rule_version_id: RuleVersionId | None,
        after: DecisionKey | None,
        limit: int,
    ) -> Sequence[Decision]:
        """The business's decisions, optionally of one rule version, newest first (decided_at,
        then id, both descending), starting after ``after``, at most ``limit``."""
        ...


class EventSink(Protocol):
    """Where events go inside the transaction: the outbox."""

    def publish(self, event: DomainEvent) -> None: ...


class UnitOfWork(Protocol):
    """One transaction: the repository and the event sink commit or roll back together. The
    factory returns it as a context manager; leaving the block cleanly commits."""

    @property
    def decisions(self) -> DecisionRepository: ...

    @property
    def events(self) -> EventSink: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]: ...
