"""Create the obligations a rule version implies for one business (ADR-015).

A recurring rule gets one obligation per period inside a rolling window (the period that
contains ``as_of`` and the ones after it, ``window`` in total), idempotent on (business, rule
version, period): running it again creates nothing new. A one-off rule gets one obligation due
``due_in_days`` after ``as_of``. Periods that end before the rule version is in force are
skipped. Every created obligation is written together with its ``obligation.created`` event
and the change log row that records it.

A request that carries the version's cached facts (``ref``) is guarded too: a period the
version no longer governs, because it ends after the version's ``effective_to``, and a one-off
due on that day or later, are refused and reported (``domain.rule_versions.holds_period`` and
``holds_due``); the version that replaced it makes them. ``materialise_in`` does the work in a
unit of work the caller holds.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from domain_kernel._validation import require_int
from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, TenantId
from domain_kernel.recurrence import Period
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import ObligationStatus
from obligation.application.audit import record
from obligation.domain.model import Obligation, due_at_end_of_day
from obligation.domain.repository import UnitOfWork, UnitOfWorkFactory
from obligation.domain.rule_versions import RuleVersionRef, holds_due, holds_period

IST = timezone(timedelta(hours=5, minutes=30))
"""Due dates are days in India; an obligation is due at the end of that day in IST."""


@dataclass(frozen=True, slots=True)
class MaterialiseRequest:
    tenant_id: TenantId
    business_id: BusinessId
    decision_id: DecisionId
    rule: RuleVersionSnapshot
    as_of: date
    ref: RuleVersionRef | None = None
    """The version's cached facts; what it no longer governs is refused. None checks nothing."""
    profile_version: int | None = None
    """The profile version of the decision; every obligation made keeps it."""


@dataclass(frozen=True, slots=True)
class MaterialiseResult:
    created: tuple[ObligationId, ...]
    existing: int
    skipped_before_effective: int
    refused: tuple[str, ...] = ()
    """What the version no longer governs: period labels, or ``one-off due <day>``."""


class MaterialiseObligations:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        *,
        window: int = 2,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._window = require_int(window, "window", minimum=1)
        self._clock = clock

    def run(self, request: MaterialiseRequest) -> MaterialiseResult:
        with self._unit_of_work(request.tenant_id) as uow:
            return materialise_in(uow, request, window=self._window, now=self._clock())


def materialise_in(
    uow: UnitOfWork, request: MaterialiseRequest, *, window: int, now: datetime
) -> MaterialiseResult:
    """``MaterialiseObligations`` in the unit of work ``uow`` of the request's tenant."""
    rule = request.rule
    created_at = now.astimezone(UTC)
    created: list[ObligationId] = []
    refused: list[str] = []
    existing = 0
    skipped = 0
    for period, due_at in _plan(rule, request.as_of, require_int(window, "window", minimum=1)):
        label = None if period is None else period.label
        if period is not None and period.end <= rule.effective.start:
            skipped += 1
            continue
        if request.ref is not None and not _held(request.ref, period, due_at):
            refused.append(label or _one_off(due_at))
            continue
        if uow.obligations.find(request.business_id, rule.rule_version_id, label):
            existing += 1
            continue
        obligation = Obligation(
            id=ObligationId.new(),
            tenant_id=request.tenant_id,
            business_id=request.business_id,
            rule_version_id=rule.rule_version_id,
            decision_id=request.decision_id,
            title=_title(rule, period),
            steps=rule.obligation_template.steps,
            evidence_type=rule.obligation_template.evidence_type,
            period=period,
            due_at=due_at,
            status=ObligationStatus.OPEN,
            created_at=created_at,
            updated_at=created_at,
            profile_version=request.profile_version,
        )
        uow.obligations.add(obligation)
        record(uow, obligation.created_event(), obligation)
        created.append(obligation.id)
    return MaterialiseResult(tuple(created), existing, skipped, tuple(refused))


def _plan(
    rule: RuleVersionSnapshot, as_of: date, window: int
) -> list[tuple[Period | None, datetime | None]]:
    recurrence = rule.recurrence
    if recurrence is None:
        days = rule.obligation_template.due_in_days
        due = None if days is None else due_at_end_of_day(as_of + timedelta(days=days), IST)
        return [(None, due)]
    return [
        (period, due_at_end_of_day(recurrence.due_date(period), IST))
        for period in recurrence.periods(as_of, window)
    ]


def _held(ref: RuleVersionRef, period: Period | None, due_at: datetime | None) -> bool:
    if period is not None:
        return holds_period(ref, period)
    return holds_due(ref, None if due_at is None else due_at.astimezone(IST).date())


def _one_off(due_at: datetime | None) -> str:
    return "one-off" if due_at is None else f"one-off due {due_at.astimezone(IST).date()}"


def _title(rule: RuleVersionSnapshot, period: Period | None) -> str:
    title = rule.obligation_template.title
    return title if period is None else f"{title} ({period.label})"
