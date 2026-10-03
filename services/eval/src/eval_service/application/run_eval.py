"""Run one suite of the eval harness and store the run with its gates and drift.

The harness runs outside any transaction (it takes seconds in ``ci`` and longer against a real
model). The run is then stored, with each gate's value in the previous run of the same suite and
profile, and ``eval.run.completed`` is published through the outbox in the same transaction. A
harness failure raises ``EvalHarnessError`` and stores nothing; failing gates are a result, and
are stored like passing ones.
"""

from collections.abc import Callable
from datetime import datetime

from domain_kernel.events import utc_now
from eval_service.domain.events import EvalRunCompleted
from eval_service.domain.model import EvalRun, Profile, Suite
from eval_service.domain.repository import SuiteRunner, UnitOfWorkFactory


class RunEvalSuite:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        runner: SuiteRunner,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._runner = runner
        self._clock = clock

    def run(self, suite: Suite, profile: Profile) -> EvalRun:
        started_at = self._clock()
        measurements = self._runner.run(suite, profile)
        completed_at = self._clock()
        with self._unit_of_work() as uow:
            run = EvalRun.record(
                suite=suite,
                profile=profile,
                started_at=started_at,
                completed_at=completed_at,
                measurements=measurements,
                previous=uow.runs.latest(suite, profile),
            )
            uow.runs.add(run)
            uow.events.publish(EvalRunCompleted.of(run))
        return run
