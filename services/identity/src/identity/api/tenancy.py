"""Tenants: sign-up.

``POST /tenants`` creates a business or a CA firm from the provider token of the person signing
up, who becomes its first user with the kind's admin role, and answers the tenant, the user and a
session. It reads no bearer token: the person has no session until the tenant exists.
"""

from fastapi import APIRouter, status

from identity.api.deps import Wired
from identity.api.schemas import CreatedTenantOut, TenantIn
from identity.domain.tenancy import TenantKind
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])


@router.post(
    "/tenants",
    summary="Sign up: create a business or CA firm tenant with its first user and a session",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 403, 409, 422, 503),
)
def create_tenant(body: TenantIn, wired: Wired) -> CreatedTenantOut:
    created = wired.create_tenant.run(
        body.provider_token, TenantKind(body.kind), body.name, display_name=body.display_name
    )
    return CreatedTenantOut.from_created(created)
