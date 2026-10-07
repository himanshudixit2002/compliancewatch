"""Routes of the applicability-engine service. Business logic lives in application use cases.

Every decision route acts for the request's tenant (``deps.Tenant``): the tenant a user's access
token names, the one a service with tenant:act names in ``x-tenant-id``, or without a token the
header's. Evaluating takes an ``Idempotency-Key``: a retry with the same key and body gets the
first decision back for 24 hours instead of a second one.

The review routes act for the tenant ``x-tenant-id`` names (``deps.ReviewTenant``), for the
regulatory team: an analyst, a reviewer or an admin reads the queue, and a reviewer or an admin
settles an item (``deps.Resolver``). A resolution is audited: the reviewer a token names is the
actor (``py_common.audit.audit_actor``), else the system, with the request's correlation id.

The fan-out routes name no tenant: a fan-out runs over every tenant. The regulatory team reads the
runs and the global hold (``deps.FanOutReader``); an admin pauses, resumes and cancels a run and
sets and releases the hold (``deps.FanOutAdmin``). Every control is audited the same way, of no
tenant, and then signals the run's workflow.

The data export acts for the request's tenant too, for its owner or CA admin or for identity's
service token with data:export (``deps.ExportTenant``): every decision and review item of the
tenant, for identity to put in the tenant's export.

A dry run names no tenant either, unless its scope does: an admin (``deps.DryRunAdmin``) asks
what a version or a specification would decide for the directory's businesses, and only its
audit entry is written.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query, status
from fastapi.responses import JSONResponse

from applicability_engine import SERVICE_NAME
from applicability_engine.api.deps import (
    DryRunAdmin,
    ExportTenant,
    FanOutAdmin,
    FanOutReader,
    Resolver,
    ReviewTenant,
    Tenant,
    Wired,
    resolved_by,
)
from applicability_engine.api.schemas import (
    DataExportOut,
    DecisionCursor,
    DecisionOut,
    DryRunIn,
    DryRunOut,
    EvaluateIn,
    FanOutCursor,
    FanOutHoldIn,
    FanOutHoldOut,
    FanOutReasonIn,
    FanOutResumeIn,
    FanOutRunOut,
    ResolveIn,
    ReviewItemCursor,
    ReviewItemOut,
)
from applicability_engine.application.dry_run import DryRunRequest
from applicability_engine.application.evaluate import EvaluateRequest
from applicability_engine.application.fanout import FanOutControl, FanOutQuery, HoldControl
from applicability_engine.application.queries import DecisionQuery
from applicability_engine.application.review import ResolveRequest, ReviewQuery
from applicability_engine.domain.fanout import FanOutRunKey
from applicability_engine.domain.model import DecisionKey, Trigger
from applicability_engine.domain.review import ReviewItemId, ReviewItemKey, ReviewStatus
from domain_kernel.access import Principal
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.predicates import specification_from_mapping
from py_common.audit import audit_actor, current_correlation_id
from py_common.idempotency.fastapi import IDEMPOTENCY_RESPONSES, IdempotencyKey, run_idempotent
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/applicability-engine", tags=["applicability-engine"])

LIST_SCOPE = "applicability-engine.decisions"
REVIEW_SCOPE = "applicability-engine.review-items"
FAN_OUT_SCOPE = "applicability-engine.fan-outs"


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
    "/data-export",
    summary="Every decision and review item of the tenant, for its data export",
    responses=problem_responses(401, 403),
)
def export_data(tenant: ExportTenant, wired: Wired) -> DataExportOut:
    """The engine's part of the tenant's data export, which identity assembles: section
    decisions, every decision of the tenant (superseded ones included) with each predicate's
    outcome, and section review_items, the review queue's items, open and resolved; each oldest
    first, then by id, and present even when empty. Nothing of another tenant, and nothing the
    engine keeps across tenants (the fan-outs, the hold, the business directory)."""
    return DataExportOut.from_export(wired.export_data.run(tenant))


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
    signed-in reviewer is the one recorded; without a token the body's resolved_by is. Every
    resolution writes an audit entry, applicability.review.resolve, with the note as its reason.
    404 when the tenant has no such item, 409 when it is already resolved."""
    entry = wired.resolve_review_item.run(
        ResolveRequest(
            tenant_id=tenant,
            item_id=ReviewItemId(item_id),
            resolution=body.resolution,
            resolved_by=resolved_by(reviewer, body.resolved_by),
            note=body.note,
            actor=audit_actor(SERVICE_NAME, reviewer),
            correlation_id=current_correlation_id(),
        )
    )
    return ReviewItemOut.from_entry(entry)


@router.get(
    "/fan-outs",
    summary="Every rule version's fan-out, newest first, a page at a time",
    responses=problem_responses(401, 403, 422),
)
def list_fan_outs(reader: FanOutReader, wired: Wired, page: Pagination) -> Page[FanOutRunOut]:
    """One fan-out per published rule version: the engine decides the version for every
    business of its level in the business directory, in batches of 1,000, behind the global
    hold. Newest first (started_at, then rule version id)."""
    after = page.after(FAN_OUT_SCOPE, FanOutCursor)
    found = wired.list_fan_outs.run(
        FanOutQuery(
            limit=page.limit + 1,
            after=None
            if after is None
            else FanOutRunKey(after.started_at, RuleVersionId(after.rule_version_id)),
        )
    )
    items, next_cursor = page_of(
        found,
        page.limit,
        FAN_OUT_SCOPE,
        lambda run: FanOutCursor(
            started_at=run.started_at, rule_version_id=run.rule_version_id.value
        ),
    )
    return Page[FanOutRunOut](
        items=[FanOutRunOut.from_run(run) for run in items], next_cursor=next_cursor
    )


@router.get(
    "/fan-outs/{rule_version_id}",
    summary="One rule version's fan-out: its status, counters and last change",
    responses=problem_responses(401, 403, 404, 422),
)
def read_fan_out(rule_version_id: UUID, reader: FanOutReader, wired: Wired) -> FanOutRunOut:
    return FanOutRunOut.from_run(wired.read_fan_out.run(RuleVersionId(rule_version_id)))


def _control(principal: Principal, rule_version_id: UUID, reason: str) -> FanOutControl:
    return FanOutControl(
        rule_version_id=RuleVersionId(rule_version_id),
        actor=audit_actor(SERVICE_NAME, principal),
        reason=reason,
        correlation_id=current_correlation_id(),
    )


@router.post(
    "/fan-outs/{rule_version_id}/pause",
    summary="Pause a running or held fan-out at its next batch boundary",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def pause_fan_out(
    rule_version_id: UUID, body: FanOutReasonIn, admin: FanOutAdmin, wired: Wired
) -> FanOutRunOut:
    """The run stops at its next batch boundary and waits until an admin resumes it; the global
    hold's release does not. Audited as applicability.fanout.pause with the reason. 404 when the
    version has no fan-out, 409 when it is not running or held."""
    run = wired.pause_fan_out.run(_control(admin, rule_version_id, body.reason))
    return FanOutRunOut.from_run(run)


@router.post(
    "/fan-outs/{rule_version_id}/resume",
    summary="Resume a paused fan-out",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def resume_fan_out(
    rule_version_id: UUID,
    admin: FanOutAdmin,
    wired: Wired,
    body: Annotated[FanOutResumeIn | None, Body()] = None,
) -> FanOutRunOut:
    """The run decides its next batch at once; while the global hold is set it is held again
    instead. Resuming a run that paused itself on flips turns the flip check off for the rest of
    the run. Audited as applicability.fanout.resume. 404 when the version has no fan-out, 409
    when it is not paused."""
    reason = "" if body is None else body.reason
    run = wired.resume_fan_out.run(_control(admin, rule_version_id, reason))
    return FanOutRunOut.from_run(run)


@router.post(
    "/fan-outs/{rule_version_id}/cancel",
    summary="Cancel a fan-out that has not finished; its decisions stay",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def cancel_fan_out(
    rule_version_id: UUID, body: FanOutReasonIn, admin: FanOutAdmin, wired: Wired
) -> FanOutRunOut:
    """The run stops at its next batch boundary for good. To take back what it decided, withdraw
    the rule version in the rulebook. Audited as applicability.fanout.cancel with the reason. 404
    when the version has no fan-out, 409 when it has finished."""
    run = wired.cancel_fan_out.run(_control(admin, rule_version_id, body.reason))
    return FanOutRunOut.from_run(run)


@router.get(
    "/fan-out-hold",
    summary="The global fan-out hold",
    responses=problem_responses(401, 403),
)
def read_fan_out_hold(reader: FanOutReader, wired: Wired) -> FanOutHoldOut:
    return FanOutHoldOut.from_hold(wired.read_hold.run())


@router.put(
    "/fan-out-hold",
    summary="Set or release the global fan-out hold",
    responses=problem_responses(401, 403, 422),
)
def put_fan_out_hold(body: FanOutHoldIn, admin: FanOutAdmin, wired: Wired) -> FanOutHoldOut:
    """held true stops every fan-out at its next batch boundary (held) until the hold is
    released; a reason of at least ten characters is required, and setting it again replaces
    the reason. held false releases it, and every run it held carries on by itself; a paused run
    stays paused. Audited as applicability.fanout.hold or applicability.fanout.release, of no
    tenant; releasing a hold that is not set changes nothing."""
    control = HoldControl(
        actor=audit_actor(SERVICE_NAME, admin),
        reason=body.reason,
        correlation_id=current_correlation_id(),
    )
    if body.held:
        return FanOutHoldOut.from_hold(wired.set_hold.run(control))
    wired.release_hold.run(control)
    return FanOutHoldOut.from_hold(None)


@router.post(
    "/dry-runs",
    summary="What a version or a specification would decide for the directory; stores nothing",
    responses=problem_responses(401, 403, 404, 422, 503),
)
def dry_run(body: DryRunIn, admin: DryRunAdmin, wired: Wired) -> DryRunOut:
    """Evaluates a rule version in any status (a draft, one under review or approved, or a
    published one), or a specification no version holds yet, the way a fan-out does: against
    every business of the level the business directory lists, of one tenant when the scope
    names one, for the current financial year in India. It answers the counts by result, the
    counts by the attribute that decided each result, and up to ``sample_size`` decisions, a
    result at a time. Nothing is stored and no event is published; the only write is the audit
    entry applicability.dry_run, with the actor and the counts. 404 when the rulebook has no such
    version; 422 for a malformed specification, a level that is not the version's, or a scope
    wider than CW_APPLICABILITY_DRY_RUN_MAX businesses (2,000 by default; name a tenant); 503 when
    the rulebook or the profile service cannot be read."""
    scope = body.scope
    report = wired.dry_run.run(
        DryRunRequest(
            actor=audit_actor(SERVICE_NAME, admin),
            rule_version_id=None
            if body.rule_version_id is None
            else RuleVersionId(body.rule_version_id),
            specification=None
            if body.specification is None
            else specification_from_mapping(body.specification),
            level=scope.level,
            tenant_id=None if scope.tenant_id is None else TenantId(scope.tenant_id),
            sample_size=scope.sample_size,
            correlation_id=current_correlation_id(),
        )
    )
    return DryRunOut.from_report(report)
