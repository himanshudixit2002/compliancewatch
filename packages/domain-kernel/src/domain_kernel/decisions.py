"""The outcome of evaluating one rule version against one business profile."""

from dataclasses import dataclass
from datetime import datetime

from domain_kernel._validation import require_aware, require_instance, require_int
from domain_kernel.confidence import Confidence
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.predicates import Applicability, PredicateResult


@dataclass(frozen=True, slots=True)
class ApplicabilityDecision:
    """Result, confidence and the per-predicate results behind them."""

    decision_id: DecisionId
    tenant_id: TenantId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    result: Applicability
    confidence: Confidence
    evaluated: tuple[PredicateResult, ...]
    profile_version: int
    decided_at: datetime

    def __post_init__(self) -> None:
        require_instance(self.decision_id, DecisionId, "decision_id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.result, Applicability, "result")
        require_instance(self.confidence, Confidence, "confidence")
        for index, item in enumerate(require_instance(self.evaluated, tuple, "evaluated")):
            require_instance(item, PredicateResult, f"evaluated[{index}]")
        require_int(self.profile_version, "profile_version", minimum=1)
        require_aware(self.decided_at, "decided_at")

    @property
    def needs_review(self) -> bool:
        """True when the result is unsure or the confidence is below the review threshold."""
        return self.result is Applicability.UNSURE or self.confidence.needs_review()
