"""Request and response bodies of the applicability-engine API."""

from datetime import UTC, datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from applicability_engine.application.review import ReviewEntry
from applicability_engine.domain.fanout import (
    MAX_REASON_CHARS,
    MIN_REASON_CHARS,
    FanOutHold,
    FanOutRun,
    FanOutStatus,
)
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.domain.review import (
    NOTE_MAX_CHARS,
    Resolution,
    ReviewReason,
    ReviewStatus,
)
from domain_kernel.ontology import AttributeLevel
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


Reason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=MIN_REASON_CHARS, max_length=MAX_REASON_CHARS
    ),
    Field(description=f"Why, in at least {MIN_REASON_CHARS} characters; kept in the audit log"),
]
OptionalReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_REASON_CHARS),
    Field(description="Why, if you say; kept in the audit log"),
]


class FanOutRunOut(BaseModel):
    """One rule version's fan-out over the business directory. ``status`` is running, held (the
    global hold stopped it at a batch boundary), paused (a person, or the run itself on flips),
    completed, cancelled, disabled (published while the flag was off) or failed (``last_error``
    says why). ``businesses_total`` is the directory entries of the level when the run began and
    ``evaluated`` the businesses decided so far; ``flip_rate`` is ``flips`` over
    ``flips_compared``, the businesses compared with the version it supersedes, or null before
    any comparison. ``status_reason`` and ``status_by`` say why and by whom the status last
    changed: a user id, ``system:applicability-engine`` or ``service:<client>``."""

    rule_version_id: UUID
    rule_key: str
    level: AttributeLevel
    status: FanOutStatus
    trigger_event_id: UUID
    supersedes: list[UUID]
    businesses_total: int
    evaluated: int
    applies: int
    flips_compared: int
    flips: int
    flip_rate: float | None
    started_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    status_reason: str
    status_by: str
    last_error: str

    @classmethod
    def from_run(cls, run: FanOutRun) -> "FanOutRunOut":
        counters = run.counters
        return cls(
            rule_version_id=run.rule_version_id.value,
            rule_key=run.rule_key,
            level=run.level,
            status=run.status,
            trigger_event_id=run.trigger_event_id.value,
            supersedes=[superseded.value for superseded in run.supersedes],
            businesses_total=counters.businesses_total,
            evaluated=counters.evaluated,
            applies=counters.applies,
            flips_compared=counters.flips_compared,
            flips=counters.flips,
            flip_rate=counters.flip_rate,
            started_at=run.started_at.astimezone(UTC),
            updated_at=run.updated_at.astimezone(UTC),
            finished_at=None if run.finished_at is None else run.finished_at.astimezone(UTC),
            status_reason=run.status_reason,
            status_by=run.status_by,
            last_error=run.last_error,
        )


class FanOutCursor(BaseModel):
    """Where a page of fan-outs ends: the last run on it."""

    started_at: AwareDatetime
    rule_version_id: UUID


class FanOutReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class FanOutResumeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: OptionalReason = ""


class FanOutHoldIn(BaseModel):
    """``held`` true sets the hold (a reason of at least ten characters is required), or
    replaces the reason of the one that is set; false releases it, with a reason if you say."""

    model_config = ConfigDict(extra="forbid")

    held: bool
    reason: OptionalReason = ""

    @model_validator(mode="after")
    def _a_hold_says_why(self) -> Self:
        if self.held and len(self.reason) < MIN_REASON_CHARS:
            raise ValueError(f"a hold needs a reason of at least {MIN_REASON_CHARS} characters")
        return self


class FanOutHoldOut(BaseModel):
    """The global hold: while ``held`` no fan-out starts its next batch. ``set_by`` is a user
    id, ``system:applicability-engine`` or ``service:<client>``."""

    held: bool
    reason: str | None
    set_by: str | None
    set_at: datetime | None

    @classmethod
    def from_hold(cls, hold: FanOutHold | None) -> "FanOutHoldOut":
        if hold is None:
            return cls(held=False, reason=None, set_by=None, set_at=None)
        return cls(
            held=True,
            reason=hold.reason,
            set_by=hold.set_by,
            set_at=hold.set_at.astimezone(UTC),
        )
