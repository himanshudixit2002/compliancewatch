"""The fan-out of one published rule version over the business directory (ADR-004).

``FanOutWorkflow`` (type ``applicability.fan_out``, task queue ``applicability``, workflow id
``applicability-fan-out-<rule version id>``; a second start of the same id is refused, finished or
not) runs ``application.fanout_flow.drive`` with its steps as activities and timers:

- batches of 1,000 directory entries (``FanOutRequest.batch_size``), one tenant group at a time
  inside each batch (``EvaluateBatchActivity``);
- after 100 batches (``batches_per_run``), or when its history grows past ``HISTORY_LIMIT``
  events while it waits, it continues as new with the cursor, the counters and the flip check;
- at every batch boundary it reads the global hold and its own row, and while held or paused
  waits for a signal or ``poll_seconds`` before it looks again.

Signals ``pause``, ``resume`` and ``cancel`` wake it: the controls change the run's row first,
so the row decides what the workflow does, and a lost signal costs one poll. ``cancel`` is also
final on its own: a cancel signal sent another way still ends the run, cancelled as the system.
The query ``progress`` answers where the run stands as the workflow last saw it.
"""

from contextlib import suppress
from datetime import timedelta
from typing import Final
from uuid import UUID

from temporalio import workflow
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from applicability_engine.application.fanout_activities import (
        BeginFanOutActivity,
        EvaluateBatchActivity,
        ReadControlsActivity,
        UpdateFanOutActivity,
    )
    from applicability_engine.application.fanout_flow import (
        BatchFailedError,
        BatchIn,
        BatchOut,
        Continued,
        Controls,
        FanOutProgress,
        FanOutRequest,
        FanOutResult,
        RunChange,
        RunRef,
        RunState,
        Wakeups,
        drive,
    )
    from applicability_engine.domain.fanout import FAN_OUT_WORKFLOW, FanOutSignal

HISTORY_LIMIT: Final = 2_000
"""History events after which a waiting run continues as new rather than grow further."""
ERROR_CHARS: Final = 1_000


class WorkflowSteps:
    """``FanOutSteps`` as activities and a timer that a signal cuts short."""

    def __init__(self, wakeups: Wakeups) -> None:
        self._wakeups = wakeups

    async def begin(self, request: FanOutRequest) -> RunState:
        begun: RunState = await BeginFanOutActivity.schedule(request)
        return begun

    async def controls(self, rule_version_id: UUID) -> Controls:
        found: Controls = await ReadControlsActivity.schedule(
            RunRef(rule_version_id=rule_version_id)
        )
        return found

    async def evaluate(self, batch: BatchIn) -> BatchOut:
        try:
            decided: BatchOut = await EvaluateBatchActivity.schedule(batch)
        except ActivityError as error:
            raise BatchFailedError(str(error.cause or error)[:ERROR_CHARS]) from error
        return decided

    async def update(self, change: RunChange) -> RunState:
        stored: RunState = await UpdateFanOutActivity.schedule(change)
        return stored

    async def wait(self, seconds: float) -> None:
        if self._wakeups.take():
            return
        with suppress(TimeoutError):
            await workflow.wait_condition(
                lambda: self._wakeups.pending, timeout=timedelta(seconds=seconds)
            )
        self._wakeups.take()

    def history_is_long(self) -> bool:
        info = workflow.info()
        return info.get_current_history_length() > HISTORY_LIMIT or (
            info.is_continue_as_new_suggested()
        )


@workflow.defn(name=FAN_OUT_WORKFLOW)
class FanOutWorkflow:
    def __init__(self) -> None:
        self._wakeups = Wakeups()
        self._progress: FanOutProgress | None = None

    @workflow.run
    async def run(self, request: FanOutRequest) -> FanOutResult:
        self._progress = FanOutProgress(
            rule_version_id=request.rule_version_id,
            batches=request.batches,
            cursor=request.cursor,
            counters=request.counters,
            flip_check=request.flip_check,
        )
        outcome = await drive(
            request, WorkflowSteps(self._wakeups), self._wakeups, on_progress=self._seen
        )
        if isinstance(outcome, Continued):
            workflow.continue_as_new(outcome.request)
        return FanOutResult(
            rule_version_id=request.rule_version_id,
            status=outcome.status,
            batches=outcome.batches,
            counters=outcome.counters,
        )

    def _seen(self, progress: FanOutProgress) -> None:
        self._progress = progress

    @workflow.signal
    def pause(self) -> None:
        self._wakeups.signal(FanOutSignal.PAUSE)

    @workflow.signal
    def resume(self) -> None:
        self._wakeups.signal(FanOutSignal.RESUME)

    @workflow.signal
    def cancel(self) -> None:
        self._wakeups.signal(FanOutSignal.CANCEL)

    @workflow.query
    def progress(self) -> FanOutProgress | None:
        if self._progress is None:
            return None
        return self._progress.model_copy(update={"signals": tuple(self._wakeups.received)})
