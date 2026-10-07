"""A decision: one evaluation of one rule version against one version of a business profile.

The kernel's ``ApplicabilityDecision`` holds the result, the confidence and the per-predicate
results; ``Decision`` adds what caused the evaluation and the financial year the profile's
per-year attributes were read for. Decisions are append-only: recomputing writes a new one, and
the latest for a (business, rule version) pair is the one in force.

A decision something other than a person's request caused carries a ``trigger_ref``: the event
or the review item behind it (``profile.updated:<event id>``, ``rule.published:<event id>`` for a
fan-out, ``review:<item id>``). Its id is
derived from the reference, the business and the rule version (``decision_id_for``), and the
store keeps one decision per (trigger_ref, business, rule version), so handling the same event
again stores nothing new.

A version is decided while it is published, and after it is superseded for as long as it still
governs a duty due (``RuleVersionSpec.still_governs``): a version governs the periods whose last
day it is in force on, so superseded from 1 October a monthly return's version still owes
September, due 20 October, and a business decided on 5 October must be decided for it.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.decisions import ApplicabilityDecision
from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, derive_id
from domain_kernel.ontology import AttributeLevel
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Specification
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import one_off_due_on
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
class Schedule:
    """When a rule version's duties fall due, as the obligation service makes them (ADR-015):
    one obligation per period of ``recurrence`` for a duty that repeats, else one due
    ``due_in_days`` after the decision (undated without them), each the version's while it is in
    force over ``effective``."""

    effective: EffectivePeriod
    recurrence: Recurrence | None = None
    due_in_days: int | None = None

    def __post_init__(self) -> None:
        require_instance(self.effective, EffectivePeriod, "effective")
        if self.recurrence is not None:
            require_instance(self.recurrence, Recurrence, "recurrence")
        if self.due_in_days is not None:
            require_int(self.due_in_days, "due_in_days", minimum=0)

    def still_due(self, as_of: date) -> bool:
        """Whether a version that has ended still governs a duty due on or after ``as_of``.

        A recurring one: a period still due then whose last day it was in force on
        (``Recurrence.periods_governed``, the rule the obligation service makes periods by).
        Superseded from 1 October, a monthly return due on the 20th still governs September on
        5 October, and nothing on 25 October. A one-off: the due day of an obligation decided on
        ``as_of`` (``one_off_due_on``), which belongs to the version in force on it, so never one
        that ended; an undated one-off is the newer version's.
        """
        if self.recurrence is not None:
            return bool(self.recurrence.periods_governed(self.effective, as_of, 1))
        due_on = one_off_due_on(as_of, self.due_in_days)
        return due_on is not None and self.effective.contains(due_on)


@dataclass(frozen=True, slots=True)
class RuleVersionSpec:
    """The part of a rule version the engine evaluates: its status and its specification, and
    when the reader knows them its rule key, the level of the nodes it is evaluated against (a
    fan-out pages the directory by that level) and its ``schedule``."""

    rule_version_id: RuleVersionId
    status: RuleVersionStatus
    specification: Specification
    rule_key: str | None = None
    level: AttributeLevel | None = None
    schedule: Schedule | None = None

    def __post_init__(self) -> None:
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.status, RuleVersionStatus, "status")
        if not isinstance(self.specification, Specification):
            raise InvariantViolationError(
                f"specification must be a Specification, got {type(self.specification).__name__}"
            )
        if self.rule_key is not None:
            require_text(self.rule_key, "rule_key")
        if self.level is not None:
            require_instance(self.level, AttributeLevel, "level")
        if self.schedule is not None:
            require_instance(self.schedule, Schedule, "schedule")

    def still_governs(self, as_of: date) -> bool:
        """Whether the engine still decides the version on ``as_of``: it is published, or it is
        superseded and still governs a duty due then (``Schedule.still_due``), which a business
        decided now is still to be given. A withdrawn version governs nothing (its obligations
        close), and neither does a draft, nor a superseded one whose schedule is unknown."""
        if self.status is RuleVersionStatus.PUBLISHED:
            return True
        return (
            self.status is RuleVersionStatus.SUPERSEDED
            and self.schedule is not None
            and self.schedule.still_due(as_of)
        )


@dataclass(frozen=True, slots=True)
class RuleInForce:
    """A rule version the rulebook lists, with the level of the hierarchy nodes it is evaluated
    against (entity, registration or location): a published one in force on a date, or a
    superseded one that ended on or after a date, which the engine decides while it still
    governs a duty due (``RuleVersionSpec.still_governs``)."""

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
    """Where a page of decisions ends, by decided_at then id: newest first in a business's
    listing, oldest first in the tenant's data export."""

    decided_at: datetime
    decision_id: DecisionId

    def __post_init__(self) -> None:
        require_aware(self.decided_at, "decided_at")
        require_instance(self.decision_id, DecisionId, "decision_id")

    @classmethod
    def of(cls, decision: Decision) -> "DecisionKey":
        return cls(decision.decided_at, decision.decision_id)
