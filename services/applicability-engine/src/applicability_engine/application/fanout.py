"""The fan-out controls a person uses, and the reads behind them.

- ``ListFanOuts`` and ``ReadFanOut``: the runs newest first, a page at a time, and one run.
- ``PauseFanOut``, ``ResumeFanOut`` and ``CancelFanOut``: a person pauses a run that is running or
  held, resumes one that is paused, or cancels one that has not finished.
- ``ReadHold``, ``SetHold`` and ``ReleaseHold``: the global hold, which stops every fan-out at its
  next batch boundary until it is released.

Each control changes its row and writes its audit entry in one unit of work of no tenant, so the
two commit or roll back together, and only then signals the run's workflow
(``FanOutWorkflows.signal``), so it acts at once rather than at its next poll; no call leaves the
process while the transaction is open, and a signal that is lost costs only that wait. Releasing
the hold signals every run it held. Pausing, cancelling and holding need a reason of at least ten
characters (``domain.fanout.require_reason``); resuming and releasing take one if given.

The audit entries: ``applicability.fanout.pause``, ``.resume``, ``.cancel``, ``.hold`` and
``.release``, of no tenant (a fan-out runs over every tenant), on the subject ``fanout_run`` (the
rule version id) or ``fanout_hold`` (``global``), with the actor the request names (the verified
person, else ``system:applicability-engine``), the reason, the state before and after and the
request's correlation id. The run itself writes the same pause and cancel entries, as the system,
when it pauses on flips or is cancelled because its version was withdrawn
(``application.fanout_runs``, ``application.rule_events``).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from applicability_engine.domain.errors import FanOutNotFoundError, FanOutStateError
from applicability_engine.domain.fanout import (
    MAX_REASON_CHARS,
    FanOutHold,
    FanOutRun,
    FanOutRunKey,
    FanOutSignal,
    FanOutStatus,
    require_reason,
)
from applicability_engine.domain.ports import FanOutWorkflows
from applicability_engine.domain.repository import FanOutUnitOfWorkFactory
from domain_kernel.audit import AuditActor, AuditActorKind, AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import RuleVersionId

MAX_RUNS = 201
"""The most one read returns: the longest page and the row that tells there is another."""
PAUSE_ACTION: Final = "applicability.fanout.pause"
RESUME_ACTION: Final = "applicability.fanout.resume"
CANCEL_ACTION: Final = "applicability.fanout.cancel"
HOLD_ACTION: Final = "applicability.fanout.hold"
RELEASE_ACTION: Final = "applicability.fanout.release"
RUN_SUBJECT: Final = "fanout_run"
HOLD_SUBJECT: Final = "fanout_hold"
HOLD_ID: Final = "global"


def actor_name(actor: AuditActor) -> str:
    """How a run or the hold records who acted: a person's user id, else the actor's label
    (``system:applicability-engine``, ``service:<client>``); never a name."""
    return actor.id if actor.kind is AuditActorKind.USER else actor.label


def optional_reason(reason: str) -> str:
    """A reason a control takes if given: stripped, at most ``MAX_REASON_CHARS``."""
    text = reason.strip()
    if len(text) > MAX_REASON_CHARS:
        raise InvariantViolationError(f"reason has at most {MAX_REASON_CHARS} characters")
    return text


def audited_run(run: FanOutRun) -> dict[str, object]:
    """What an audit entry keeps of a run: its status, why and by whom, and how far it got."""
    return {
        "status": run.status.value,
        "status_reason": run.status_reason,
        "status_by": run.status_by,
        "businesses_total": run.counters.businesses_total,
        "evaluated": run.counters.evaluated,
    }


def audited_hold(hold: FanOutHold | None) -> dict[str, object] | None:
    if hold is None:
        return None
    return {"reason": hold.reason, "set_by": hold.set_by, "set_at": hold.set_at.isoformat()}


def run_entry(
    action: str,
    before: FanOutRun,
    after: FanOutRun,
    *,
    actor: AuditActor,
    reason: str,
    at: datetime,
    correlation_id: str | None,
) -> AuditEntry:
    """The audit entry of a change of a run's status, of no tenant."""
    return AuditEntry(
        action=action,
        tenant_id=None,
        subject_type=RUN_SUBJECT,
        subject_id=str(after.rule_version_id),
        actor=actor,
        reason=reason,
        before=audited_run(before),
        after=audited_run(after),
        occurred_at=at,
        correlation_id=correlation_id,
    )


@dataclass(frozen=True, slots=True)
class FanOutControl:
    """A person's control of one run: ``actor`` is who the audit entry names, ``reason`` why,
    and ``correlation_id`` the request behind it."""

    rule_version_id: RuleVersionId
    actor: AuditActor
    reason: str = ""
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class HoldControl:
    """A person setting or releasing the global hold."""

    actor: AuditActor
    reason: str = ""
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class FanOutQuery:
    limit: int
    after: FanOutRunKey | None = None


class ListFanOuts:
    def __init__(self, fanouts: FanOutUnitOfWorkFactory) -> None:
        self._fanouts = fanouts

    def run(self, query: FanOutQuery) -> Sequence[FanOutRun]:
        with self._fanouts() as uow:
            return tuple(uow.runs.list(after=query.after, limit=min(max(query.limit, 1), MAX_RUNS)))


class ReadFanOut:
    def __init__(self, fanouts: FanOutUnitOfWorkFactory) -> None:
        self._fanouts = fanouts

    def run(self, rule_version_id: RuleVersionId) -> FanOutRun:
        with self._fanouts() as uow:
            run = uow.runs.get(rule_version_id)
        if run is None:
            raise FanOutNotFoundError(str(rule_version_id))
        return run


class ReadHold:
    def __init__(self, fanouts: FanOutUnitOfWorkFactory) -> None:
        self._fanouts = fanouts

    def run(self) -> FanOutHold | None:
        with self._fanouts() as uow:
            return uow.hold.get()


class _RunControl:
    """Move one run to ``to`` for a person, audit it, then signal its workflow."""

    to: FanOutStatus
    action: str
    signal: FanOutSignal
    requires_reason: bool
    allowed_from: frozenset[FanOutStatus] | None = None
    """The statuses a person may move the run from; None: whatever ``TRANSITIONS`` allows."""

    def __init__(
        self,
        fanouts: FanOutUnitOfWorkFactory,
        workflows: FanOutWorkflows,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._fanouts = fanouts
        self._workflows = workflows
        self._clock = clock

    def run(self, control: FanOutControl) -> FanOutRun:
        reason = (
            require_reason(control.reason)
            if self.requires_reason
            else optional_reason(control.reason)
        )
        now = self._clock()
        rule_version_id = control.rule_version_id
        with self._fanouts() as uow:
            before = uow.runs.get(rule_version_id, for_update=True)
            if before is None:
                raise FanOutNotFoundError(str(rule_version_id))
            if self.allowed_from is not None and before.status not in self.allowed_from:
                raise FanOutStateError(str(rule_version_id), before.status.value, self.to.value)
            after = before.move(self.to, at=now, reason=reason, by=actor_name(control.actor))
            uow.runs.save(after)
            uow.audit.write(
                run_entry(
                    self.action,
                    before,
                    after,
                    actor=control.actor,
                    reason=reason,
                    at=now,
                    correlation_id=control.correlation_id,
                )
            )
        self._workflows.signal(rule_version_id, self.signal)
        return after


class PauseFanOut(_RunControl):
    """Pause a running or held run; it stops at its next batch boundary and waits for a person.
    A reason is required."""

    to = FanOutStatus.PAUSED
    action = PAUSE_ACTION
    signal = FanOutSignal.PAUSE
    requires_reason = True


class ResumeFanOut(_RunControl):
    """Resume a paused run; a run the hold stopped resumes when the hold is released, not
    here."""

    to = FanOutStatus.RUNNING
    action = RESUME_ACTION
    signal = FanOutSignal.RESUME
    requires_reason = False
    allowed_from = frozenset({FanOutStatus.PAUSED})


class CancelFanOut(_RunControl):
    """Cancel a run that has not finished; the decisions it made stay. A reason is required."""

    to = FanOutStatus.CANCELLED
    action = CANCEL_ACTION
    signal = FanOutSignal.CANCEL
    requires_reason = True


class SetHold:
    """Set the global hold, or replace the reason of the one that is set; every fan-out stops at
    its next batch boundary. A reason is required."""

    def __init__(
        self, fanouts: FanOutUnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._fanouts = fanouts
        self._clock = clock

    def run(self, control: HoldControl) -> FanOutHold:
        reason = require_reason(control.reason)
        now = self._clock()
        hold = FanOutHold(reason=reason, set_by=actor_name(control.actor), set_at=now)
        with self._fanouts() as uow:
            before = uow.hold.get(for_update=True)
            uow.hold.put(hold)
            uow.audit.write(_hold_entry(HOLD_ACTION, before, hold, control, reason, now))
        return hold


class ReleaseHold:
    """Release the global hold and signal every run it held, which then runs again by itself; a
    paused run stays paused. Releasing a hold that is not set changes nothing and writes no
    entry. Returns the hold that was released, or None."""

    def __init__(
        self,
        fanouts: FanOutUnitOfWorkFactory,
        workflows: FanOutWorkflows,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._fanouts = fanouts
        self._workflows = workflows
        self._clock = clock

    def run(self, control: HoldControl) -> FanOutHold | None:
        reason = optional_reason(control.reason)
        now = self._clock()
        with self._fanouts() as uow:
            before = uow.hold.get(for_update=True)
            if before is None:
                return None
            uow.hold.clear()
            held = [run.rule_version_id for run in uow.runs.with_status(FanOutStatus.HELD)]
            uow.audit.write(_hold_entry(RELEASE_ACTION, before, None, control, reason, now))
        for rule_version_id in held:
            self._workflows.signal(rule_version_id, FanOutSignal.RESUME)
        return before


def _hold_entry(
    action: str,
    before: FanOutHold | None,
    after: FanOutHold | None,
    control: HoldControl,
    reason: str,
    at: datetime,
) -> AuditEntry:
    state: Mapping[str, object] | None = audited_hold(after)
    return AuditEntry(
        action=action,
        tenant_id=None,
        subject_type=HOLD_SUBJECT,
        subject_id=HOLD_ID,
        actor=control.actor,
        reason=reason,
        before=audited_hold(before),
        after=state,
        occurred_at=at,
        correlation_id=control.correlation_id,
    )
