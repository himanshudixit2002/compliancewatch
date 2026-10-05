"""The fan-out workflow's activities (``py_common.temporal.ActivityBase``), each a use case of
this package behind the wire models of ``application.fanout_flow``.

- ``BeginFanOutActivity`` (``applicability.fanout.begin``): ``BeginFanOut``.
- ``ReadControlsActivity`` (``applicability.fanout.controls``): ``ReadControls``.
- ``EvaluateBatchActivity`` (``applicability.fanout.evaluate_batch``): ``EvaluateBatch``, which
  reads profiles over HTTP and writes decisions, run on a thread while the activity heartbeats.
- ``UpdateFanOutActivity`` (``applicability.fanout.update``): ``UpdateFanOut``.

Every one is idempotent, so Temporal may retry it: beginning inserts the run once, decisions
derive their ids from the rule.published event, and counters and statuses are written whole. The
three that only touch the database retry until it answers. A batch retries for about an hour
with backoff (a profile or rulebook outage), except when the version is gone or no longer
published, which no retry fixes. The sync use cases run on a thread (``asyncio.to_thread``) so the
worker's event loop, which also serves the consumers, never blocks.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, ClassVar, Final

from temporalio.common import RetryPolicy

from applicability_engine.application.fanout_batch import BatchRequest, EvaluateBatch
from applicability_engine.application.fanout_flow import (
    BatchIn,
    BatchOut,
    Controls,
    Counters,
    Cursor,
    FanOutRequest,
    RunChange,
    RunRef,
    RunState,
)
from applicability_engine.application.fanout_runs import (
    BeginFanOut,
    ReadControls,
    RunUpdate,
    UpdateFanOut,
)
from applicability_engine.domain.fanout import FanOutRun
from applicability_engine.domain.ports import ProfileReader, RulebookReader
from applicability_engine.domain.repository import (
    BusinessDirectoryReader,
    FanOutUnitOfWorkFactory,
    UnitOfWorkFactory,
)
from domain_kernel.events import utc_now
from domain_kernel.ids import RuleVersionId
from domain_kernel.ontology import Ontology
from py_common.logging import get_logger
from py_common.temporal import ActivityBase

log = get_logger(__name__)

UNTIL_IT_ANSWERS: Final = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=0,
)
"""The database steps: retried, with backoff, for as long as the database does not answer."""
BATCH_RETRIES: Final = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=15,
    non_retryable_error_types=["RuleVersionNotFoundError", "RuleVersionNotPublishedError"],
)
"""A batch: about an hour of retries, none when the version is gone or no longer published."""
HEARTBEAT_SECONDS: Final = 10.0


def state_of(run: FanOutRun) -> RunState:
    return RunState(status=run.status, counters=Counters.of(run.counters))


class BeginFanOutActivity(ActivityBase[FanOutRequest, RunState]):
    name: ClassVar[str] = "applicability.fanout.begin"
    input_type: ClassVar[type[Any]] = FanOutRequest
    output_type: ClassVar[type[Any]] = RunState
    retry_policy: ClassVar[RetryPolicy] = UNTIL_IT_ANSWERS
    start_to_close: ClassVar[timedelta] = timedelta(minutes=1)

    def __init__(self, begin: BeginFanOut) -> None:
        self._begin = begin

    async def run(self, input: FanOutRequest) -> RunState:
        return state_of(await asyncio.to_thread(self._begin.run, input.start()))


class ReadControlsActivity(ActivityBase[RunRef, Controls]):
    name: ClassVar[str] = "applicability.fanout.controls"
    input_type: ClassVar[type[Any]] = RunRef
    output_type: ClassVar[type[Any]] = Controls
    retry_policy: ClassVar[RetryPolicy] = UNTIL_IT_ANSWERS
    start_to_close: ClassVar[timedelta] = timedelta(minutes=1)

    def __init__(self, read: ReadControls) -> None:
        self._read = read

    async def run(self, input: RunRef) -> Controls:
        found = await asyncio.to_thread(self._read.run, RuleVersionId(input.rule_version_id))
        return Controls(
            status=None if found.run is None else found.run.status,
            hold_reason=None if found.hold is None else found.hold.reason,
        )


class EvaluateBatchActivity(ActivityBase[BatchIn, BatchOut]):
    name: ClassVar[str] = "applicability.fanout.evaluate_batch"
    input_type: ClassVar[type[Any]] = BatchIn
    output_type: ClassVar[type[Any]] = BatchOut
    retry_policy: ClassVar[RetryPolicy] = BATCH_RETRIES
    start_to_close: ClassVar[timedelta] = timedelta(minutes=30)
    heartbeat_timeout: ClassVar[timedelta | None] = timedelta(minutes=2)

    def __init__(self, batch: EvaluateBatch, *, heartbeat_seconds: float = HEARTBEAT_SECONDS):
        self._batch = batch
        self._heartbeat_seconds = heartbeat_seconds

    async def run(self, input: BatchIn) -> BatchOut:
        request = BatchRequest(
            start=input.request.start(),
            after=None if input.after is None else input.after.key(),
            limit=input.limit,
        )
        work = asyncio.ensure_future(asyncio.to_thread(self._batch.run, request))
        while not work.done():
            await asyncio.wait({work}, timeout=self._heartbeat_seconds)
            if not work.done():
                self.heartbeat()
        outcome = work.result()
        log.info(
            "applicability.fanout_batch",
            rule_version_id=str(input.request.rule_version_id),
            read=outcome.read,
            evaluated=outcome.evaluated,
            appended=outcome.appended,
            published=outcome.published,
            skipped=outcome.skipped,
            flips=outcome.flips,
            done=outcome.done,
        )
        return BatchOut(
            read=outcome.read,
            evaluated=outcome.evaluated,
            applies=outcome.applies,
            flips_compared=outcome.flips_compared,
            flips=outcome.flips,
            appended=outcome.appended,
            published=outcome.published,
            skipped=outcome.skipped,
            last=None if outcome.last is None else Cursor.of(outcome.last),
            done=outcome.done,
        )


class UpdateFanOutActivity(ActivityBase[RunChange, RunState]):
    name: ClassVar[str] = "applicability.fanout.update"
    input_type: ClassVar[type[Any]] = RunChange
    output_type: ClassVar[type[Any]] = RunState
    retry_policy: ClassVar[RetryPolicy] = UNTIL_IT_ANSWERS
    start_to_close: ClassVar[timedelta] = timedelta(minutes=1)

    def __init__(self, update: UpdateFanOut) -> None:
        self._update = update

    async def run(self, input: RunChange) -> RunState:
        change = RunUpdate(
            rule_version_id=RuleVersionId(input.rule_version_id),
            counters=None if input.counters is None else input.counters.domain(),
            status=input.status,
            reason=input.reason,
            error=input.error,
            correlation_id=None if input.correlation_id is None else str(input.correlation_id),
        )
        return state_of(await asyncio.to_thread(self._update.run, change))


def fanout_activities(
    *,
    fanouts: FanOutUnitOfWorkFactory,
    directory: BusinessDirectoryReader,
    unit_of_work: UnitOfWorkFactory,
    profiles: ProfileReader,
    rulebook: RulebookReader,
    ontology: Ontology,
    clock: Callable[[], datetime] = utc_now,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> list[ActivityBase[Any, Any]]:
    """Every activity of the fan-out workflow, on these stores and readers."""
    return [
        BeginFanOutActivity(BeginFanOut(fanouts, directory, clock=clock)),
        ReadControlsActivity(ReadControls(fanouts)),
        EvaluateBatchActivity(
            EvaluateBatch(directory, unit_of_work, profiles, rulebook, ontology, clock=clock),
            heartbeat_seconds=heartbeat_seconds,
        ),
        UpdateFanOutActivity(UpdateFanOut(fanouts, clock=clock)),
    ]
