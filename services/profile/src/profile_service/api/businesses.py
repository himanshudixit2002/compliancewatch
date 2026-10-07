"""The business API: ``/v1/businesses``, part of the public API (tag ``public``).

A business is a legal entity with its GSTIN registrations, and its id is the entity's node id.
Creating routes take an ``Idempotency-Key``: a retry with the same key and body gets the first
response back for 24 hours. Every route lists the roles that may call it as ``x-roles``, which a
caller an access token names must hold, and a signed-in user's changes are recorded as theirs.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from domain_kernel.identifiers import Gstin, Pan
from domain_kernel.ids import BusinessId
from profile_service.api.business_schemas import (
    BusinessCreatedOut,
    BusinessIn,
    BusinessOut,
    BusinessPatchIn,
    BusinessSummaryOut,
    OnboardingOut,
    RegistrationAddIn,
    RegistrationCreatedOut,
)
from profile_service.api.deps import PUBLIC_ROUTE, Caller, Tenant, Wired
from profile_service.domain.errors import ProfileNodeNotFoundError
from py_common.idempotency.fastapi import IDEMPOTENCY_RESPONSES, IdempotencyKey, run_idempotent
from py_common.pagination import InvalidCursorError, Page, Pagination, page_of
from py_common.problems import limit_problem_responses, problem_responses

router = APIRouter(prefix="/v1/businesses", tags=["public", "businesses"])

LIST_SCOPE = "profile.businesses"
READ_PROBLEMS = problem_responses(401, 403, 404, 422)
REGISTRATION_PROBLEMS = {**problem_responses(503), **limit_problem_responses()}
"""402: a GSTIN registration past the tenant's plan (profile-plan-limit-reached), with the
plan's ``limit`` and the registrations ``used``; 503: identity refused profile's request for the
limits (profile-entitlements-misconfigured)."""
CREATE_PROBLEMS = {
    **problem_responses(401, 403, 422),
    **REGISTRATION_PROBLEMS,
    **IDEMPOTENCY_RESPONSES,
}


class BusinessCursor(BaseModel):
    """Where a page of businesses ends: the last business on it. The next page starts after
    that business's (name, id), read again, so the cursor stays short whatever the name."""

    id: UUID


@router.post(
    "",
    summary="Create a business from its GSTIN, or from its PAN alone",
    status_code=status.HTTP_201_CREATED,
    response_model=BusinessCreatedOut,
    responses=CREATE_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
def create_business(
    body: BusinessIn, tenant: Tenant, key: IdempotencyKey, caller: Caller, wired: Wired
) -> JSONResponse:
    """A GSTIN makes the business from the PAN inside it and pre-fills the registration from the
    GSTIN lookup; a PAN alone makes the business with no registration. The answers are stored
    with it, and the first onboarding question comes back. A business the tenant already has
    (the same PAN) is answered with ``created`` false."""

    def produce() -> BusinessCreatedOut:
        created = wired.create_business.run(
            tenant,
            name=body.name,
            pan=None if body.pan is None else Pan.parse(body.pan),
            gstin=None if body.gstin is None else Gstin.parse(body.gstin),
            registration_name=body.registration_name,
            answers=[answer.answer() for answer in body.answers],
            by=caller.user_id,
        )
        return BusinessCreatedOut.from_created(created, wired.ontology, wired.wording)

    return run_idempotent(wired.idempotency, tenant, key, status.HTTP_201_CREATED, produce)


@router.get(
    "",
    summary="The tenant's businesses by name, a page at a time",
    responses=problem_responses(401, 403, 422),
    openapi_extra=PUBLIC_ROUTE,
)
def list_businesses(
    tenant: Tenant,
    wired: Wired,
    page: Pagination,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            description="Keeps the businesses whose name, PAN or GSTIN contains this, any case",
        ),
    ] = None,
) -> Page[BusinessSummaryOut]:
    after = page.after(LIST_SCOPE, BusinessCursor)
    try:
        found = wired.list_businesses.run(
            tenant,
            after=None if after is None else BusinessId(after.id),
            limit=page.limit + 1,
            query=q or "",
        )
    except ProfileNodeNotFoundError as exc:
        raise InvalidCursorError(
            "The cursor is invalid: it names no business of this tenant."
        ) from exc
    items, next_cursor = page_of(
        found, page.limit, LIST_SCOPE, lambda business: BusinessCursor(id=business.id.value)
    )
    return Page[BusinessSummaryOut](
        items=[BusinessSummaryOut.from_business(business) for business in items],
        next_cursor=next_cursor,
    )


@router.get(
    "/{business_id}",
    summary="One business with its registrations and stored values",
    responses=READ_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
def read_business(business_id: UUID, tenant: Tenant, wired: Wired) -> BusinessOut:
    return BusinessOut.from_business(wired.read_business.run(tenant, BusinessId(business_id)))


@router.patch(
    "/{business_id}",
    summary="Store answers across the business and its registrations, or rename it",
    responses=READ_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
def update_business(
    business_id: UUID, body: BusinessPatchIn, tenant: Tenant, caller: Caller, wired: Wired
) -> BusinessOut:
    """All or nothing: one value the ontology refuses stores none of the changes. Every node
    that changed publishes ``profile.updated``, which recomputes the business's obligations."""
    business = wired.update_business.run(
        tenant,
        BusinessId(business_id),
        answers=[change.answer() for change in body.changes],
        name=body.name,
        by=caller.user_id,
    )
    return BusinessOut.from_business(business)


@router.get(
    "/{business_id}/onboarding",
    summary="The next onboarding question with its wording and options, and the progress",
    responses=READ_PROBLEMS,
    openapi_extra=PUBLIC_ROUTE,
)
def onboarding(business_id: UUID, tenant: Tenant, wired: Wired) -> OnboardingOut:
    checklist = wired.onboarding.run(tenant, BusinessId(business_id))
    return OnboardingOut.from_checklist(
        BusinessId(business_id), checklist, wired.ontology, wired.wording
    )


@router.post(
    "/{business_id}/registrations",
    summary="Add a GSTIN registration to a business and pre-fill it",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistrationCreatedOut,
    responses={**READ_PROBLEMS, **REGISTRATION_PROBLEMS, **IDEMPOTENCY_RESPONSES},
    openapi_extra=PUBLIC_ROUTE,
)
def add_registration(
    business_id: UUID,
    body: RegistrationAddIn,
    tenant: Tenant,
    key: IdempotencyKey,
    caller: Caller,
    wired: Wired,
) -> JSONResponse:
    def produce() -> RegistrationCreatedOut:
        added = wired.add_registration.run(
            tenant,
            BusinessId(business_id),
            Gstin.parse(body.gstin),
            name=body.name,
            by=caller.user_id,
        )
        return RegistrationCreatedOut.from_added(added)

    return run_idempotent(wired.idempotency, tenant, key, status.HTTP_201_CREATED, produce)
