"""A decision: one evaluation of one rule version against one version of a business profile.

The kernel's ``ApplicabilityDecision`` holds the result, the confidence and the per-predicate
results; ``Decision`` adds what caused the evaluation and the financial year the profile's
per-year attributes were read for. Decisions are append-only: recomputing writes a new one, and
the latest for a (business, rule version) pair is the one in force.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain_kernel._validation import require_aware, require_instance
from domain_kernel.decisions import ApplicabilityDecision
from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import DecisionId, RuleVersionId
from domain_kernel.predicates import Specification
from domain_kernel.status import RuleVersionStatus


class Trigger(StrEnum):
    """What caused an evaluation; the ``trigger`` of ``applicability.decided``."""

    MANUAL = "manual"
    RULE_PUBLISHED = "rule_published"
    PROFILE_UPDATED = "profile_updated"


@dataclass(frozen=True, slots=True)
class RuleVersionSpec:
    """The part of a rule version the engine evaluates: its status and its specification."""

    rule_version_id: RuleVersionId
    status: RuleVersionStatus
    specification: Specification

    def __post_init__(self) -> None:
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.status, RuleVersionStatus, "status")
        if not isinstance(self.specification, Specification):
            raise InvariantViolationError(
                f"specification must be a Specification, got {type(self.specification).__name__}"
            )


@dataclass(frozen=True, slots=True)
class Decision(ApplicabilityDecision):
    trigger: Trigger
    as_of_fy: FinancialYear | None

    def __post_init__(self) -> None:
        ApplicabilityDecision.__post_init__(self)
        require_instance(self.trigger, Trigger, "trigger")
        if self.as_of_fy is not None:
            require_instance(self.as_of_fy, FinancialYear, "as_of_fy")


@dataclass(frozen=True, slots=True)
class DecisionKey:
    """Where a page of a business's decisions ends: newest first, then by id."""

    decided_at: datetime
    decision_id: DecisionId

    def __post_init__(self) -> None:
        require_aware(self.decided_at, "decided_at")
        require_instance(self.decision_id, DecisionId, "decision_id")

    @classmethod
    def of(cls, decision: Decision) -> "DecisionKey":
        return cls(decision.decided_at, decision.decision_id)
