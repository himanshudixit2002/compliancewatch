"""Request-scoped dependencies: the caller and its tenant, the wiring and the clock.

The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``. ``Tenant`` is the tenant a
member of it acts for:

- a user's access token names the tenant, and an ``x-tenant-id`` header naming another is a 403
  ``auth-tenant-mismatch``; the user needs one of the tenant member roles;
- a service names the tenant in ``x-tenant-id`` and needs the tenant:act scope;
- without a token (``header`` mode, or ``dual`` mode without one) the header names the tenant, as
  before tokens existed.

Profiles are tenant data, so no tenant at all is this service's own 401 ``tenant-required``.
``Caller`` is the principal, from which the routes take who changed a value.
"""

from datetime import datetime
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import Depends, Request

from domain_kernel.access import TENANT_MEMBER_ROLES, Principal, Role, Scope
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId, UserId
from profile_service.domain.errors import TenantRequiredError
from profile_service.wiring import Wiring
from py_common.auth.fastapi import CurrentPrincipal, require_roles, tenant_scope

member = require_roles(TENANT_MEMBER_ROLES, scopes={Scope.TENANT_ACT})
"""A user with a tenant member role or a service with tenant:act; the anonymous principal of
``header`` mode passes."""
tenant_of_request = tenant_scope(True, TenantRequiredError)


async def member_tenant(
    principal: Annotated[Principal, Depends(member)],
    tenant: Annotated[TenantId, Depends(tenant_of_request)],
) -> TenantId:
    """The request's tenant, once the caller is known to be one of its members."""
    return tenant


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


def changed_by(principal: Principal, offered: UUID | None) -> UserId | None:
    """Who changed a value: the user a verified token names (None for a service), and the body's
    ``changed_by`` only when no token names the caller."""
    if principal.is_authenticated:
        return principal.user_id
    return None if offered is None else UserId(offered)


PUBLIC_ROLES: Final = tuple(role.value for role in Role if role in TENANT_MEMBER_ROLES)
"""The roles of a tenant's members, in the kernel's order; each public route lists who may call
it as ``x-roles``, and ``member`` enforces them for a caller a token names."""
PUBLIC_ROUTE: Final[dict[str, Any]] = {"x-roles": list(PUBLIC_ROLES)}
"""``openapi_extra`` of a public route every member of the tenant may call."""

Tenant = Annotated[TenantId, Depends(member_tenant)]
Caller = CurrentPrincipal
Wired = Annotated[Wiring, Depends(wiring)]


def clock() -> datetime:
    """The current time; tests override this dependency to fix it."""
    return utc_now()


Now = Annotated[datetime, Depends(clock)]
