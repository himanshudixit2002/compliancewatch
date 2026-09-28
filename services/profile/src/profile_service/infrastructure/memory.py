"""In-memory repository, unit of work and eval recorder: the fakes for tests and the app
before Postgres."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager

from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from profile_service.domain.model import ProfileNode, ReviewTask
from profile_service.domain.repository import UnitOfWork


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

    def commit(self) -> None:
        self._store.nodes.clear()
        self._store.nodes.update(self._nodes)
        self._store.tasks.clear()
        self._store.tasks.update(self._tasks)
        self.events.commit()
        self.eval_cases.commit()


class MemoryStore:
    def __init__(self) -> None:
        self.nodes: dict[BusinessId, ProfileNode] = {}
        self.tasks: dict[BusinessId, ReviewTask] = {}
        self.events: list[DomainEvent] = []
        self.eval_cases: list[Mapping[str, object]] = []

    def __call__(self, tenant_id: TenantId) -> AbstractContextManager[UnitOfWork]:
        return self._unit(tenant_id)

    @contextmanager
    def _unit(self, tenant_id: TenantId) -> Iterator[UnitOfWork]:
        uow = MemoryUnitOfWork(self, tenant_id)
        yield uow
        uow.commit()

    def ping(self) -> bool:
        return True
