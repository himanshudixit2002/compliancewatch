"""What the application layer needs from persistence, as protocols the infrastructure implements."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.model import Decision, DecisionKey
from applicability_engine.domain.review import ReviewItem, ReviewItemId, ReviewItemKey, ReviewStatus
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId


class DecisionRepository(Protocol):
    """Append-only; reads and writes are scoped to the tenant the unit of work was opened for."""

    def add(self, decision: Decision) -> None: ...

    def add_if_absent(self, decision: Decision) -> bool:
        """Append ``decision`` unless its id, or its (trigger_ref, business, rule version), is
        already stored; True when it was appended."""
        ...

    def get(self, decision_id: DecisionId) -> Decision | None: ...

    def get_many(self, decision_ids: Sequence[DecisionId]) -> Sequence[Decision]:
        """The decisions of ``decision_ids`` the tenant has, in no particular order."""
        ...

    def latest(self, business_id: BusinessId, rule_version_id: RuleVersionId) -> Decision | None:
        """The newest decision of the business and the rule version (decided_at, then id)."""
        ...

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


class DirectoryRepository(Protocol):
    """The tenant's entries of the business directory; written once per node."""

    def add(self, entry: DirectoryEntry) -> bool:
        """Record ``entry`` unless its node is listed; True when it was added."""
        ...


class ReviewItemRepository(Protocol):
    """The tenant's review items."""

    def add(self, item: ReviewItem) -> bool:
        """Store a new open item unless its id is stored; True when it was added."""
        ...

    def get(self, item_id: ReviewItemId, *, for_update: bool = False) -> ReviewItem | None:
        """The item; ``for_update`` holds it until the unit of work ends."""
        ...

    def open_for(
        self, business_id: BusinessId, rule_version_id: RuleVersionId
    ) -> ReviewItem | None:
        """The open item of the business and the rule version, held until the unit of work
        ends; at most one is open."""
        ...

    def save(self, item: ReviewItem) -> None:
        """Store the new state of an item already stored."""
        ...

    def list(
        self, *, status: ReviewStatus | None, after: ReviewItemKey | None, limit: int
    ) -> Sequence[ReviewItem]:
        """Items oldest first (opened_at, then id), optionally of one status, starting after
        ``after``, at most ``limit``."""
        ...


class EventSink(Protocol):
    """Where events go inside the transaction: the outbox."""

    def publish(self, event: DomainEvent) -> None: ...


class UnitOfWork(Protocol):
    """One transaction: the repositories and the event sink commit or roll back together. The
    factory returns it as a context manager; leaving the block cleanly commits."""

    @property
    def decisions(self) -> DecisionRepository: ...

    @property
    def directory(self) -> DirectoryRepository: ...

    @property
    def reviews(self) -> ReviewItemRepository: ...

    @property
    def events(self) -> EventSink: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]: ...
