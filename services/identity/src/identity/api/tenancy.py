"""Tenants and their users: sign-up, what tenant admins do, and the membership a service reads.

``POST /tenants`` creates a business or a CA firm from the provider token of the person signing
up, who becomes its first user with the kind's admin role, and answers the tenant, the user and a
session. It reads no bearer token: the person has no session until the tenant exists.

The user routes need a tenant admin: an owner, a CA admin, or an admin of the internal tenant.
With a verified token the caller's session version is checked against the store, so a revoked
admin is refused at once. Outside header mode they need that token: in dual mode a request without
one is a 401, not the anonymous caller other tenant routes still serve, because the users and
roles it would store outlive the switch to token mode. In header mode the tenant header names the
tenant, as on every tenant route, and an anonymous caller grants no admin or regulatory role;
production runs token mode.

``GET /users/{user_id}/membership`` is for a service acting for the tenant (tenant:act, the tenant
in ``x-tenant-id``), such as the obligation service checking an assignee: the user's roles and
status, no contact details. A person's token is refused, and outside header mode so is a request
without a token.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from domain_kernel.access import TENANT_ADMIN_ROLES, Principal, Role, Scope
from domain_kernel.ids import UserId
from identity.api.deps import Tenant, Wired
from identity.api.schemas import (
    CreatedTenantOut,
    InviteIn,
    MembershipOut,
    RolesIn,
    TenantIn,
    UserOut,
    UsersOut,
)
from identity.domain.tenancy import Contact, TenantKind
from py_common.auth.errors import AuthTokenRequiredError
from py_common.auth.fastapi import CurrentPrincipal, authenticator_of, require_roles
from py_common.problems import limit_problem_responses, problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])

admin_roles = require_roles(TENANT_ADMIN_ROLES, Role.ADMIN)


async def tenant_admin(
    request: Request, principal: Annotated[Principal, Depends(admin_roles)]
) -> Principal:
    """An owner, a CA admin or an admin of the internal tenant; a service is refused. Only
    header mode lets the anonymous caller through: in dual mode a request without a token is a
    401, as it is in token mode."""
    if not principal.is_authenticated and authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "Managing users needs a tenant admin's access token as Authorization: Bearer <token>"
        )
    return principal


TenantAdmin = Depends(tenant_admin)
"""The guard of the user routes (``tenant_admin``)."""

acting_services = require_roles(scopes={Scope.TENANT_ACT})


async def acting_service(
    request: Request, principal: Annotated[Principal, Depends(acting_services)]
) -> Principal:
    """A service with tenant:act; a person is refused. Only header mode lets the anonymous
    caller through, as on the user routes."""
    if not principal.is_authenticated and authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "Reading a membership needs a service's access token as Authorization: Bearer <token>"
        )
    return principal


ActingService = Depends(acting_service)
"""The guard of the membership route (``acting_service``)."""


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


@router.get(
    "/users",
    summary="The tenant's users (tenant admins)",
    responses=problem_responses(401, 403, 404),
    dependencies=[TenantAdmin],
)
def list_users(tenant: Tenant, principal: CurrentPrincipal, wired: Wired) -> UsersOut:
    users = wired.list_users.run(tenant, principal)
    return UsersOut(items=[UserOut.from_user(user) for user in users])


@router.get(
    "/users/{user_id}/membership",
    summary="Whether a user belongs to the tenant, with their roles and status (services)",
    responses=problem_responses(401, 403, 404, 422),
    dependencies=[ActingService],
)
def read_membership(user_id: UUID, tenant: Tenant, wired: Wired) -> MembershipOut:
    """For a service acting for the tenant it names in x-tenant-id, with the tenant:act scope:
    the user's roles and whether they may still sign in (status active or disabled), and no
    contact details. 404 when the tenant has no such user, a user of another tenant included,
    or when identity has no such tenant."""
    return MembershipOut.from_user(wired.read_membership.run(tenant, UserId(user_id)))


@router.post(
    "/users",
    summary="Invite a user: their account at the identity provider, then the user (tenant admins)",
    status_code=status.HTTP_201_CREATED,
    # 402: identity-seat-limit-reached, with the plan's limit and the seats used
    responses={**problem_responses(401, 403, 404, 409, 422, 503), **limit_problem_responses()},
    dependencies=[TenantAdmin],
)
def invite_user(
    body: InviteIn, tenant: Tenant, principal: CurrentPrincipal, wired: Wired
) -> UserOut:
    user = wired.invite_user.run(
        tenant,
        principal,
        contact=Contact.of(email=body.email, phone=body.phone),
        roles=body.roles,
        display_name=body.display_name,
    )
    return UserOut.from_user(user)


@router.put(
    "/users/{user_id}/roles",
    summary="Change a user's roles; older sessions of the user are revoked (tenant admins)",
    responses=problem_responses(401, 403, 404, 409, 422),
    dependencies=[TenantAdmin],
)
def change_roles(
    user_id: UUID, body: RolesIn, tenant: Tenant, principal: CurrentPrincipal, wired: Wired
) -> UserOut:
    changed = wired.change_roles.run(tenant, principal, UserId(user_id), body.roles)
    return UserOut.from_user(changed)


@router.post(
    "/users/{user_id}/disable",
    summary="Disable a user; they cannot sign in and their sessions are revoked (tenant admins)",
    responses=problem_responses(401, 403, 404, 409),
    dependencies=[TenantAdmin],
)
def disable_user(
    user_id: UUID, tenant: Tenant, principal: CurrentPrincipal, wired: Wired
) -> UserOut:
    return UserOut.from_user(wired.disable_user.run(tenant, principal, UserId(user_id)))
