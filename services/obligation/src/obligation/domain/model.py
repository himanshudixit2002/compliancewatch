"""The obligation aggregate: one duty for one business, for one period when the rule recurs.

An obligation is created from a rule version's template for a business the rule applies to. It
moves through the kernel's status table (open, in progress, done, waived, closed as not
applicable), can be rescheduled while open, and once closed never changes again. Every change
returns the new obligation and the event that records it; the application layer persists both
in one transaction.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Self

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, TenantId, UserId
from domain_kernel.recurrence import Period
from domain_kernel.status import (
    OBLIGATION_TRANSITIONS,
    ClosureReason,
    ObligationStatus,
    close_obligation,
)
from obligation.domain.errors import ObligationClosedError
from obligation.domain.events import (
    ObligationClosed,
    ObligationCreated,
    ObligationRescheduled,
    RescheduleReason,
)


@dataclass(frozen=True, slots=True)
class Obligation:
    id: ObligationId
    tenant_id: TenantId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    decision_id: DecisionId
    title: str
    steps: tuple[str, ...]
    evidence_type: str
    period: Period | None
    due_at: datetime | None
    status: ObligationStatus
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    closed_reason: ClosureReason | None = None
    closed_by: UserId | None = None

    def __post_init__(self) -> None:
        require_instance(self.id, ObligationId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.decision_id, DecisionId, "decision_id")
        require_text(self.title, "title")
        for index, step in enumerate(require_instance(self.steps, tuple, "steps")):
            require_text(step, f"steps[{index}]")
        require_instance(self.evidence_type, str, "evidence_type")
        if self.period is not None:
            require_instance(self.period, Period, "period")
        if self.due_at is not None:
            require_aware(self.due_at, "due_at")
        require_instance(self.status, ObligationStatus, "status")
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        closed = OBLIGATION_TRANSITIONS.is_terminal(self.status)
        if closed != (self.closed_at is not None) or closed != (self.closed_reason is not None):
            raise InvariantViolationError(
                "closed_at and closed_reason are set exactly when the status is terminal"
            )
        if self.closed_at is not None:
            require_aware(self.closed_at, "closed_at")
            require_instance(self.closed_reason, ClosureReason, "closed_reason")
        if self.closed_by is not None:
            require_instance(self.closed_by, UserId, "closed_by")

    @property
    def is_open(self) -> bool:
        return not OBLIGATION_TRANSITIONS.is_terminal(self.status)

    @property
    def period_label(self) -> str | None:
        return None if self.period is None else self.period.label

    def created_event(self) -> ObligationCreated:
        return ObligationCreated(
            tenant_id=self.tenant_id,
            occurred_at=self.created_at,
            obligation_id=self.id,
            business_id=self.business_id,
            rule_version_id=self.rule_version_id,
            decision_id=self.decision_id,
            title=self.title,
            steps=self.steps,
            due_at=self.due_at,
            evidence_type=self.evidence_type,
        )

    def start(self, at: datetime) -> Self:
        self._require_open()
        OBLIGATION_TRANSITIONS.assert_transition(self.status, ObligationStatus.IN_PROGRESS)
        return replace(
            self, status=ObligationStatus.IN_PROGRESS, updated_at=require_aware(at, "at")
        )

    def reschedule(
        self,
        new_due_at: datetime,
        *,
        reason: RescheduleReason,
        at: datetime,
        caused_by: RuleVersionId | None = None,
    ) -> tuple[Self, ObligationRescheduled]:
        """Move the due date of an open obligation; the event carries both dates."""
        self._require_open()
        require_aware(new_due_at, "new_due_at")
        if self.due_at is None:
            raise InvariantViolationError("an obligation without a due date cannot be rescheduled")
        if new_due_at == self.due_at:
            raise InvariantViolationError("new_due_at equals the current due date")
        moved = replace(self, due_at=new_due_at, updated_at=require_aware(at, "at"))
        event = ObligationRescheduled(
            tenant_id=self.tenant_id,
            occurred_at=at,
            obligation_id=self.id,
            business_id=self.business_id,
            rule_version_id=self.rule_version_id,
            previous_due_at=self.due_at,
            new_due_at=new_due_at,
            reason=reason,
            caused_by_rule_version_id=caused_by,
        )
        return moved, event

    def close(
        self, reason: ClosureReason, *, at: datetime, by: UserId | None = None
    ) -> tuple[Self, ObligationClosed]:
        """Close for a reason; the kernel decides the terminal status and whether the move is
        allowed from the current one."""
        self._require_open()
        status = close_obligation(self.status, reason)
        closed = replace(
            self,
            status=status,
            updated_at=require_aware(at, "at"),
            closed_at=at,
            closed_reason=reason,
            closed_by=by,
        )
        event = ObligationClosed(
            tenant_id=self.tenant_id,
            occurred_at=at,
            obligation_id=self.id,
            business_id=self.business_id,
            rule_version_id=self.rule_version_id,
            status=status,
            reason=reason,
            closed_at=at,
            closed_by=by,
        )
        return closed, event

    def _require_open(self) -> None:
        if not self.is_open:
            raise ObligationClosedError(str(self.id), self.status.value)


def period_matches(obligation: Obligation, period_label: str | None) -> bool:
    """True when ``period_label`` is None (every period) or equals the obligation's period."""
    return period_label is None or obligation.period_label == period_label


def due_at_end_of_day(day: date, tz: object) -> datetime:
    """The last second of ``day`` in the given timezone: what a date-only deadline means."""
    from datetime import time, tzinfo

    if not isinstance(tz, tzinfo):
        raise InvariantViolationError("tz must be a tzinfo")
    return datetime.combine(day, time(23, 59, 59), tz)
