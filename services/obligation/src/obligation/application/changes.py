"""Deadline changes, withdrawals, supersessions and closures on open obligations (ADR-015).

``ApplyDeadlineChange`` moves every open obligation of a rule version and period to the new
date and publishes ``obligation.rescheduled``; ``WithdrawRule`` closes every open obligation
of a rule version with reason ``rule_withdrawn``; ``CloseSupersededPeriods`` closes, with reason
``rule_superseded``, the open obligations of a superseded version that the newer one takes over
(``domain.rule_versions.taken_over``: a period that ends after the newer version takes effect, a
one-off due on that day or later, or one without a date), and leaves the earlier ones open;
``CloseObligation`` closes one obligation for a user's reason. Closed obligations are never
touched: history stays as it was, and running a change again changes nothing more. Every event is
recorded with its change log row (``audit.record``).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import ObligationId, RuleVersionId, TenantId, UserId
from domain_kernel.status import ClosureReason
from obligation.application.audit import record
from obligation.application.materialise import IST
from obligation.domain.errors import ObligationNotFoundError
from obligation.domain.events import RescheduleReason
from obligation.domain.model import due_at_end_of_day
from obligation.domain.repository import UnitOfWorkFactory
from obligation.domain.rule_versions import taken_over


@dataclass(frozen=True, slots=True)
class DeadlineChange:
    tenant_id: TenantId
    rule_version_id: RuleVersionId
    period_label: str | None
    new_due_on: date
    reason: RescheduleReason
    caused_by: RuleVersionId | None = None


@dataclass(frozen=True, slots=True)
class ChangeResult:
    changed: tuple[ObligationId, ...]
    unchanged: int


class ApplyDeadlineChange:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, change: DeadlineChange) -> ChangeResult:
        now = self._clock()
        new_due_at = due_at_end_of_day(change.new_due_on, IST)
        changed: list[ObligationId] = []
        unchanged = 0
        with self._unit_of_work(change.tenant_id) as uow:
            for obligation in uow.obligations.open_for_rule_version(
                change.rule_version_id, change.period_label
            ):
                if obligation.due_at is None or obligation.due_at == new_due_at:
                    unchanged += 1
                    continue
                moved, event = obligation.reschedule(
                    new_due_at, reason=change.reason, at=now, caused_by=change.caused_by
                )
                uow.obligations.save(moved)
                record(uow, event, moved)
                changed.append(moved.id)
        return ChangeResult(tuple(changed), unchanged)


class WithdrawRule:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, tenant_id: TenantId, rule_version_id: RuleVersionId) -> ChangeResult:
        now = self._clock()
        closed: list[ObligationId] = []
        with self._unit_of_work(tenant_id) as uow:
            for obligation in uow.obligations.open_for_rule_version(rule_version_id):
                done, event = obligation.close(ClosureReason.RULE_WITHDRAWN, at=now)
                uow.obligations.save(done)
                record(uow, event, done)
                closed.append(done.id)
        return ChangeResult(tuple(closed), 0)


@dataclass(frozen=True, slots=True)
class Supersession:
    """A rule version superseded by a newer one in force from ``effective_from``, as one tenant
    sees it."""

    tenant_id: TenantId
    rule_version_id: RuleVersionId
    superseded_by: RuleVersionId
    effective_from: date


class CloseSupersededPeriods:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, supersession: Supersession) -> ChangeResult:
        now = self._clock()
        closed: list[ObligationId] = []
        kept = 0
        with self._unit_of_work(supersession.tenant_id) as uow:
            for obligation in uow.obligations.open_for_rule_version(supersession.rule_version_id):
                if not taken_over(obligation, supersession.effective_from, IST):
                    kept += 1
                    continue
                done, event = obligation.close(ClosureReason.RULE_SUPERSEDED, at=now)
                uow.obligations.save(done)
                record(uow, event, done)
                closed.append(done.id)
        return ChangeResult(tuple(closed), kept)


class CloseObligation:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        obligation_id: ObligationId,
        reason: ClosureReason,
        *,
        by: UserId | None = None,
    ) -> ObligationId:
        now = self._clock()
        with self._unit_of_work(tenant_id) as uow:
            obligation = uow.obligations.get(obligation_id)
            if obligation is None:
                raise ObligationNotFoundError(str(obligation_id))
            done, event = obligation.close(reason, at=now, by=by)
            uow.obligations.save(done)
            record(uow, event, done)
        return done.id
