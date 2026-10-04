"""Review items: the decisions a person has to settle, one open item per business and rule
version at most.

ADR-007 routes a decision a model or a person has to judge to a reviewer. A decision opens an
item when it needs review because of a free-text predicate nobody has judged (``free_text``) or
a judgement whose confidence is below the review threshold (``low_confidence``). A decision that
is unsure only because the profile has not set an attribute opens none: the owner answers the
question, and the next profile.updated decides again. So does one the ontology cannot decide (an
attribute it does not know, a comparison it refuses), which is a fault of the rule to fix in the
rulebook rather than a question about the business.

While an item is open it follows the latest decision of its business and rule version: a later
decision that still needs review takes its place under the item, and a later decision that
needs none settles it (resolution ``dismiss``, no person). A reviewer resolves an open item to
``applies`` or ``not_applicable``, which appends a decision with trigger ``review``, or to
``dismiss``, which appends nothing; either way the item records who, when and why.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final, Self

from applicability_engine.domain.model import Decision
from domain_kernel._validation import require_aware, require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import (
    BusinessId,
    DecisionId,
    EntityId,
    RuleVersionId,
    TenantId,
    UserId,
    derive_id,
)
from domain_kernel.predicates import Applicability, PredicateKind

NOTE_MAX_CHARS: Final = 2_000


class ReviewReason(StrEnum):
    """Why a decision needs a person."""

    FREE_TEXT = "free_text"
    LOW_CONFIDENCE = "low_confidence"


class ReviewStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class Resolution(StrEnum):
    """What the reviewer settled on: a result for the decision, or no decision at all."""

    APPLIES = "applies"
    NOT_APPLICABLE = "not_applicable"
    DISMISS = "dismiss"

    @property
    def result(self) -> Applicability | None:
        """The result of the decision the resolution appends; None for ``dismiss``."""
        return None if self is Resolution.DISMISS else Applicability(self.value)


@dataclass(frozen=True, slots=True)
class ReviewItemId(EntityId):
    """A review item; derived from the decision that opened it."""


def review_item_id_for(decision_id: DecisionId) -> ReviewItemId:
    """The id of the item ``decision_id`` opens: the same on every call, so a replayed decision
    opens nothing new."""
    return derive_id(ReviewItemId, "applicability_review_item", str(decision_id))


def review_reason(decision: Decision) -> ReviewReason | None:
    """Why ``decision`` needs a person, or None when it needs none or only the owner's answers.

    A free-text predicate left unsure comes first; then a judged predicate, or the decision
    itself, whose confidence is below the review threshold. Missing attributes, attributes the
    ontology does not know and comparisons it refuses are unsure too, but no reviewer settles
    them, so they give no reason.
    """
    if not decision.needs_review:
        return None
    if any(
        item.predicate.kind is PredicateKind.FREE_TEXT and item.outcome is Applicability.UNSURE
        for item in decision.evaluated
    ):
        return ReviewReason.FREE_TEXT
    judged_low = any(
        item.outcome is not Applicability.UNSURE and item.confidence.needs_review()
        for item in decision.evaluated
    )
    decided_low = decision.result is not Applicability.UNSURE and decision.confidence.needs_review()
    if judged_low or decided_low:
        return ReviewReason.LOW_CONFIDENCE
    return None


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One decision waiting for a reviewer, or settled. ``decision_id`` is the decision under
    review: the latest of the business and rule version while the item is open. A resolved
    item names its resolution, when it was made and the note; ``resolved_by`` is the reviewer,
    or None when a later decision settled it, and ``resolution_decision_id`` the decision a
    resolution to applies or not_applicable appended."""

    item_id: ReviewItemId
    tenant_id: TenantId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    decision_id: DecisionId
    reason: ReviewReason
    opened_at: datetime
    status: ReviewStatus = ReviewStatus.OPEN
    resolution: Resolution | None = None
    resolved_by: UserId | None = None
    resolved_at: datetime | None = None
    note: str = ""
    resolution_decision_id: DecisionId | None = None

    def __post_init__(self) -> None:
        require_instance(self.item_id, ReviewItemId, "item_id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.decision_id, DecisionId, "decision_id")
        require_instance(self.reason, ReviewReason, "reason")
        require_aware(self.opened_at, "opened_at")
        require_instance(self.status, ReviewStatus, "status")
        require_instance(self.note, str, "note")
        if len(self.note) > NOTE_MAX_CHARS:
            raise InvariantViolationError(f"note has at most {NOTE_MAX_CHARS} characters")
        if self.status is ReviewStatus.OPEN:
            self._check_open()
        else:
            self._check_resolved()

    def _check_open(self) -> None:
        if (
            self.resolution is not None
            or self.resolved_by is not None
            or self.resolved_at is not None
            or self.note
            or self.resolution_decision_id is not None
        ):
            raise InvariantViolationError("an open review item has no resolution yet")

    def _check_resolved(self) -> None:
        require_instance(self.resolution, Resolution, "resolution")
        if self.resolved_by is not None:
            require_instance(self.resolved_by, UserId, "resolved_by")
        require_aware(self.resolved_at, "resolved_at")
        appends = self.resolution is not Resolution.DISMISS
        if appends != (self.resolution_decision_id is not None):
            raise InvariantViolationError(
                "a resolution to applies or not_applicable names the decision it appended, and "
                "only such a resolution does"
            )
        if self.resolution_decision_id is not None:
            require_instance(self.resolution_decision_id, DecisionId, "resolution_decision_id")
        if appends and self.resolved_by is None:
            raise InvariantViolationError("only a person resolves an item to a result")

    @property
    def is_open(self) -> bool:
        return self.status is ReviewStatus.OPEN

    @classmethod
    def open(cls, decision: Decision, reason: ReviewReason) -> Self:
        """The item ``decision`` opens, opened when it was decided."""
        return cls(
            item_id=review_item_id_for(decision.decision_id),
            tenant_id=decision.tenant_id,
            business_id=decision.business_id,
            rule_version_id=decision.rule_version_id,
            decision_id=decision.decision_id,
            reason=reason,
            opened_at=decision.decided_at,
        )

    def follow(self, decision: Decision, reason: ReviewReason) -> Self:
        """The open item under ``decision``, a later decision of its pair that needs review."""
        self._require_open_for(decision)
        return replace(self, decision_id=decision.decision_id, reason=reason)

    def settled_by(self, decision: Decision, *, at: datetime) -> Self:
        """The item a later decision of its pair that needs no review settled: dismissed by no
        person, with a note naming the decision."""
        self._require_open_for(decision)
        return replace(
            self,
            status=ReviewStatus.RESOLVED,
            resolution=Resolution.DISMISS,
            resolved_at=at,
            note=f"settled by decision {decision.decision_id} ({decision.result.value})",
        )

    def resolve(
        self,
        resolution: Resolution,
        *,
        by: UserId,
        at: datetime,
        note: str,
        decision_id: DecisionId | None,
    ) -> Self:
        """The item a reviewer resolved; ``decision_id`` is the decision a result appended."""
        if not self.is_open:
            raise InvariantViolationError(f"review item {self.item_id} is already resolved")
        return replace(
            self,
            status=ReviewStatus.RESOLVED,
            resolution=resolution,
            resolved_by=by,
            resolved_at=at,
            note=note,
            resolution_decision_id=decision_id,
        )

    def _require_open_for(self, decision: Decision) -> None:
        if not self.is_open:
            raise InvariantViolationError(f"review item {self.item_id} is already resolved")
        if (decision.business_id, decision.rule_version_id) != (
            self.business_id,
            self.rule_version_id,
        ):
            raise InvariantViolationError(
                f"decision {decision.decision_id} is of another business or rule version"
            )


@dataclass(frozen=True, slots=True)
class ReviewItemKey:
    """Where a page of review items ends: oldest first, then by id."""

    opened_at: datetime
    item_id: ReviewItemId

    def __post_init__(self) -> None:
        require_aware(self.opened_at, "opened_at")
        require_instance(self.item_id, ReviewItemId, "item_id")

    @classmethod
    def of(cls, item: ReviewItem) -> "ReviewItemKey":
        return cls(item.opened_at, item.item_id)
