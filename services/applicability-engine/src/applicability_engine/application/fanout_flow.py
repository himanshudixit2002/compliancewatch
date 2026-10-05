"""A fan-out's control loop: ``drive``, which the Temporal workflow runs
(``applicability_engine.workflows.fan_out``) and the in-process runner of tests and demos too
(``applicability_engine.testing.LocalFanOuts``), over ``FanOutSteps``.

The loop begins the run (its row, with the businesses of its level counted), then decides the
directory a batch at a time. At every batch boundary it reads its controls, the run's row and the
global hold, and obeys them:

- a cancelled run, or a cancel signal, ends the loop; a run the signal alone cancels is moved to
  cancelled, audited as the system;
- a paused run waits (``FanOutSteps.wait``: until a signal or ``poll_seconds``) and looks again;
- while the hold is set the run is moved to held and waits likewise; once the hold is gone it is
  moved back to running;
- otherwise it decides the next batch and records the counters.

The run's row decides: the controls change it first and only then signal the workflow, which is
how a signal wakes the loop early, and a lost signal costs at most ``poll_seconds``. After the
last batch the run completes. A batch that fails after its retries fails the run, with the error.
When more than ``FLIP_THRESHOLD`` of at least ``FLIP_MINIMUM`` businesses compared with the
superseded version flipped, the run pauses itself, audited as the system with the reason; once a
person resumes it the check is off for the rest of the run, since that person has seen the flips.

After ``batches_per_run`` batches, or when the workflow's history grows long while it waits, the
loop returns ``Continued`` with everything it carries (the cursor, the counters, the flip check),
and the workflow continues as new with it. The loop reads no clock and makes no call of its own:
every side effect is a step, so the workflow stays deterministic.

The models here are what crosses the Temporal wire (the pydantic data converter); the workflow's
input is ``FanOutRequest``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from applicability_engine.domain.directory import DirectoryKey
from applicability_engine.domain.fanout import (
    BATCH_SIZE,
    BATCHES_PER_RUN,
    MAX_RULE_KEY_CHARS,
    FanOutCounters,
    FanOutSignal,
    FanOutStart,
    FanOutStatus,
    flip_alarm,
)
from domain_kernel.ids import BusinessId, CorrelationId, EventId, RuleVersionId, TenantId
from domain_kernel.ontology import AttributeLevel

POLL_SECONDS: Final = 30.0
"""How long a held or paused run waits before it reads its controls again, unless signalled."""
RELEASED: Final = "the hold was released"
COMPLETED: Final = "every business of the level was decided"
CANCEL_SIGNALLED: Final = "cancelled by a cancel signal to the workflow"


class Wire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Cursor(Wire):
    """Where the next batch starts: after this directory entry."""

    tenant_id: UUID
    business_id: UUID

    @classmethod
    def of(cls, key: DirectoryKey) -> Self:
        return cls(tenant_id=key.tenant_id.value, business_id=key.business_id.value)

    def key(self) -> DirectoryKey:
        return DirectoryKey(TenantId(self.tenant_id), BusinessId(self.business_id))


class Counters(Wire):
    businesses_total: int = Field(default=0, ge=0)
    evaluated: int = Field(default=0, ge=0)
    applies: int = Field(default=0, ge=0)
    flips_compared: int = Field(default=0, ge=0)
    flips: int = Field(default=0, ge=0)

    @classmethod
    def of(cls, counters: FanOutCounters) -> Self:
        return cls(
            businesses_total=counters.businesses_total,
            evaluated=counters.evaluated,
            applies=counters.applies,
            flips_compared=counters.flips_compared,
            flips=counters.flips,
        )

    def domain(self) -> FanOutCounters:
        return FanOutCounters(
            businesses_total=self.businesses_total,
            evaluated=self.evaluated,
            applies=self.applies,
            flips_compared=self.flips_compared,
            flips=self.flips,
        )


class FanOutRequest(Wire):
    """The workflow's input: the version to fan out and the event behind it, the batching, and
    what a run continued as new carries over (the cursor, the counters, the batches done and
    the flip check)."""

    rule_version_id: UUID
    rule_key: str = Field(min_length=1, max_length=MAX_RULE_KEY_CHARS)
    level: AttributeLevel
    trigger_event_id: UUID
    supersedes: tuple[UUID, ...] = ()
    correlation_id: UUID | None = None
    batch_size: int = Field(default=BATCH_SIZE, ge=1, le=BATCH_SIZE)
    batches_per_run: int = Field(default=BATCHES_PER_RUN, ge=1)
    poll_seconds: float = Field(default=POLL_SECONDS, gt=0, le=3_600)
    began: bool = False
    cursor: Cursor | None = None
    counters: Counters = Counters()
    batches: int = Field(default=0, ge=0)
    flip_check: bool = True
    paused_on_flips: bool = False

    def start(self) -> FanOutStart:
        return FanOutStart(
            rule_version_id=RuleVersionId(self.rule_version_id),
            rule_key=self.rule_key,
            level=self.level,
            trigger_event_id=EventId(self.trigger_event_id),
            supersedes=tuple(RuleVersionId(item) for item in self.supersedes),
            correlation_id=None
            if self.correlation_id is None
            else CorrelationId(self.correlation_id),
        )

    @classmethod
    def of(cls, start: FanOutStart, **options: object) -> Self:
        values: dict[str, object] = {
            "rule_version_id": start.rule_version_id.value,
            "rule_key": start.rule_key,
            "level": start.level,
            "trigger_event_id": start.trigger_event_id.value,
            "supersedes": tuple(item.value for item in start.supersedes),
            "correlation_id": None if start.correlation_id is None else start.correlation_id.value,
        }
        values.update(options)
        return cls.model_validate(values)


class RunRef(Wire):
    rule_version_id: UUID


class RunState(Wire):
    """The run as stored after a step."""

    status: FanOutStatus
    counters: Counters


class Controls(Wire):
    """The run's status as stored (None: it has no row) and the hold's reason (None: released)."""

    status: FanOutStatus | None
    hold_reason: str | None = None


class RunChange(Wire):
    rule_version_id: UUID
    counters: Counters | None = None
    status: FanOutStatus | None = None
    reason: str = ""
    error: str = ""
    correlation_id: UUID | None = None


class BatchIn(Wire):
    request: FanOutRequest
    after: Cursor | None = None
    limit: int = Field(default=BATCH_SIZE, ge=1, le=BATCH_SIZE)


class BatchOut(Wire):
    read: int = Field(ge=0)
    evaluated: int = Field(ge=0)
    applies: int = Field(ge=0)
    flips_compared: int = Field(ge=0)
    flips: int = Field(ge=0)
    appended: int = Field(ge=0)
    published: int = Field(ge=0)
    skipped: int = Field(ge=0)
    last: Cursor | None = None
    done: bool


class FanOutProgress(Wire):
    """What the workflow's ``progress`` query answers."""

    rule_version_id: UUID
    status: FanOutStatus | None = None
    batches: int = 0
    cursor: Cursor | None = None
    counters: Counters = Counters()
    flip_check: bool = True
    signals: tuple[str, ...] = ()


class FanOutResult(Wire):
    """What the workflow returns when the run has finished."""

    rule_version_id: UUID
    status: FanOutStatus | None
    batches: int
    counters: Counters


class BatchFailedError(Exception):
    """A batch failed after its retries; the message says why."""


class FanOutSteps(Protocol):
    """The side effects of the loop: the workflow's activities and timers, or direct calls."""

    async def begin(self, request: FanOutRequest) -> RunState: ...

    async def controls(self, rule_version_id: UUID) -> Controls: ...

    async def evaluate(self, batch: BatchIn) -> BatchOut:
        """Raises ``BatchFailedError`` when the batch failed after its retries."""
        ...

    async def update(self, change: RunChange) -> RunState: ...

    async def wait(self, seconds: float) -> None:
        """Wait ``seconds``, or less when a signal arrives."""
        ...

    def history_is_long(self) -> bool:
        """Whether the workflow should continue as new before its history grows further."""
        ...


class Wakeups:
    """The signals a run received: any of them wakes a wait, and ``cancel`` is final."""

    def __init__(self) -> None:
        self.pending = False
        self.cancelled = False
        self.received: list[str] = []

    def signal(self, signal: FanOutSignal) -> None:
        self.received.append(signal.value)
        self.pending = True
        if signal is FanOutSignal.CANCEL:
            self.cancelled = True

    def take(self) -> bool:
        """Whether a signal arrived since the last call."""
        woken, self.pending = self.pending, False
        return woken


@dataclass(frozen=True, slots=True)
class Finished:
    status: FanOutStatus | None
    counters: Counters
    batches: int


@dataclass(frozen=True, slots=True)
class Continued:
    request: FanOutRequest


type Outcome = Finished | Continued


async def drive(
    request: FanOutRequest,
    steps: FanOutSteps,
    wakeups: Wakeups,
    *,
    on_progress: Callable[[FanOutProgress], None] = lambda progress: None,
) -> Outcome:
    """Run the loop until the run finishes, or until it should continue as new."""
    rule_version_id = request.rule_version_id
    counters = request.counters
    if not request.began:
        begun = await steps.begin(request)
        counters = counters.model_copy(update={"businesses_total": begun.counters.businesses_total})
    cursor = request.cursor
    flip_check, paused_on_flips = request.flip_check, request.paused_on_flips
    batches = request.batches
    status: FanOutStatus | None = None

    def report() -> None:
        on_progress(
            FanOutProgress(
                rule_version_id=rule_version_id,
                status=status,
                batches=batches,
                cursor=cursor,
                counters=counters,
                flip_check=flip_check,
                signals=tuple(wakeups.received),
            )
        )

    def carried() -> Continued:
        return Continued(
            request.model_copy(
                update={
                    "began": True,
                    "cursor": cursor,
                    "counters": counters,
                    "batches": batches,
                    "flip_check": flip_check,
                    "paused_on_flips": paused_on_flips,
                }
            )
        )

    def change(**values: object) -> RunChange:
        return RunChange.model_validate(
            {"rule_version_id": rule_version_id, "correlation_id": request.correlation_id} | values
        )

    async def finish(to: FanOutStatus, *, reason: str = "", error: str = "") -> Finished:
        final = change(counters=counters, status=to, reason=reason, error=error)
        return Finished((await steps.update(final)).status, counters, batches)

    batches_here = 0
    while True:
        controls = await steps.controls(rule_version_id)
        status = controls.status
        report()
        if status is None or not status.is_active:
            return Finished(status, counters, batches)
        if wakeups.cancelled:
            return await finish(FanOutStatus.CANCELLED, reason=CANCEL_SIGNALLED)
        if status is FanOutStatus.PAUSED or controls.hold_reason is not None:
            if status is not FanOutStatus.PAUSED and status is not FanOutStatus.HELD:
                held = change(status=FanOutStatus.HELD, reason=controls.hold_reason or "")
                status = (await steps.update(held)).status
                report()
            if steps.history_is_long():
                return carried()
            await steps.wait(request.poll_seconds)
            continue
        if status is FanOutStatus.HELD:
            released = change(status=FanOutStatus.RUNNING, reason=RELEASED)
            status = (await steps.update(released)).status
        if paused_on_flips:
            flip_check, paused_on_flips = False, False
        try:
            batch = await steps.evaluate(
                BatchIn(request=request, after=cursor, limit=request.batch_size)
            )
        except BatchFailedError as error:
            return await finish(FanOutStatus.FAILED, reason="a batch failed", error=str(error))
        counters = Counters.of(
            counters.domain().plus(
                evaluated=batch.evaluated,
                applies=batch.applies,
                flips_compared=batch.flips_compared,
                flips=batch.flips,
            )
        )
        cursor = batch.last or cursor
        batches += 1
        batches_here += 1
        report()
        if batch.done:
            return await finish(FanOutStatus.COMPLETED, reason=COMPLETED)
        alarm = flip_alarm(counters.domain()) if flip_check else None
        if alarm is not None:
            paused = change(counters=counters, status=FanOutStatus.PAUSED, reason=alarm)
            status = (await steps.update(paused)).status
            paused_on_flips = True
            continue
        status = (await steps.update(change(counters=counters))).status
        long_enough = batches_here >= request.batches_per_run or steps.history_is_long()
        if long_enough and not wakeups.cancelled:
            return carried()
