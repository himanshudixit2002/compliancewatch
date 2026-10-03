"""The event the engine publishes; payload fields follow
packages/contracts/events/schemas/applicability.decided.v1.json."""

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Self

from applicability_engine.domain.model import Decision, Trigger
from domain_kernel._validation import require_aware, require_bool, require_instance, require_int
from domain_kernel.confidence import Confidence
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId
from domain_kernel.predicates import Applicability


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicabilityDecided(DomainEvent):
    """The engine evaluated one rule version against one business profile version. The
    obligation service consumes it."""

    topic: ClassVar[str] = "applicability.decided"
    schema_version: ClassVar[str] = "1.0.0"

    decision_id: DecisionId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    result: Applicability
    confidence: float
    profile_version: int
    decided_at: datetime
    needs_review: bool
    trigger: Trigger

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.decision_id, DecisionId, "decision_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.result, Applicability, "result")
        Confidence(self.confidence)
        require_int(self.profile_version, "profile_version", minimum=1)
        require_aware(self.decided_at, "decided_at")
        require_bool(self.needs_review, "needs_review")
        require_instance(self.trigger, Trigger, "trigger")

    @classmethod
    def of(cls, decision: Decision) -> Self:
        return cls(
            tenant_id=decision.tenant_id,
            occurred_at=decision.decided_at,
            decision_id=decision.decision_id,
            business_id=decision.business_id,
            rule_version_id=decision.rule_version_id,
            result=decision.result,
            confidence=decision.confidence.value,
            profile_version=decision.profile_version,
            decided_at=decision.decided_at,
            needs_review=decision.needs_review,
            trigger=decision.trigger,
        )
