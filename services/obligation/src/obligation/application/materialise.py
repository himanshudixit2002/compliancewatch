"""Create the obligations a rule version implies for one business (ADR-015).

A recurring rule gets one obligation per period inside a rolling window (the period that
contains ``as_of`` and the ones after it, ``window`` in total), idempotent on (business, rule
version, period): running it again creates nothing new. A one-off rule gets one obligation due
``due_in_days`` after ``as_of``. Periods that end before the rule version is in force are
skipped. Every created obligation is written together with its ``obligation.created`` event
and the change log row that records it.
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
from obligation.domain.repository import UnitOfWorkFactory

IST = timezone(timedelta(hours=5, minutes=30))
"""Due dates are days in India; an obligation is due at the end of that day in IST."""


@dataclass(frozen=True, slots=True)
class MaterialiseRequest:
    tenant_id: TenantId
    business_id: BusinessId
    decision_id: DecisionId
    rule: RuleVersionSnapshot
    as_of: date


@dataclass(frozen=True, slots=True)
class MaterialiseResult:
    created: tuple[ObligationId, ...]
    existing: int
    skipped_before_effective: int


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
        rule = request.rule
        now = self._clock().astimezone(UTC)
        created: list[ObligationId] = []
        existing = 0
        skipped = 0
        with self._unit_of_work(request.tenant_id) as uow:
            for period, due_at in self._plan(rule, request.as_of):
                label = None if period is None else period.label
                if period is not None and period.end <= rule.effective.start:
                    skipped += 1
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
                    created_at=now,
                    updated_at=now,
                )
                uow.obligations.add(obligation)
                record(uow, obligation.created_event(), obligation)
                created.append(obligation.id)
        return MaterialiseResult(tuple(created), existing, skipped)

    def _plan(
        self, rule: RuleVersionSnapshot, as_of: date
    ) -> list[tuple[Period | None, datetime | None]]:
        recurrence = rule.recurrence
        if recurrence is None:
            days = rule.obligation_template.due_in_days
            due = None if days is None else due_at_end_of_day(as_of + timedelta(days=days), IST)
            return [(None, due)]
        return [
            (period, due_at_end_of_day(recurrence.due_date(period), IST))
            for period in recurrence.periods(as_of, self._window)
        ]


def _title(rule: RuleVersionSnapshot, period: Period | None) -> str:
    title = rule.obligation_template.title
    return title if period is None else f"{title} ({period.label})"
