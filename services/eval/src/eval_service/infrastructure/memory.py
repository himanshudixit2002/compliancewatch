"""In-memory repository and unit of work: the fakes for tests and the app before Postgres.

A unit of work works on a copy of the runs and replaces them when the block exits cleanly; units
run one at a time (a store-level lock held from open to commit or rollback).
"""

import threading
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager

from domain_kernel.events import DomainEvent
from eval_service.domain.model import EvalRun, EvalRunId, Profile, Suite
from eval_service.domain.repository import UnitOfWork


class MemoryEvalRunRepository:
    def __init__(self, store: dict[EvalRunId, EvalRun]) -> None:
        self._store = store

    def add(self, run: EvalRun) -> None:
        if run.id in self._store:
            raise ValueError(f"duplicate eval run {run.id}")
        self._store[run.id] = run

    def get(self, run_id: EvalRunId) -> EvalRun | None:
        return self._store.get(run_id)

    def latest(self, suite: Suite, profile: Profile) -> EvalRun | None:
        found = self.recent(suite=suite, profile=profile, limit=1)
        return found[0] if found else None

    def recent(
        self, *, suite: Suite | None, profile: Profile | None, limit: int
    ) -> Sequence[EvalRun]:
        found = [
            run
            for run in self._store.values()
            if (suite is None or run.suite is suite) and (profile is None or run.profile is profile)
        ]
        # The Postgres order: latest start first, then the larger id.
        found.sort(key=lambda run: (run.started_at, run.id.value), reverse=True)
        return found[:limit]


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
    def __init__(self, store: dict[EvalRunId, EvalRun], events: list[DomainEvent]) -> None:
        self._committed = store
        self._working: dict[EvalRunId, EvalRun] = {}
        self.runs = MemoryEvalRunRepository(self._working)
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
    """Holds the runs and the published events; makes units of work."""

    def __init__(self) -> None:
        self.runs: dict[EvalRunId, EvalRun] = {}
        self.events: list[DomainEvent] = []
        self._lock = threading.Lock()

    def ping(self) -> bool:
        return True

    def __call__(self) -> AbstractContextManager[UnitOfWork]:
        return self._unit()

    @contextmanager
    def _unit(self) -> Iterator[UnitOfWork]:
        with self._lock, MemoryUnitOfWork(self.runs, self.events) as uow:
            yield uow
