"""Tenants and their users: sign-up, and what tenant admins do.

``POST /tenants`` creates a business or a CA firm from the provider token of the person signing
up, who becomes its first user with the kind's admin role, and answers the tenant, the user and a
session. It reads no bearer token: the person has no session until the tenant exists.

The user routes need a tenant admin: an owner, a CA admin, or an admin of the internal tenant.
With a verified token the caller's session version is checked against the store, so a revoked
admin is refused at once. In header mode (and dual mode without a token) the tenant header names
the tenant, as on every tenant route; production runs token mode.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from domain_kernel.access import TENANT_ADMIN_ROLES, Role
from domain_kernel.ids import UserId
from identity.api.deps import Tenant, Wired
from identity.api.schemas import (
    CreatedTenantOut,
    InviteIn,
    RolesIn,
    TenantIn,
    UserOut,
    UsersOut,
)
from identity.domain.tenancy import Contact, TenantKind
from py_common.auth.fastapi import CurrentPrincipal, require_roles
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])

TenantAdmin = Depends(require_roles(TENANT_ADMIN_ROLES, Role.ADMIN))
"""An owner, a CA admin or an admin of the internal tenant; a service is refused."""


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


@router.post(
    "/users",
    summary="Invite a user: their account at the identity provider, then the user (tenant admins)",
    status_code=status.HTTP_201_CREATED,
    responses=problem_responses(401, 403, 404, 409, 422, 503),
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
