"""A fan-out: one published rule version decided for every business of its level.

When the rulebook publishes a version, the engine decides it for every node of the version's
level that the business directory lists, one batch of ``BATCH_SIZE`` businesses at a time
(``FanOutWorkflow`` on the ``applicability`` task queue). ``FanOutRun`` is the run's row, one per
rule version: its status, its counters, and the reason and author of its last change of status.
``FanOutHold`` is the global hold: while it is set, no fan-out starts its next batch.

Statuses (``TRANSITIONS`` says which follow which):

- ``running``: deciding businesses, batch by batch;
- ``held``: stopped at a batch boundary because the global hold is set; it runs again by itself
  once the hold is released;
- ``paused``: stopped at a batch boundary by a person, or by the run itself when its flips went
  past the threshold (``flip_alarm``); it runs again only when a person resumes it;
- ``completed``: every business of the level was decided;
- ``cancelled``: a person cancelled it, or the version was withdrawn; the decisions it made stay;
- ``disabled``: the version was published while the flag ``applicability.fanout`` was off, so it
  never ran (the profile.updated consumer still decides each business when its profile changes);
- ``failed``: a batch kept failing after its retries; ``last_error`` says why.

A flip is a business whose decision under the new version differs from the latest decision of
the version it supersedes. Once ``FLIP_MINIMUM`` businesses have been compared, a flip rate above
``FLIP_THRESHOLD`` pauses the run, since a superseding version that changes that many results is
more likely a fault than a change of law; a person looks and resumes or cancels it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Final, Self

from applicability_engine.domain.errors import FanOutStateError
from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CorrelationId, EventId, RuleVersionId
from domain_kernel.ontology import AttributeLevel

FAN_OUT_TASK_QUEUE: Final = "applicability"
"""The Temporal task queue of the engine's fan-out workflow and its activities."""
FAN_OUT_WORKFLOW: Final = "applicability.fan_out"
"""The workflow type of a fan-out."""
BATCH_SIZE: Final = 1_000
"""Directory entries a batch decides."""
BATCHES_PER_RUN: Final = 100
"""Batches a workflow run decides before it continues as new, carrying its cursor."""
FLIP_THRESHOLD: Final = 0.02
"""The flip rate past which a run pauses itself."""
FLIP_MINIMUM: Final = 200
"""Businesses compared with the superseded version before the flip rate counts."""
MIN_REASON_CHARS: Final = 10
"""The shortest reason a pause, a cancellation or a hold takes."""
MAX_REASON_CHARS: Final = 2_000
"""The longest reason an audit entry keeps."""
MAX_RULE_KEY_CHARS: Final = 80
MAX_ERROR_CHARS: Final = 2_000
MAX_ACTOR_CHARS: Final = 200
TRIGGER_REF_PREFIX: Final = "rule.published:"


def fan_out_workflow_id(rule_version_id: RuleVersionId) -> str:
    """The workflow id of the version's fan-out: one per version, ever."""
    return f"applicability-fan-out-{rule_version_id}"


def published_trigger_ref(event_id: EventId) -> str:
    """The ``trigger_ref`` of the decisions a rule.published event's fan-out makes."""
    return f"{TRIGGER_REF_PREFIX}{event_id}"


def require_reason(reason: object, name: str = "reason") -> str:
    """A reason a person gives for a control: at least ``MIN_REASON_CHARS`` characters once
    stripped, at most ``MAX_REASON_CHARS``."""
    text = require_instance(reason, str, name).strip()
    if len(text) < MIN_REASON_CHARS:
        raise InvariantViolationError(f"{name} needs at least {MIN_REASON_CHARS} characters")
    if len(text) > MAX_REASON_CHARS:
        raise InvariantViolationError(f"{name} has at most {MAX_REASON_CHARS} characters")
    return text


class FanOutStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    HELD = "held"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DISABLED = "disabled"
    FAILED = "failed"

    @property
    def is_active(self) -> bool:
        """Running, held or paused: the run has more to do."""
        return self in ACTIVE


ACTIVE: Final = frozenset({FanOutStatus.RUNNING, FanOutStatus.HELD, FanOutStatus.PAUSED})
TRANSITIONS: Final[Mapping[FanOutStatus, frozenset[FanOutStatus]]] = {
    FanOutStatus.RUNNING: frozenset(
        {
            FanOutStatus.PAUSED,
            FanOutStatus.HELD,
            FanOutStatus.COMPLETED,
            FanOutStatus.CANCELLED,
            FanOutStatus.FAILED,
        }
    ),
    FanOutStatus.HELD: frozenset(
        {
            FanOutStatus.RUNNING,
            FanOutStatus.PAUSED,
            FanOutStatus.COMPLETED,
            FanOutStatus.CANCELLED,
            FanOutStatus.FAILED,
        }
    ),
    FanOutStatus.PAUSED: frozenset(
        {
            FanOutStatus.RUNNING,
            FanOutStatus.COMPLETED,
            FanOutStatus.CANCELLED,
            FanOutStatus.FAILED,
        }
    ),
    FanOutStatus.COMPLETED: frozenset(),
    FanOutStatus.CANCELLED: frozenset(),
    FanOutStatus.DISABLED: frozenset(),
    FanOutStatus.FAILED: frozenset(),
}
"""Which status may follow which. ``completed`` follows ``held`` and ``paused`` too: the last
batch was decided before the hold or the pause took effect."""


class FanOutSignal(StrEnum):
    """What the controls tell a running workflow once the run's row has changed: look again now,
    rather than at the next poll. ``cancel`` also ends the workflow by itself."""

    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class FanOutCounters:
    """``businesses_total`` is the directory entries of the level when the run began;
    ``evaluated`` the businesses decided so far, ``applies`` those the version applies to;
    ``flips_compared`` the businesses the superseded version had a decision for and ``flips``
    those whose result changed."""

    businesses_total: int = 0
    evaluated: int = 0
    applies: int = 0
    flips_compared: int = 0
    flips: int = 0

    def __post_init__(self) -> None:
        for name in ("businesses_total", "evaluated", "applies", "flips_compared", "flips"):
            require_int(getattr(self, name), name, minimum=0)
        if self.applies > self.evaluated:
            raise InvariantViolationError("applies counts some of the evaluated businesses")
        if self.flips > self.flips_compared:
            raise InvariantViolationError("flips counts some of the compared businesses")
        if self.flips_compared > self.evaluated:
            raise InvariantViolationError("flips_compared counts some of the evaluated businesses")

    @property
    def flip_rate(self) -> float | None:
        """Flips per business compared; None before any comparison."""
        return None if not self.flips_compared else self.flips / self.flips_compared

    def plus(self, *, evaluated: int, applies: int, flips_compared: int, flips: int) -> Self:
        """These counters with one more batch added."""
        return replace(
            self,
            evaluated=self.evaluated + evaluated,
            applies=self.applies + applies,
            flips_compared=self.flips_compared + flips_compared,
            flips=self.flips + flips,
        )


def flip_alarm(counters: FanOutCounters) -> str | None:
    """Why the run must pause itself, or None: more than ``FLIP_THRESHOLD`` of the businesses
    compared flipped, once at least ``FLIP_MINIMUM`` were compared."""
    rate = counters.flip_rate
    if rate is None or counters.flips_compared < FLIP_MINIMUM or rate <= FLIP_THRESHOLD:
        return None
    return (
        f"{counters.flips} of {counters.flips_compared} businesses compared with the superseded "
        f"version flipped ({rate:.1%}), more than {FLIP_THRESHOLD:.0%}; check the version before "
        "resuming"
    )


@dataclass(frozen=True, slots=True)
class FanOutStart:
    """What a fan-out of a published version needs to begin: the version, its rule and level,
    the rule.published event behind it (its id is the decisions' ``trigger_ref``) and the
    versions it supersedes, against whose decisions it counts flips."""

    rule_version_id: RuleVersionId
    rule_key: str
    level: AttributeLevel
    trigger_event_id: EventId
    supersedes: tuple[RuleVersionId, ...] = ()
    correlation_id: CorrelationId | None = None

    def __post_init__(self) -> None:
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_text(self.rule_key, "rule_key")
        if len(self.rule_key) > MAX_RULE_KEY_CHARS:
            raise InvariantViolationError(f"rule_key has at most {MAX_RULE_KEY_CHARS} characters")
        require_instance(self.level, AttributeLevel, "level")
        require_instance(self.trigger_event_id, EventId, "trigger_event_id")
        for superseded in require_instance(self.supersedes, tuple, "supersedes"):
            require_instance(superseded, RuleVersionId, "supersedes[]")
        if self.correlation_id is not None:
            require_instance(self.correlation_id, CorrelationId, "correlation_id")

    @property
    def trigger_ref(self) -> str:
        return published_trigger_ref(self.trigger_event_id)


@dataclass(frozen=True, slots=True)
class FanOutRun:
    """One rule version's fan-out. ``status_reason`` and ``status_by`` say why and by whom the
    status last changed (a person's user id, ``system:<service>`` or ``service:<client>``; never a
    name), and ``last_error`` why a run failed."""

    rule_version_id: RuleVersionId
    rule_key: str
    level: AttributeLevel
    status: FanOutStatus
    trigger_event_id: EventId
    started_at: datetime
    updated_at: datetime
    supersedes: tuple[RuleVersionId, ...] = ()
    counters: FanOutCounters = field(default_factory=FanOutCounters)
    finished_at: datetime | None = None
    status_reason: str = ""
    status_by: str = ""
    last_error: str = ""

    def __post_init__(self) -> None:
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_text(self.rule_key, "rule_key")
        if len(self.rule_key) > MAX_RULE_KEY_CHARS:
            raise InvariantViolationError(f"rule_key has at most {MAX_RULE_KEY_CHARS} characters")
        require_instance(self.level, AttributeLevel, "level")
        require_instance(self.status, FanOutStatus, "status")
        require_instance(self.trigger_event_id, EventId, "trigger_event_id")
        require_aware(self.started_at, "started_at")
        require_aware(self.updated_at, "updated_at")
        for superseded in require_instance(self.supersedes, tuple, "supersedes"):
            require_instance(superseded, RuleVersionId, "supersedes[]")
        require_instance(self.counters, FanOutCounters, "counters")
        if self.status.is_active:
            if self.finished_at is not None:
                raise InvariantViolationError(f"a {self.status.value} fan-out has not finished")
        else:
            require_aware(self.finished_at, "finished_at")
        for name, limit in (
            ("status_reason", MAX_REASON_CHARS),
            ("status_by", MAX_ACTOR_CHARS),
            ("last_error", MAX_ERROR_CHARS),
        ):
            if len(require_instance(getattr(self, name), str, name)) > limit:
                raise InvariantViolationError(f"{name} has at most {limit} characters")

    @classmethod
    def begun(
        cls,
        start: FanOutStart,
        *,
        at: datetime,
        businesses_total: int = 0,
        disabled: bool = False,
    ) -> Self:
        """The run of ``start``: running, or disabled (finished at once) when the flag is off."""
        return cls(
            rule_version_id=start.rule_version_id,
            rule_key=start.rule_key,
            level=start.level,
            status=FanOutStatus.DISABLED if disabled else FanOutStatus.RUNNING,
            trigger_event_id=start.trigger_event_id,
            started_at=at,
            updated_at=at,
            supersedes=start.supersedes,
            counters=FanOutCounters(businesses_total=0 if disabled else businesses_total),
            finished_at=at if disabled else None,
            status_reason="the flag applicability.fanout was off" if disabled else "",
        )

    @property
    def is_active(self) -> bool:
        return self.status.is_active

    def can_move(self, to: FanOutStatus) -> bool:
        return to in TRANSITIONS[self.status]

    def move(
        self,
        to: FanOutStatus,
        *,
        at: datetime,
        reason: str = "",
        by: str = "",
        error: str = "",
    ) -> Self:
        """The run in status ``to``; raises when ``TRANSITIONS`` forbids the move."""
        if not self.can_move(to):
            raise FanOutStateError(str(self.rule_version_id), self.status.value, to.value)
        return replace(
            self,
            status=to,
            updated_at=at,
            finished_at=None if to.is_active else at,
            status_reason=reason[:MAX_REASON_CHARS],
            status_by=by[:MAX_ACTOR_CHARS],
            last_error=error[:MAX_ERROR_CHARS] if to is FanOutStatus.FAILED else self.last_error,
        )

    def counted(self, counters: FanOutCounters, *, at: datetime) -> Self:
        """The run with the counters a batch left; its status unchanged."""
        return replace(self, counters=counters, updated_at=at)


@dataclass(frozen=True, slots=True)
class FanOutRunKey:
    """Where a page of runs ends: newest first, then by rule version."""

    started_at: datetime
    rule_version_id: RuleVersionId

    def __post_init__(self) -> None:
        require_aware(self.started_at, "started_at")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")

    @classmethod
    def of(cls, run: FanOutRun) -> "FanOutRunKey":
        return cls(run.started_at, run.rule_version_id)


@dataclass(frozen=True, slots=True)
class FanOutHold:
    """The global hold: while it is set no fan-out starts its next batch. ``set_by`` is who set
    it (a user id, ``system:<service>`` or ``service:<client>``)."""

    reason: str
    set_by: str
    set_at: datetime

    def __post_init__(self) -> None:
        require_reason(self.reason)
        if self.reason != self.reason.strip():
            raise InvariantViolationError("reason must not have leading or trailing whitespace")
        require_text(self.set_by, "set_by")
        if len(self.set_by) > MAX_ACTOR_CHARS:
            raise InvariantViolationError(f"set_by has at most {MAX_ACTOR_CHARS} characters")
        require_aware(self.set_at, "set_at")
