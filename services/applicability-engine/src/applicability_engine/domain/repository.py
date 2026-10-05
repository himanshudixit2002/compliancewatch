"""What the application layer needs from persistence, as protocols the infrastructure implements."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from applicability_engine.domain.directory import DirectoryEntry, DirectoryKey
from applicability_engine.domain.fanout import FanOutHold, FanOutRun, FanOutRunKey, FanOutStatus
from applicability_engine.domain.impact import ImpactEntry
from applicability_engine.domain.model import Decision, DecisionKey
from applicability_engine.domain.review import ReviewItem, ReviewItemId, ReviewItemKey, ReviewStatus
from domain_kernel.audit import AuditSink
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability


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


class ImpactRepository(Protocol):
    """The tenant's latest decision of a rule version per business, placed by the business
    directory (``domain.impact``)."""

    def latest_by_entity(
        self,
        rule_version_id: RuleVersionId,
        *,
        result: Applicability | None,
        after: BusinessId | None,
        limit: int,
    ) -> Sequence[ImpactEntry]:
        """The latest decision of the version (decided_at, then id) of each business under the
        first ``limit`` entities after ``after``, by entity then business; with ``result``, only
        the businesses whose latest decision has it, and only the entities with one."""
        ...

    def result_counts(self, rule_version_id: RuleVersionId) -> Mapping[Applicability, int]:
        """How many of the tenant's businesses have each result as their latest decision of
        the version; a result none has is left out."""
        ...


class EventSink(Protocol):
    """Where events go inside the transaction: the outbox."""

    def publish(self, event: DomainEvent) -> None: ...


class UnitOfWork(Protocol):
    """One transaction: the repositories, the event sink and the audit sink commit or roll back
    together. The factory returns it as a context manager; leaving the block cleanly commits."""

    @property
    def decisions(self) -> DecisionRepository: ...

    @property
    def directory(self) -> DirectoryRepository: ...

    @property
    def reviews(self) -> ReviewItemRepository: ...

    @property
    def impact(self) -> ImpactRepository: ...

    @property
    def events(self) -> EventSink: ...

    @property
    def audit(self) -> AuditSink:
        """Where the audit entries of the unit's actions go: ``audit.event``, next to the
        outbox."""
        ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]: ...


class BusinessDirectoryReader(Protocol):
    """The business directory across tenants: ids and levels only, read with no tenant
    setting and outside any unit of work (``business_directory_read``)."""

    def entries(
        self,
        *,
        level: AttributeLevel,
        after: DirectoryKey | None,
        limit: int,
        tenant_id: TenantId | None = None,
    ) -> Sequence[DirectoryEntry]:
        """Entries of ``level`` by tenant then node, after ``after``, at most ``limit``; of
        ``tenant_id`` alone when one is named."""
        ...

    def count(self, *, level: AttributeLevel, tenant_id: TenantId | None = None) -> int:
        """How many entries of ``level`` the directory lists; of ``tenant_id`` alone when one
        is named."""
        ...


class FanOutRunRepository(Protocol):
    """One row per rule version's fan-out; rule-level, of no tenant."""

    def add_if_absent(self, run: FanOutRun) -> bool:
        """Store ``run`` unless its rule version has one; True when it was stored."""
        ...

    def get(self, rule_version_id: RuleVersionId, *, for_update: bool = False) -> FanOutRun | None:
        """The run; ``for_update`` holds it until the unit of work ends."""
        ...

    def save(self, run: FanOutRun) -> None:
        """Store the new state of a run already stored."""
        ...

    def list(self, *, after: FanOutRunKey | None, limit: int) -> Sequence[FanOutRun]:
        """Runs newest first (started_at, then rule version, both descending), after
        ``after``, at most ``limit``."""
        ...

    def with_status(self, status: FanOutStatus) -> Sequence[FanOutRun]:
        """Every run in ``status``."""
        ...


class FanOutHoldRepository(Protocol):
    """The global hold: a row while it is set, none once it is released."""

    def get(self, *, for_update: bool = False) -> FanOutHold | None: ...

    def put(self, hold: FanOutHold) -> None:
        """Set the hold, or replace the one that is set."""
        ...

    def clear(self) -> bool:
        """Release the hold; True when one was set."""
        ...


class FanOutUnitOfWork(Protocol):
    """One transaction over the fan-out tables and the audit sink, with no tenant setting:
    the runs and the hold are rule-level, and their audit entries belong to no tenant."""

    @property
    def runs(self) -> FanOutRunRepository: ...

    @property
    def hold(self) -> FanOutHoldRepository: ...

    @property
    def audit(self) -> AuditSink: ...


class FanOutUnitOfWorkFactory(Protocol):
    def __call__(self) -> AbstractContextManager[FanOutUnitOfWork]: ...
