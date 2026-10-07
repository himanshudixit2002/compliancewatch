"""Persistence protocols the application layer uses; the infrastructure implements them."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from domain_kernel.audit import AuditSink
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from profile_service.domain.model import NodeAttribute, ProfileNode, ProfileVersion, ReviewTask

type NodeCursor = tuple[datetime, BusinessId]
"""Where a page of nodes or review tasks ends: (created_at, id) of the last one."""
type AttributeCursor = tuple[datetime, BusinessId, str, str]
"""Where a page of attribute values ends: (updated_at, node_id, key, financial year label or
'') of the last one."""
type VersionCursor = tuple[datetime, BusinessId, int]
"""Where a page of history rows ends: (at, node_id, version) of the last one."""


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

    def count(self, level: AttributeLevel) -> int:
        """How many nodes of ``level`` the tenant holds (its GSTIN registrations, for the plan
        limit)."""
        ...

    def add(self, node: ProfileNode) -> None: ...

    def save(self, node: ProfileNode) -> None: ...

    def add_review_task(self, task: ReviewTask) -> None: ...

    def open_review_tasks(self, node_id: BusinessId | None = None) -> Sequence[ReviewTask]: ...

    # The data export reads every row of the tenant a page at a time, each section in a stable
    # order (oldest first, then the key), starting after the cursor of the previous page.

    def export_nodes(self, after: NodeCursor | None, limit: int) -> Sequence[ProfileNode]:
        """At most ``limit`` nodes of every level in the order of (created_at, id)."""
        ...

    def export_attributes(
        self, after: AttributeCursor | None, limit: int
    ) -> Sequence[NodeAttribute]:
        """At most ``limit`` stored values in the order of (updated_at, node_id, key, year)."""
        ...

    def export_versions(self, after: VersionCursor | None, limit: int) -> Sequence[ProfileVersion]:
        """At most ``limit`` history rows in the order of (at, node_id, version)."""
        ...

    def export_review_tasks(self, after: NodeCursor | None, limit: int) -> Sequence[ReviewTask]:
        """At most ``limit`` review tasks, open or closed, in the order of (created_at, id)."""
        ...


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
