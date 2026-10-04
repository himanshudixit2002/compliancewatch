"""Routes of the applicability-engine service. Business logic lives in application use cases.

Every decision route acts for the request's tenant (``deps.Tenant``): the tenant a user's access
token names, the one a service with tenant:act names in ``x-tenant-id``, or without a token the
header's. Evaluating takes an ``Idempotency-Key``: a retry with the same key and body gets the
first decision back for 24 hours instead of a second one.

The review routes act for the tenant ``x-tenant-id`` names (``deps.ReviewTenant``), for the
regulatory team: an analyst, a reviewer or an admin reads the queue, and a reviewer or an admin
settles an item (``deps.Resolver``).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from applicability_engine.api.deps import Resolver, ReviewTenant, Tenant, Wired, resolved_by
from applicability_engine.api.schemas import (
    DecisionCursor,
    DecisionOut,
    EvaluateIn,
    ResolveIn,
    ReviewItemCursor,
    ReviewItemOut,
)
from applicability_engine.application.evaluate import EvaluateRequest
from applicability_engine.application.queries import DecisionQuery
from applicability_engine.application.review import ResolveRequest, ReviewQuery
from applicability_engine.domain.model import DecisionKey, Trigger
from applicability_engine.domain.review import ReviewItemId, ReviewItemKey, ReviewStatus
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId
from py_common.idempotency.fastapi import IDEMPOTENCY_RESPONSES, IdempotencyKey, run_idempotent
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/applicability-engine", tags=["applicability-engine"])

LIST_SCOPE = "applicability-engine.decisions"
REVIEW_SCOPE = "applicability-engine.review-items"


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "applicability-engine", "status": "pong"}


@router.post(
    "/businesses/{business_id}/decisions",
    summary="Evaluate a published rule version against the business's profile, and store it",
    status_code=status.HTTP_201_CREATED,
    response_model=DecisionOut,
    responses={**problem_responses(401, 403, 404, 409, 422, 503), **IDEMPOTENCY_RESPONSES},
)
def evaluate(
    business_id: UUID, body: EvaluateIn, tenant: Tenant, key: IdempotencyKey, wired: Wired
) -> JSONResponse:
    """Every evaluation stores a new decision and publishes ``applicability.decided``, so this
    is also how a decision is recomputed after the profile changed. A predicate the engine
    cannot decide (free text, an attribute the profile has not set) is unsure, never guessed,
    and an unsure result needs review. 404 when the rulebook has no such rule version or the
    profile service no such business; 409 when the version is not published; 503 when either
    service cannot be read."""

    def produce() -> DecisionOut:
        decision = wired.evaluate.run(
            EvaluateRequest(
                tenant_id=tenant,
                business_id=BusinessId(business_id),
                rule_version_id=RuleVersionId(body.rule_version_id),
                trigger=Trigger.MANUAL,
                fy=None if body.fy is None else FinancialYear.parse(body.fy),
            )
        )
        return DecisionOut.from_decision(decision)

    return run_idempotent(wired.idempotency, tenant, key, status.HTTP_201_CREATED, produce)


@router.get(
    "/businesses/{business_id}/decisions",
    summary="A business's decisions, newest first, a page at a time",
    responses=problem_responses(401, 403, 422),
)
def list_decisions(
    business_id: UUID,
    tenant: Tenant,
    wired: Wired,
    page: Pagination,
    rule_version_id: Annotated[
        UUID | None,
        Query(description="Only the decisions of this rule version; the first is the latest"),
    ] = None,
) -> Page[DecisionOut]:
    after = page.after(LIST_SCOPE, DecisionCursor)
    found = wired.list_decisions.run(
        DecisionQuery(
            tenant_id=tenant,
            business_id=BusinessId(business_id),
            limit=page.limit + 1,
            rule_version_id=None if rule_version_id is None else RuleVersionId(rule_version_id),
            after=None if after is None else DecisionKey(after.decided_at, DecisionId(after.id)),
        )
    )
    items, next_cursor = page_of(
        found,
        page.limit,
        LIST_SCOPE,
        lambda decision: DecisionCursor(
            decided_at=decision.decided_at, id=decision.decision_id.value
        ),
    )
    return Page[DecisionOut](
        items=[DecisionOut.from_decision(decision) for decision in items],
        next_cursor=next_cursor,
    )


@router.get(
    "/decisions/{decision_id}",
    summary="One decision with the outcome of every predicate",
    responses=problem_responses(401, 403, 404, 422),
)
def read_decision(decision_id: UUID, tenant: Tenant, wired: Wired) -> DecisionOut:
    return DecisionOut.from_decision(wired.read_decision.run(tenant, DecisionId(decision_id)))


@router.get(
    "/review-items",
    summary="The tenant's review items, oldest first, a page at a time",
    responses=problem_responses(401, 403, 422),
)
def list_review_items(
    tenant: ReviewTenant,
    wired: Wired,
    page: Pagination,
    item_status: Annotated[
        ReviewStatus | None,
        Query(alias="status", description="Only the items of this status; every item without"),
    ] = None,
) -> Page[ReviewItemOut]:
    """Decisions a person has to settle: a free-text predicate nobody judged, or a judgement
    below the review threshold. A decision unsure only for an attribute the profile has not set
    opens no item. Each item carries the decision under review with every predicate's outcome;
    at most one item of a business and rule version is open."""
    after = page.after(REVIEW_SCOPE, ReviewItemCursor)
    found = wired.list_review_items.run(
        ReviewQuery(
            tenant_id=tenant,
            limit=page.limit + 1,
            status=item_status,
            after=None if after is None else ReviewItemKey(after.opened_at, ReviewItemId(after.id)),
        )
    )
    items, next_cursor = page_of(
        found,
        page.limit,
        REVIEW_SCOPE,
        lambda entry: ReviewItemCursor(opened_at=entry.item.opened_at, id=entry.item.item_id.value),
    )
    return Page[ReviewItemOut](
        items=[ReviewItemOut.from_entry(entry) for entry in items], next_cursor=next_cursor
    )


@router.post(
    "/review-items/{item_id}/resolve",
    summary="Settle an open review item: applies, not_applicable or dismiss, with a note",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def resolve_review_item(
    item_id: UUID, body: ResolveIn, tenant: ReviewTenant, reviewer: Resolver, wired: Wired
) -> ReviewItemOut:
    """applies and not_applicable append a decision with trigger review, the reviewer's result
    and confidence 1, made from the decision under review, and publish applicability.decided;
    the obligation service then makes or closes the obligations. dismiss appends nothing. A
    signed-in reviewer is the one recorded; without a token the body's resolved_by is. 404 when
    the tenant has no such item, 409 when it is already resolved."""
    entry = wired.resolve_review_item.run(
        ResolveRequest(
            tenant_id=tenant,
            item_id=ReviewItemId(item_id),
            resolution=body.resolution,
            resolved_by=resolved_by(reviewer, body.resolved_by),
            note=body.note,
        )
    )
    return ReviewItemOut.from_entry(entry)
