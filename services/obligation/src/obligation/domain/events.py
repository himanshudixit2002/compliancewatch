"""Events the obligation service publishes; payload fields follow packages/contracts/events."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, UserId
from domain_kernel.status import ClosureReason, ObligationStatus


class RescheduleReason(StrEnum):
    DEADLINE_EXTENDED = "deadline_extended"
    CORRECTED = "corrected"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationCreated(DomainEvent):
    topic: ClassVar[str] = "obligation.created"
    schema_version: ClassVar[str] = "1.0.0"

    obligation_id: ObligationId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    decision_id: DecisionId
    title: str
    steps: tuple[str, ...]
    due_at: datetime | None
    evidence_type: str = ""

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.decision_id, DecisionId, "decision_id")
        require_text(self.title, "title")
        require_instance(self.steps, tuple, "steps")
        if self.due_at is not None:
            require_aware(self.due_at, "due_at")
        require_instance(self.evidence_type, str, "evidence_type")


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationRescheduled(DomainEvent):
    topic: ClassVar[str] = "obligation.rescheduled"
    schema_version: ClassVar[str] = "1.0.0"

    obligation_id: ObligationId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    previous_due_at: datetime
    new_due_at: datetime
    reason: RescheduleReason
    caused_by_rule_version_id: RuleVersionId | None = None

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_aware(self.previous_due_at, "previous_due_at")
        require_aware(self.new_due_at, "new_due_at")
        require_instance(self.reason, RescheduleReason, "reason")
        if self.caused_by_rule_version_id is not None:
            require_instance(
                self.caused_by_rule_version_id, RuleVersionId, "caused_by_rule_version_id"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationClosed(DomainEvent):
    topic: ClassVar[str] = "obligation.closed"
    schema_version: ClassVar[str] = "1.0.0"

    obligation_id: ObligationId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    status: ObligationStatus
    reason: ClosureReason
    closed_at: datetime
    closed_by: UserId | None = None

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.status, ObligationStatus, "status")
        require_instance(self.reason, ClosureReason, "reason")
        require_aware(self.closed_at, "closed_at")
        if self.closed_by is not None:
            require_instance(self.closed_by, UserId, "closed_by")


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationDueSoon(DomainEvent):
    """An open obligation's due date is near: the reminder sweep publishes one per obligation,
    due date and reminder threshold (``domain.reminders``)."""

    topic: ClassVar[str] = "obligation.due_soon"
    schema_version: ClassVar[str] = "1.0.0"

    obligation_id: ObligationId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    title: str
    due_at: datetime
    days_left: int
    reminder_index: int

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_text(self.title, "title")
        require_aware(self.due_at, "due_at")
        require_int(self.days_left, "days_left", minimum=0)
        require_int(self.reminder_index, "reminder_index", minimum=1)
