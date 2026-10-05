"""What a fan-out's workflow does to its own row: begin it, read its controls, record its
progress and the statuses it reaches by itself.

- ``BeginFanOut``: the run's row, made unless the rule events consumer made it first (both insert
  it if absent), with ``businesses_total`` counted from the directory while the run has decided
  nothing yet. The count is a read of its own, before the unit of work opens.
- ``ReadControls``: the run as stored and the global hold, which the workflow reads at every
  batch boundary and every poll while it waits.
- ``UpdateFanOut``: the counters after a batch, and a status the run reaches by itself (held when
  the hold is set, running once it is released, paused on flips, completed, failed, cancelled by
  a signal). A status the run cannot move to is left as it is, since a person or the consumer
  moved it meanwhile (a cancelled run stays cancelled when its last batch completes), and the run
  as stored is returned. A pause on flips and a cancellation are audited as the system, with the
  reason, like the same controls by a person; the other moves are not controls and write none.

Each call is one short unit of work, so the workflow's activities can retry it: beginning twice
inserts once, counters are written whole rather than added, and a status already reached is not
moved, or audited, again.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from applicability_engine import SERVICE_NAME
from applicability_engine.application.fanout import CANCEL_ACTION, PAUSE_ACTION, run_entry
from applicability_engine.domain.errors import FanOutNotFoundError
from applicability_engine.domain.fanout import (
    FanOutCounters,
    FanOutHold,
    FanOutRun,
    FanOutStart,
    FanOutStatus,
)
from applicability_engine.domain.repository import (
    BusinessDirectoryReader,
    FanOutUnitOfWorkFactory,
)
from domain_kernel.audit import AuditActor
from domain_kernel.events import utc_now
from domain_kernel.ids import RuleVersionId

SYSTEM: Final = AuditActor.system(SERVICE_NAME)
"""Who the run's own moves name: the engine, acting for nobody."""
AUDITED_MOVES: Final = {FanOutStatus.PAUSED: PAUSE_ACTION, FanOutStatus.CANCELLED: CANCEL_ACTION}


class BeginFanOut:
    def __init__(
        self,
        fanouts: FanOutUnitOfWorkFactory,
        directory: BusinessDirectoryReader,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._fanouts = fanouts
        self._directory = directory
        self._clock = clock

    def run(self, start: FanOutStart) -> FanOutRun:
        total = self._directory.count(level=start.level)
        now = self._clock()
        with self._fanouts() as uow:
            uow.runs.add_if_absent(FanOutRun.begun(start, at=now, businesses_total=total))
            run = uow.runs.get(start.rule_version_id, for_update=True)
            if run is None:  # pragma: no cover - inserted or found in this unit
                raise FanOutNotFoundError(str(start.rule_version_id))
            counters = run.counters
            if run.is_active and not counters.evaluated and counters.businesses_total != total:
                run = run.counted(replace(counters, businesses_total=total), at=now)
                uow.runs.save(run)
        return run


@dataclass(frozen=True, slots=True)
class Controls:
    """What the workflow obeys at a batch boundary: its run as stored (None if it has none) and
    the global hold (None while released)."""

    run: FanOutRun | None
    hold: FanOutHold | None


class ReadControls:
    def __init__(self, fanouts: FanOutUnitOfWorkFactory) -> None:
        self._fanouts = fanouts

    def run(self, rule_version_id: RuleVersionId) -> Controls:
        with self._fanouts() as uow:
            return Controls(run=uow.runs.get(rule_version_id), hold=uow.hold.get())


@dataclass(frozen=True, slots=True)
class RunUpdate:
    """``counters`` replace the run's when given; ``status`` is where the run moves by itself,
    with ``reason`` (kept on the run, and the audit entry's reason for a pause or a
    cancellation) and ``error`` (kept when it fails). ``correlation_id`` ties an audit entry to
    the rule.published event behind the run."""

    rule_version_id: RuleVersionId
    counters: FanOutCounters | None = None
    status: FanOutStatus | None = None
    reason: str = ""
    error: str = ""
    correlation_id: str | None = None


class UpdateFanOut:
    def __init__(
        self, fanouts: FanOutUnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._fanouts = fanouts
        self._clock = clock

    def run(self, update: RunUpdate) -> FanOutRun:
        now = self._clock()
        with self._fanouts() as uow:
            stored = uow.runs.get(update.rule_version_id, for_update=True)
            if stored is None:
                raise FanOutNotFoundError(str(update.rule_version_id))
            run = stored
            if update.counters is not None and update.counters != run.counters:
                run = run.counted(update.counters, at=now)
            to = update.status
            if to is not None and to is not run.status and run.can_move(to):
                moved = run.move(
                    to, at=now, reason=update.reason, by=SYSTEM.label, error=update.error
                )
                action = AUDITED_MOVES.get(to)
                if action is not None:
                    uow.audit.write(
                        run_entry(
                            action,
                            run,
                            moved,
                            actor=SYSTEM,
                            reason=update.reason,
                            at=now,
                            correlation_id=update.correlation_id,
                        )
                    )
                run = moved
            if run != stored:
                uow.runs.save(run)
        return run
