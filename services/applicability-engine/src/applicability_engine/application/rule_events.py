"""The rulebook's events the engine acts on: rule.published starts a fan-out, rule.withdrawn
cancels one. What the worker's consumer of group ``applicability-engine.rules`` does with each.

Like the profile.updated consumer, each event is handled in two phases, so nothing leaves the
process while a transaction is open:

- ``plan_published(event)`` reads, with no transaction open: it drops the rulebook client's
  cached listings of versions (the recompute sees the new version at once) and reads the version
  (its status, rule key, level and schedule). With the flag ``applicability.fanout`` on it then
  starts the version's workflow (``FanOutWorkflows.start``; a second start of the same version is
  refused, so a redelivered event starts nothing twice). A version the rulebook does not have, or
  that it withdrew, fans out nowhere, and neither does a superseded one, unless it still governs
  a duty due today (``RuleVersionSpec.still_governs``): an event read after a newer version took
  over still fans it out to the businesses that owe its last periods. The newer version's own
  fan-out decides only the newer version.
- ``plan_withdrawn(event)`` drops the cached listing too: the withdrawn version is no longer in
  force.
- ``apply(plan, units)`` writes in one unit of work of no tenant, on the consumer's connection so
  it commits with the event's inbox row. A published version gets its run unless it has one: a
  running run, or with the flag off a ``disabled`` one, which never runs. A withdrawn version's
  run that has not finished is cancelled, audited as the system with the reason; the workflow
  sees it at its next batch boundary, or its next poll while it waits, and stops. The decisions
  the run made stay.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from applicability_engine.application.fanout import CANCEL_ACTION, run_entry
from applicability_engine.application.fanout_runs import SYSTEM
from applicability_engine.domain.fanout import FanOutRun, FanOutStart, FanOutStatus
from applicability_engine.domain.ports import FanOutWorkflows, RulebookReader
from applicability_engine.domain.repository import FanOutUnitOfWorkFactory
from domain_kernel.events import utc_now
from domain_kernel.ids import CorrelationId, EventId, RuleVersionId
from domain_kernel.status import RuleVersionStatus

IST = timezone(timedelta(hours=5, minutes=30))
"""Duties fall due on days in India."""


@dataclass(frozen=True, slots=True)
class RulePublished:
    """What the engine reads from one rule.published event."""

    event_id: EventId
    rule_version_id: RuleVersionId
    supersedes: tuple[RuleVersionId, ...] = ()
    correlation_id: CorrelationId | None = None


@dataclass(frozen=True, slots=True)
class RuleWithdrawn:
    """What the engine reads from one rule.withdrawn event."""

    event_id: EventId
    rule_version_id: RuleVersionId
    correlation_id: CorrelationId | None = None


@dataclass(frozen=True, slots=True)
class RulePlan:
    """What the reads found. For a publication, ``start`` is the fan-out to record (None when
    nothing fans out, with ``skipped`` saying why), ``disabled`` that the flag was off and
    ``started`` that this event started the workflow (False for a redelivery)."""

    published: RulePublished | None = None
    withdrawn: RuleWithdrawn | None = None
    start: FanOutStart | None = None
    disabled: bool = False
    started: bool = False
    skipped: str = ""


class RuleEvents:
    def __init__(
        self,
        rulebook: RulebookReader,
        workflows: FanOutWorkflows,
        *,
        enabled: bool,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._rulebook = rulebook
        self._workflows = workflows
        self._enabled = enabled
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return self._enabled

    def plan_published(self, event: RulePublished) -> RulePlan:
        """The reads, and the workflow's start: no unit of work is open."""
        self._rulebook.forget_in_force()
        version = self._rulebook.rule_version(event.rule_version_id)
        if version is None:
            return RulePlan(published=event, skipped="the rulebook has no such version")
        if not version.still_governs(self._clock().astimezone(IST).date()):
            why = f"the version is {version.status.value}"
            if version.status is RuleVersionStatus.SUPERSEDED:
                why += " and governs no duty still due"
            return RulePlan(published=event, skipped=why)
        if version.level is None or version.rule_key is None:
            return RulePlan(published=event, skipped="the rulebook gave no rule key or level")
        start = FanOutStart(
            rule_version_id=version.rule_version_id,
            rule_key=version.rule_key,
            level=version.level,
            trigger_event_id=event.event_id,
            supersedes=event.supersedes,
            correlation_id=event.correlation_id,
        )
        if not self._enabled:
            return RulePlan(published=event, start=start, disabled=True)
        return RulePlan(published=event, start=start, started=self._workflows.start(start))

    def plan_withdrawn(self, event: RuleWithdrawn) -> RulePlan:
        self._rulebook.forget_in_force()
        return RulePlan(withdrawn=event)

    def apply(self, plan: RulePlan, units: FanOutUnitOfWorkFactory) -> FanOutRun | None:
        """The writes, in one unit of work of no tenant; the run as stored, or None."""
        if plan.withdrawn is not None:
            return self._cancel(plan.withdrawn, units)
        if plan.start is None:
            return None
        now = self._clock()
        with units() as uow:
            uow.runs.add_if_absent(FanOutRun.begun(plan.start, at=now, disabled=plan.disabled))
            return uow.runs.get(plan.start.rule_version_id)

    def _cancel(self, event: RuleWithdrawn, units: FanOutUnitOfWorkFactory) -> FanOutRun | None:
        now = self._clock()
        reason = f"rule version {event.rule_version_id} was withdrawn"
        with units() as uow:
            run = uow.runs.get(event.rule_version_id, for_update=True)
            if run is None or not run.is_active:
                return run
            cancelled = run.move(FanOutStatus.CANCELLED, at=now, reason=reason, by=SYSTEM.label)
            uow.runs.save(cancelled)
            uow.audit.write(
                run_entry(
                    CANCEL_ACTION,
                    run,
                    cancelled,
                    actor=SYSTEM,
                    reason=reason,
                    at=now,
                    correlation_id=None
                    if event.correlation_id is None
                    else str(event.correlation_id),
                )
            )
        return cancelled
