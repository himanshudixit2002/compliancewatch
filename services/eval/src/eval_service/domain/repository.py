"""What the application layer needs from persistence and from the harness, as protocols the
infrastructure implements."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from domain_kernel.events import DomainEvent
from eval_service.domain.model import EvalRun, EvalRunId, GateMeasurement, Profile, Suite


class EvalRunRepository(Protocol):
    def add(self, run: EvalRun) -> None: ...

    def get(self, run_id: EvalRunId) -> EvalRun | None: ...

    def latest(self, suite: Suite, profile: Profile) -> EvalRun | None:
        """The most recently started run of the suite under the profile."""
        ...

    def recent(
        self, *, suite: Suite | None, profile: Profile | None, limit: int
    ) -> Sequence[EvalRun]:
        """Runs, most recently started first, optionally of one suite or profile."""
        ...


class EventSink(Protocol):
    def publish(self, event: DomainEvent) -> None: ...


class UnitOfWork(Protocol):
    @property
    def runs(self) -> EvalRunRepository: ...

    @property
    def events(self) -> EventSink: ...


class UnitOfWorkFactory(Protocol):
    """``factory()`` opens one transaction; eval runs belong to no tenant."""

    def __call__(self) -> AbstractContextManager[UnitOfWork]: ...


class SuiteRunner(Protocol):
    def run(self, suite: Suite, profile: Profile) -> Sequence[GateMeasurement]:
        """Run the suite and measure its gates; raises ``EvalHarnessError`` when it cannot."""
        ...
