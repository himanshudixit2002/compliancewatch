"""Request-scoped dependencies: the caller and its tenant, and the wiring.

The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``. ``Tenant`` is the tenant a
member of it reads obligations for:

- a user's access token names the tenant, and an ``x-tenant-id`` header naming another is a 403
  ``auth-tenant-mismatch``; the user needs one of the tenant member roles;
- a service (the qa service, reading the obligations a question is about) names the tenant in
  ``x-tenant-id`` and needs the tenant:act scope;
- without a token (``header`` mode, or ``dual`` mode without one) the header names the tenant, as
  before tokens existed.

``ExportTenant`` is the tenant whose data is exported
(``py_common.auth.fastapi.data_export_scope``): a user with one of the tenant admin roles (owner,
ca_admin) for their own tenant, a service only with a data:export token bound to that tenant and
addressed to this service, as identity mints one when it assembles the export, or without a token
the header's.

``Writer`` is who changes an obligation: a user with one of the tenant member roles, never a
service, or, without a token, the header's tenant as before. It carries what the use cases record
of the caller: the audit actor (``py_common.audit.audit_actor``: the user's roles, else the
system), the user id a verified token named, and the request's correlation id.

Obligations are tenant data, so no tenant at all is this service's own 401
``obligation-tenant-required``. ``PUBLIC_ROUTE`` is the ``openapi_extra`` of the routes of the
public API: the roles that may call them, as ``x-roles``.
"""

from typing import Annotated, Any, Final

from fastapi import Depends, Request

from domain_kernel.access import (
    TENANT_MEMBER_ROLES,
    Principal,
    Role,
    Scope,
)
from domain_kernel.ids import TenantId
from obligation.application.tracking import Acting
from obligation.domain.errors import ObligationTenantRequiredError
from obligation.wiring import Wiring
from py_common.audit import audit_actor, current_correlation_id
from py_common.auth.fastapi import data_export_scope, require_roles, tenant_scope

SERVICE_NAME: Final = "obligation"

member = require_roles(TENANT_MEMBER_ROLES, scopes={Scope.TENANT_ACT})
"""A user with a tenant member role or a service with tenant:act; the anonymous principal of
``header`` mode passes."""
writer = require_roles(TENANT_MEMBER_ROLES)
"""A user with a tenant member role; a service is refused, and the anonymous principal of
``header`` mode passes."""
tenant_of_request = tenant_scope(True, ObligationTenantRequiredError)

PUBLIC_ROLES: Final = tuple(role.value for role in Role if role in TENANT_MEMBER_ROLES)
"""The roles of a tenant's members, in the kernel's order."""
PUBLIC_ROUTE: Final[dict[str, Any]] = {"x-roles": list(PUBLIC_ROLES)}
"""``openapi_extra`` of a public route every member of the tenant may call."""


async def member_tenant(
    principal: Annotated[Principal, Depends(member)],
    tenant: Annotated[TenantId, Depends(tenant_of_request)],
) -> TenantId:
    """The request's tenant, once the caller is known to be one of its members."""
    return tenant


async def acting_member(
    principal: Annotated[Principal, Depends(writer)],
    tenant: Annotated[TenantId, Depends(tenant_of_request)],
) -> Acting:
    """Who changes an obligation of the request's tenant, once the caller is known to be one of
    its members."""
    return Acting(
        tenant_id=tenant,
        actor=audit_actor(SERVICE_NAME, principal),
        user_id=principal.user_id,
        verified=principal.is_authenticated,
        correlation_id=current_correlation_id(),
    )


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Tenant = Annotated[TenantId, Depends(member_tenant)]
Writer = Annotated[Acting, Depends(acting_member)]
ExportTenant = Annotated[
    TenantId, Depends(data_export_scope(SERVICE_NAME, ObligationTenantRequiredError))
]
Wired = Annotated[Wiring, Depends(wiring)]
