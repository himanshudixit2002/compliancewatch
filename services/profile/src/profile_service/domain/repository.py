"""Persistence protocols the application layer uses; the infrastructure implements them."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from domain_kernel.audit import AuditSink
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from profile_service.domain.model import ProfileNode, ReviewTask


class ProfileRepository(Protocol):
    """Scoped to the tenant the unit of work was opened for."""

    def get(self, node_id: BusinessId) -> ProfileNode | None: ...

    def find_by_key(self, level: AttributeLevel, key: str) -> ProfileNode | None: ...

    def lineage(self, node: ProfileNode) -> Sequence[ProfileNode]:
        """Ancestors from the entity down to the parent; empty for an entity."""
        ...

    def children(self, node_id: BusinessId) -> Sequence[ProfileNode]: ...

    def entities(self) -> Sequence[ProfileNode]: ...

    def page_entities(
        self, after: BusinessId | None, limit: int, query: str = ""
    ) -> Sequence[ProfileNode]:
        """At most ``limit`` entities in the order of (name, id), starting after the entity
        ``after``. ``query`` keeps the entities whose name, PAN or GSTIN of a registration
        contains it, ignoring case. ProfileNodeNotFoundError when ``after`` names no entity of
        this tenant."""
        ...

    def registrations_of(
        self, entity_ids: Sequence[BusinessId]
    ) -> Mapping[BusinessId, Sequence[ProfileNode]]:
        """The registrations under each entity in the order they were created; an entity
        without any maps to an empty sequence."""
        ...

    def add(self, node: ProfileNode) -> None: ...

    def save(self, node: ProfileNode) -> None: ...

    def add_review_task(self, task: ReviewTask) -> None: ...

    def open_review_tasks(self, node_id: BusinessId | None = None) -> Sequence[ReviewTask]: ...


class EventSink(Protocol):
    def publish(self, event: DomainEvent) -> None: ...


class EvalCaseRecorder(Protocol):
    """Where an answer worth a golden case goes (a business saying an attribute does not apply)."""

    def record(self, case: Mapping[str, object]) -> None: ...


class UnitOfWork(Protocol):
    @property
    def profiles(self) -> ProfileRepository: ...

    @property
    def events(self) -> EventSink: ...

    @property
    def eval_cases(self) -> EvalCaseRecorder: ...

    @property
    def audit(self) -> AuditSink:
        """Where the unit's audit entries go, in its transaction."""
        ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]: ...
