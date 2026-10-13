"""Error reports: the errors tenants' members reported in their obligations, masked, waiting
for the regulatory team's decision, and the decisions.

The queue is read with a regulatory role a token names (``ReviewRead``; open without a token in
header and dual mode, as the other review queues). An analyst, reviewer or admin decides a report
(``AnalystWrite``); without a bearer, in header and dual mode, the review token opens the write
and the body names the actor, and a signed-in user is the actor whatever the body says.
"""

from datetime import datetime
from typing import Annotated, Final, Self
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from domain_kernel.ids import RuleVersionId
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses
from rulebook.api.deps import AnalystWrite, ReviewRead, Wired, actor_of
from rulebook.domain.error_reports import (
    MAX_NOTES_CHARS,
    ErrorCategory,
    ErrorOutcome,
    ErrorReview,
    ErrorReviewGroup,
    ErrorReviewKey,
    ErrorReviewStatus,
)

router = APIRouter(tags=["review"])

REPORTS_SCOPE: Final = "rulebook.error-reports"


class ErrorReviewOut(BaseModel):
    """One report as the rulebook holds it: ``description`` is the reporter's account as the
    obligation service masked it (empty once the tenant was erased, with ``tenant_id`` null);
    ``status`` is ``open`` until decided, then ``confirmed`` with
    ``correcting_rule_version_id`` or ``rejected``, with the decision's notes."""

    report_id: UUID
    tenant_id: UUID | None
    obligation_id: UUID
    rule_version_id: UUID
    category: ErrorCategory
    description: str
    received_at: datetime
    status: ErrorReviewStatus
    decided_by: UUID | None
    decided_at: datetime | None
    notes: str
    correcting_rule_version_id: UUID | None

    @classmethod
    def from_review(cls, review: ErrorReview) -> Self:
        return cls(
            report_id=review.report_id,
            tenant_id=None if review.tenant_id is None else review.tenant_id.value,
            obligation_id=review.obligation_id.value,
            rule_version_id=review.rule_version_id.value,
            category=review.category,
            description=review.description_masked,
            received_at=review.received_at,
            status=review.status,
            decided_by=None if review.decided_by is None else review.decided_by.value,
            decided_at=review.decided_at,
            notes=review.notes,
            correcting_rule_version_id=None
            if review.correcting_rule_version_id is None
            else review.correcting_rule_version_id.value,
        )


class ErrorReviewGroupOut(BaseModel):
    """The open reports about one rule version: how many and since when, with the version's
    rule key, number and title (null or empty for a version the rulebook no longer lists)."""

    rule_version_id: UUID
    rule_key: str | None
    version: int | None
    title: str
    open: int
    oldest_received_at: datetime

    @classmethod
    def from_group(cls, group: ErrorReviewGroup) -> Self:
        return cls(
            rule_version_id=group.rule_version_id.value,
            rule_key=group.rule_key,
            version=group.version,
            title=group.title,
            open=group.open_count,
            oldest_received_at=group.oldest_received_at,
        )


class ErrorReviewPageOut(Page[ErrorReviewOut]):
    """One page of the queue, and the open reports counted per rule version (the whole queue,
    whatever the page's filters)."""

    groups: list[ErrorReviewGroupOut]


class ErrorReviewCursor(BaseModel):
    """The keyset of the queue: the rule version, when the report arrived and its review id."""

    v: UUID
    r: AwareDatetime
    i: UUID

    @classmethod
    def of(cls, review: ErrorReview) -> Self:
        return cls(v=review.rule_version_id.value, r=review.received_at, i=review.review_id)

    def key(self) -> ErrorReviewKey:
        return ErrorReviewKey(RuleVersionId(self.v), self.r, self.i)


class ErrorDecisionIn(BaseModel):
    """``confirmed`` names ``correcting_rule_version_id``, a version with a corrects relation to
    the reported one; ``rejected`` says why in ``notes``."""

    model_config = ConfigDict(extra="forbid")

    actor_id: UUID = Field(
        description="The analyst deciding; a signed-in user's token overrides it"
    )
    decision: ErrorOutcome
    notes: str = Field(default="", max_length=MAX_NOTES_CHARS)
    correcting_rule_version_id: UUID | None = Field(
        default=None, description="For a confirmed report, the version that corrects it"
    )


@router.get(
    "/error-reports",
    summary="The error reports tenants' members made, by rule version, oldest first",
    dependencies=[ReviewRead],
    responses=problem_responses(401, 403, 422),
)
def list_error_reports(
    page: Pagination,
    wired: Wired,
    status: Annotated[
        ErrorReviewStatus | None,
        Query(description="Only reports in this status; open by default"),
    ] = ErrorReviewStatus.OPEN,
    rule_version_id: Annotated[
        UUID | None, Query(description="Only reports about this rule version")
    ] = None,
) -> ErrorReviewPageOut:
    """Each report with its masked description and, once decided, the decision; ``groups``
    counts the open reports per rule version, whatever the page shows."""
    scope = f"{REPORTS_SCOPE}.{status or 'any'}.{rule_version_id or 'any'}"
    after = page.after(scope, ErrorReviewCursor)
    version = None if rule_version_id is None else RuleVersionId(rule_version_id)
    found = wired.list_error_reviews.run(
        status=status,
        rule_version_id=version,
        after=None if after is None else after.key(),
        limit=page.limit + 1,
    )
    kept, cursor = page_of(found, page.limit, scope, ErrorReviewCursor.of)
    return ErrorReviewPageOut(
        items=[ErrorReviewOut.from_review(review) for review in kept],
        next_cursor=cursor,
        groups=[
            ErrorReviewGroupOut.from_group(group) for group in wired.list_error_reviews.groups()
        ],
    )


@router.post(
    "/error-reports/{report_id}/decision",
    summary="Confirm an error report with its correcting version, or reject it",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def decide_error_report(
    report_id: UUID, body: ErrorDecisionIn, analyst: AnalystWrite, wired: Wired
) -> ErrorReviewOut:
    """Once per report (409 rulebook-error-review-closed). confirmed needs
    correcting_rule_version_id, a stored version with a corrects relation to the reported one
    (422 rulebook-correcting-version-required; 404 rulebook-rule-version-not-found for one the
    rulebook does not hold); publishing it replaces the reported version and reaches the affected
    businesses through the rule events. The decision goes back to the obligation service as
    error_report.decided and is audited as error_report_review.decided. 404
    rulebook-error-review-not-found when no such report reached the rulebook."""
    decided = wired.decide_error_review.run(
        report_id,
        body.decision,
        by=actor_of(analyst, body.actor_id),
        notes=body.notes,
        correcting_rule_version_id=None
        if body.correcting_rule_version_id is None
        else RuleVersionId(body.correcting_rule_version_id),
    )
    return ErrorReviewOut.from_review(decided)
