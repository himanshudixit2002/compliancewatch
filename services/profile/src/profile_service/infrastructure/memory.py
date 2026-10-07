"""In-memory repository, unit of work and eval recorder: the fakes for tests and the app
before Postgres. A unit's audit entries (``MemoryAuditSink``) join the store's ``audit`` log
when it commits, and are dropped with the rest of the unit when it fails.

A unit of work works on a copy of the store and replaces it when the block exits cleanly. Units
run one at a time (a store-level lock held from open to commit or rollback), so two overlapping
requests cannot both start from the same copy and lose each other's writes.
"""

import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from uuid import UUID

from domain_kernel.audit import AuditEntry
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from profile_service.domain.errors import ProfileNodeNotFoundError
from profile_service.domain.model import ProfileNode, ReviewTask
from profile_service.domain.repository import UnitOfWork
from py_common.audit import MemoryAuditSink


class MemoryProfileRepository:
    def __init__(
        self,
        nodes: dict[BusinessId, ProfileNode],
        tasks: dict[BusinessId, ReviewTask],
        tenant_id: TenantId,
    ) -> None:
        self._nodes = nodes
        self._tasks = tasks
        self._tenant = tenant_id

    def _mine(self, node: ProfileNode | None) -> ProfileNode | None:
        return node if node is not None and node.tenant_id == self._tenant else None

    def get(self, node_id: BusinessId) -> ProfileNode | None:
        return self._mine(self._nodes.get(node_id))

    def find_by_key(self, level: AttributeLevel, key: str) -> ProfileNode | None:
        for node in self._nodes.values():
            if node.tenant_id == self._tenant and node.level is level and node.key == key:
                return node
        return None

    def lineage(self, node: ProfileNode) -> Sequence[ProfileNode]:
        chain: list[ProfileNode] = []
        parent_id = node.parent_id
        while parent_id is not None:
            parent = self.get(parent_id)
            if parent is None:
                break
            chain.insert(0, parent)
            parent_id = parent.parent_id
        return chain

    def children(self, node_id: BusinessId) -> Sequence[ProfileNode]:
        return [
            node
            for node in self._nodes.values()
            if node.tenant_id == self._tenant and node.parent_id == node_id
        ]

    def entities(self) -> Sequence[ProfileNode]:
        return [
            node
            for node in self._nodes.values()
            if node.tenant_id == self._tenant and node.level is AttributeLevel.ENTITY
        ]

    def page_entities(
        self, after: BusinessId | None, limit: int, query: str = ""
    ) -> Sequence[ProfileNode]:
        entities = sorted(self.entities(), key=_position)
        if after is not None:
            start = self.get(after)
            if start is None or start.level is not AttributeLevel.ENTITY:
                raise ProfileNodeNotFoundError(str(after))
            entities = [node for node in entities if _position(node) > _position(start)]
        if query:
            entities = [node for node in entities if self._matches(node, query.casefold())]
        return entities[:limit]

    def registrations_of(
        self, entity_ids: Sequence[BusinessId]
    ) -> Mapping[BusinessId, Sequence[ProfileNode]]:
        return {
            entity_id: sorted(
                (
                    node
                    for node in self.children(entity_id)
                    if node.level is AttributeLevel.REGISTRATION
                ),
                key=lambda node: (node.created_at, node.id.value),
            )
            for entity_id in entity_ids
        }

    def _matches(self, entity: ProfileNode, query: str) -> bool:
        keys = [entity.name, entity.key, *(child.key for child in self.children(entity.id))]
        return any(query in key.casefold() for key in keys)

    def add(self, node: ProfileNode) -> None:
        if node.id in self._nodes:
            raise ValueError(f"duplicate node {node.id}")
        self._nodes[node.id] = node

    def save(self, node: ProfileNode) -> None:
        self._nodes[node.id] = node

    def add_review_task(self, task: ReviewTask) -> None:
        self._tasks[task.id] = task

    def open_review_tasks(self, node_id: BusinessId | None = None) -> Sequence[ReviewTask]:
        return [
            task
            for task in self._tasks.values()
            if task.tenant_id == self._tenant
            and task.open
            and (node_id is None or task.node_id == node_id)
        ]


def _position(node: ProfileNode) -> tuple[str, UUID]:
    """Where a node sorts in a list of businesses: by name, then id, as Postgres pages them."""
    return (node.name, node.id.value)


class MemorySink:
    def __init__(self, target: list[DomainEvent]) -> None:
        self._target = target
        self.pending: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.pending.append(event)

    def commit(self) -> None:
        self._target.extend(self.pending)
        self.pending.clear()


class MemoryEvalRecorder:
    def __init__(self, target: list[Mapping[str, object]]) -> None:
        self._target = target
        self.pending: list[Mapping[str, object]] = []

    def record(self, case: Mapping[str, object]) -> None:
        self.pending.append(dict(case))

    def commit(self) -> None:
        self._target.extend(self.pending)
        self.pending.clear()


class MemoryUnitOfWork:
    def __init__(self, store: "MemoryStore", tenant_id: TenantId) -> None:
        self._store = store
        self._nodes: dict[BusinessId, ProfileNode] = dict(store.nodes)
        self._tasks: dict[BusinessId, ReviewTask] = dict(store.tasks)
        self.profiles = MemoryProfileRepository(self._nodes, self._tasks, tenant_id)
        self.events = MemorySink(store.events)
        self.eval_cases = MemoryEvalRecorder(store.eval_cases)
        self.audit = MemoryAuditSink(store.audit, tenant_id=tenant_id)

    def commit(self) -> None:
        self._store.nodes.clear()
        self._store.nodes.update(self._nodes)
        self._store.tasks.clear()
        self._store.tasks.update(self._tasks)
        self.events.commit()
        self.eval_cases.commit()
        self.audit.commit()


class MemoryStore:
    def __init__(self) -> None:
        self.nodes: dict[BusinessId, ProfileNode] = {}
        self.tasks: dict[BusinessId, ReviewTask] = {}
        self.events: list[DomainEvent] = []
        self.eval_cases: list[Mapping[str, object]] = []
        self.audit: list[AuditEntry] = []
        self._lock = threading.Lock()

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        with self._lock:
            uow = MemoryUnitOfWork(self, tenant_id)
            yield uow
            uow.commit()

    def ping(self) -> bool:
        return True
