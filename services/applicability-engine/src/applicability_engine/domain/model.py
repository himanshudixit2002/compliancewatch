"""A decision: one evaluation of one rule version against one version of a business profile.

The kernel's ``ApplicabilityDecision`` holds the result, the confidence and the per-predicate
results; ``Decision`` adds what caused the evaluation and the financial year the profile's
per-year attributes were read for. Decisions are append-only: recomputing writes a new one, and
the latest for a (business, rule version) pair is the one in force.

A decision something other than a person's request caused carries a ``trigger_ref``: the event
or the review item behind it (``profile.updated:<event id>``, ``review:<item id>``). Its id is
derived from the reference, the business and the rule version (``decision_id_for``), and the
store keeps one decision per (trigger_ref, business, rule version), so handling the same event
again stores nothing new.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.decisions import ApplicabilityDecision
from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, derive_id
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Specification
from domain_kernel.status import RuleVersionStatus

TRIGGER_REF_MAX_CHARS: Final = 120
"""The longest ``trigger_ref`` the store keeps."""


class Trigger(StrEnum):
    """What caused an evaluation; the ``trigger`` of ``applicability.decided``. ``review`` is a
    person's resolution of a review item."""

    MANUAL = "manual"
    RULE_PUBLISHED = "rule_published"
    PROFILE_UPDATED = "profile_updated"
    REVIEW = "review"


def decision_id_for(
    trigger_ref: str, business_id: BusinessId, rule_version_id: RuleVersionId
) -> DecisionId:
    """The id of the decision ``trigger_ref`` causes for the business and the rule version: the
    same on every call, so a replayed event names the decision it already made."""
    return derive_id(
        DecisionId, "applicability_decision", trigger_ref, str(business_id), str(rule_version_id)
    )


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
class RuleInForce:
    """A published rule version the rulebook lists as in force on a date, with the level of the
    hierarchy nodes it is evaluated against (entity, registration or location)."""

    spec: RuleVersionSpec
    rule_key: str
    level: AttributeLevel
    effective_from: date
    effective_to: date | None

    def __post_init__(self) -> None:
        require_instance(self.spec, RuleVersionSpec, "spec")
        require_text(self.rule_key, "rule_key")
        require_instance(self.level, AttributeLevel, "level")
        require_instance(self.effective_from, date, "effective_from")
        if self.effective_to is not None:
            require_instance(self.effective_to, date, "effective_to")

    @property
    def rule_version_id(self) -> RuleVersionId:
        return self.spec.rule_version_id


@dataclass(frozen=True, slots=True)
class Decision(ApplicabilityDecision):
    trigger: Trigger
    as_of_fy: FinancialYear | None
    trigger_ref: str | None = None

    def __post_init__(self) -> None:
        ApplicabilityDecision.__post_init__(self)
        require_instance(self.trigger, Trigger, "trigger")
        if self.as_of_fy is not None:
            require_instance(self.as_of_fy, FinancialYear, "as_of_fy")
        if self.trigger_ref is not None:
            require_text(self.trigger_ref, "trigger_ref")
            if len(self.trigger_ref) > TRIGGER_REF_MAX_CHARS:
                raise InvariantViolationError(
                    f"trigger_ref has at most {TRIGGER_REF_MAX_CHARS} characters"
                )


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
