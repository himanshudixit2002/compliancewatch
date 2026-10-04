"""Request and response bodies of the applicability-engine API."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from applicability_engine.application.review import ReviewEntry
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.domain.review import (
    NOTE_MAX_CHARS,
    Resolution,
    ReviewReason,
    ReviewStatus,
)
from domain_kernel.predicates import (
    Applicability,
    PredicateKind,
    PredicateResult,
    specification_to_mapping,
)


class EvaluateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_version_id: Annotated[UUID, Field(description="A published rule version")]
    fy: Annotated[
        str | None,
        Field(
            pattern=r"^[0-9]{4}-[0-9]{2}$",
            description=(
                "Financial year the profile's per-year attributes are read for, such as 2026-27; "
                "absent means the current one in India"
            ),
        ),
    ] = None


class PredicateResultOut(BaseModel):
    """One predicate of the rule's specification: its outcome, the confidence behind it and
    why. ``predicate`` is the kernel's predicate mapping, as the rule version stores it."""

    attribute: str
    kind: PredicateKind
    description: str
    predicate: dict[str, Any]
    outcome: Applicability
    confidence: float
    reason: str
    needs_review: bool

    @classmethod
    def from_result(cls, result: PredicateResult) -> "PredicateResultOut":
        return cls(
            attribute=result.predicate.attribute,
            kind=result.predicate.kind,
            description=result.predicate.describe(),
            predicate=specification_to_mapping(result.predicate),
            outcome=result.outcome,
            confidence=result.confidence.value,
            reason=result.reason,
            needs_review=result.needs_review,
        )


class DecisionOut(BaseModel):
    """One decision: the result of one rule version for one version of a business's profile.
    ``needs_review`` is true when the result is unsure or the confidence is below the review
    threshold; ``evaluated`` lists every predicate in the specification, left to right."""

    decision_id: UUID
    business_id: UUID
    rule_version_id: UUID
    result: Applicability
    confidence: float
    needs_review: bool
    profile_version: int
    as_of_fy: str | None
    trigger: Trigger
    decided_at: datetime
    evaluated: list[PredicateResultOut]

    @classmethod
    def from_decision(cls, decision: Decision) -> "DecisionOut":
        return cls(
            decision_id=decision.decision_id.value,
            business_id=decision.business_id.value,
            rule_version_id=decision.rule_version_id.value,
            result=decision.result,
            confidence=decision.confidence.value,
            needs_review=decision.needs_review,
            profile_version=decision.profile_version,
            as_of_fy=None if decision.as_of_fy is None else decision.as_of_fy.label,
            trigger=decision.trigger,
            decided_at=decision.decided_at.astimezone(UTC),
            evaluated=[PredicateResultOut.from_result(item) for item in decision.evaluated],
        )


class DecisionCursor(BaseModel):
    """Where a page of decisions ends: the last decision on it."""

    decided_at: AwareDatetime
    id: UUID


class ReviewItemOut(BaseModel):
    """A decision waiting for a reviewer, or settled. ``decision`` is the decision under review:
    the latest of the business and the rule version while the item is open. ``resolved_by`` is
    the reviewer, or null when a later decision that needs no review settled the item;
    ``resolution_decision_id`` is the decision a resolution to applies or not_applicable
    appended."""

    item_id: UUID
    business_id: UUID
    rule_version_id: UUID
    reason: ReviewReason
    status: ReviewStatus
    opened_at: datetime
    decision: DecisionOut
    resolution: Resolution | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    note: str
    resolution_decision_id: UUID | None

    @classmethod
    def from_entry(cls, entry: ReviewEntry) -> "ReviewItemOut":
        item = entry.item
        return cls(
            item_id=item.item_id.value,
            business_id=item.business_id.value,
            rule_version_id=item.rule_version_id.value,
            reason=item.reason,
            status=item.status,
            opened_at=item.opened_at.astimezone(UTC),
            decision=DecisionOut.from_decision(entry.decision),
            resolution=item.resolution,
            resolved_by=None if item.resolved_by is None else item.resolved_by.value,
            resolved_at=None if item.resolved_at is None else item.resolved_at.astimezone(UTC),
            note=item.note,
            resolution_decision_id=None
            if item.resolution_decision_id is None
            else item.resolution_decision_id.value,
        )


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: Annotated[
        Resolution,
        Field(
            description=(
                "applies or not_applicable appends a decision with trigger review and publishes "
                "applicability.decided; dismiss closes the item and appends nothing"
            )
        ),
    ]
    note: Annotated[
        str,
        Field(min_length=1, max_length=NOTE_MAX_CHARS, description="Why: kept with the item"),
    ]
    resolved_by: Annotated[
        UUID,
        Field(description="The reviewer settling the item; a signed-in user's token overrides it"),
    ]


class ReviewItemCursor(BaseModel):
    """Where a page of review items ends: the last item on it."""

    opened_at: AwareDatetime
    id: UUID
