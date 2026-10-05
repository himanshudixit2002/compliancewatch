"""Request-scoped dependencies: the caller and its tenant, and the wiring.

The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``. ``Tenant`` is the tenant a
member of it reads and computes decisions for:

- a user's access token names the tenant, and an ``x-tenant-id`` header naming another is a 403
  ``auth-tenant-mismatch``; the user needs one of the tenant member roles;
- a service names the tenant in ``x-tenant-id`` and needs the tenant:act scope;
- without a token (``header`` mode, or ``dual`` mode without one) the header names the tenant, as
  before tokens existed.

Decisions are tenant data, so no tenant at all is this service's own 401
``applicability-tenant-required``.

The review queue is the regulatory team's work, the way the rulebook's review queues are, and
its items are tenant data. ``ReviewTenant`` is the tenant whose queue a request reads or
settles, always named in ``x-tenant-id`` (401 ``applicability-tenant-required`` without it):

- a user a token names needs a regulatory role (analyst, reviewer or admin). Those roles exist
  only in the internal tenant, whose people review the decisions of every tenant, so on these two
  routes alone the header names the tenant reviewed rather than the user's own; any other user
  is a 403 ``auth-forbidden``;
- a service is a 403: settling a review is a person's judgement;
- without a token the header names the tenant, as on every other route.

``Resolver`` guards a resolution, which records who settled the item: a reviewer or an admin a
token names (an analyst is a 403). In ``header`` mode the anonymous caller passes and the body
names the reviewer; in ``dual`` mode a request without a token is a 401, so no resolution is
stored without a verified person once tokens are read at all.

The fan-outs run over every tenant and belong to none, so their routes name no tenant.
``FanOutReader`` guards the reads the way the review queue's are guarded: a regulatory role
(analyst, reviewer or admin) a token names, the anonymous caller without a token, and a 403 for
anyone else and for services. ``FanOutAdmin`` guards the controls (pause, resume, cancel, the
hold) the way a resolution is: an admin a token names; the anonymous caller only in ``header``
mode, and a 401 without a token in ``dual`` mode.
"""

from collections.abc import AsyncIterator
from typing import Annotated, Final
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request

from applicability_engine.domain.errors import ApplicabilityTenantRequiredError
from applicability_engine.wiring import Wiring
from domain_kernel.access import (
    REGULATORY_ROLES,
    TENANT_MEMBER_ROLES,
    Principal,
    PrincipalKind,
    Role,
    Scope,
)
from domain_kernel.ids import TenantId, UserId
from py_common.auth.context import TENANT_FIELD
from py_common.auth.errors import AuthForbiddenError, AuthTokenRequiredError
from py_common.auth.fastapi import (
    CurrentPrincipal,
    authenticator_of,
    require_roles,
    tenant_scope,
)

RESOLVER_ROLES: Final = frozenset({Role.REVIEWER, Role.ADMIN})
FAN_OUT_ADMIN_ROLES: Final = frozenset({Role.ADMIN})
REVIEW_TENANT_DESCRIPTION: Final = (
    "The tenant whose review items to read or settle. A regulatory user's token names the "
    "internal tenant, so on the review routes the header names the tenant reviewed."
)

member = require_roles(TENANT_MEMBER_ROLES, scopes={Scope.TENANT_ACT})
"""A user with a tenant member role or a service with tenant:act; the anonymous principal of
``header`` mode passes."""
tenant_of_request = tenant_scope(True, ApplicabilityTenantRequiredError)


async def member_tenant(
    principal: Annotated[Principal, Depends(member)],
    tenant: Annotated[TenantId, Depends(tenant_of_request)],
) -> TenantId:
    """The request's tenant, once the caller is known to be one of its members."""
    return tenant


async def review_tenant(
    principal: CurrentPrincipal,
    x_tenant_id: Annotated[UUID | None, Header(description=REVIEW_TENANT_DESCRIPTION)] = None,
) -> AsyncIterator[TenantId]:
    """The tenant whose review queue the request reads or settles (see the module docstring),
    bound into the log context like every request's tenant."""
    if principal.kind is PrincipalKind.SERVICE:
        raise AuthForbiddenError("review items are settled by people; a service may not read them")
    if principal.kind is PrincipalKind.USER and not principal.has_role(*REGULATORY_ROLES):
        names = ", ".join(sorted(role.value for role in REGULATORY_ROLES))
        raise AuthForbiddenError(f"this request needs one of: {names}")
    if x_tenant_id is None:
        raise ApplicabilityTenantRequiredError()
    tenant = TenantId(x_tenant_id)
    structlog.contextvars.bind_contextvars(**{TENANT_FIELD: str(tenant)})
    try:
        yield tenant
    finally:
        structlog.contextvars.unbind_contextvars(TENANT_FIELD)


async def resolver(request: Request, principal: CurrentPrincipal) -> Principal:
    """A reviewer or an admin a token names; the anonymous caller in ``header`` mode only."""
    if principal.is_authenticated:
        if principal.kind is PrincipalKind.USER and principal.has_role(*RESOLVER_ROLES):
            return principal
        names = ", ".join(sorted(role.value for role in RESOLVER_ROLES))
        raise AuthForbiddenError(f"this request needs one of: {names}")
    if authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "Settling a review item needs a reviewer's access token as Authorization: Bearer "
            "<token>"
        )
    return principal


async def fan_out_reader(principal: CurrentPrincipal) -> Principal:
    """A regulatory user a token names, or the anonymous caller; services and tenant members are
    a 403."""
    if principal.kind is PrincipalKind.SERVICE:
        raise AuthForbiddenError("fan-outs are read by the regulatory team, not by a service")
    if principal.kind is PrincipalKind.USER and not principal.has_role(*REGULATORY_ROLES):
        names = ", ".join(sorted(role.value for role in REGULATORY_ROLES))
        raise AuthForbiddenError(f"this request needs one of: {names}")
    return principal


async def fan_out_admin(request: Request, principal: CurrentPrincipal) -> Principal:
    """An admin a token names; the anonymous caller in ``header`` mode only."""
    if principal.is_authenticated:
        if principal.kind is PrincipalKind.USER and principal.has_role(*FAN_OUT_ADMIN_ROLES):
            return principal
        names = ", ".join(sorted(role.value for role in FAN_OUT_ADMIN_ROLES))
        raise AuthForbiddenError(f"this request needs one of: {names}")
    if authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "Controlling a fan-out needs an admin's access token as Authorization: Bearer <token>"
        )
    return principal


def resolved_by(principal: Principal, offered: UUID) -> UserId:
    """Who settled the item: the user a verified token names, else the body's
    ``resolved_by``."""
    user = principal.user_id
    return user if user is not None else UserId(offered)


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Tenant = Annotated[TenantId, Depends(member_tenant)]
ReviewTenant = Annotated[TenantId, Depends(review_tenant)]
Resolver = Annotated[Principal, Depends(resolver)]
FanOutReader = Annotated[Principal, Depends(fan_out_reader)]
FanOutAdmin = Annotated[Principal, Depends(fan_out_admin)]
Wired = Annotated[Wiring, Depends(wiring)]
