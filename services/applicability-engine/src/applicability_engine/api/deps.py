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
"""

from typing import Annotated

from fastapi import Depends, Request

from applicability_engine.domain.errors import ApplicabilityTenantRequiredError
from applicability_engine.wiring import Wiring
from domain_kernel.access import TENANT_MEMBER_ROLES, Principal, Scope
from domain_kernel.ids import TenantId
from py_common.auth.fastapi import require_roles, tenant_scope

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


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Tenant = Annotated[TenantId, Depends(member_tenant)]
Wired = Annotated[Wiring, Depends(wiring)]
