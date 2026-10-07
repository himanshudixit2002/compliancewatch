"""``GET /v1/identity/entitlements``: what the tenant's plan entitles it to.

A signed-in user reads their own tenant's (a header naming another tenant is a 403). A service
reads a tenant's with the ``entitlements:read`` scope, naming it in ``x-tenant-id``; that scope
is enough without ``tenant:act``, since this read is all it grants (profile checks a new
registration against it).
In header mode the anonymous caller names the tenant in the header, as on the other routes.
Any other caller is refused: a service without the scope (403), and outside header mode a
request without a token (401).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request

from domain_kernel.access import PrincipalKind, Scope
from domain_kernel.ids import TenantId
from identity.api.deps import Wired
from identity.api.schemas import EntitlementsOut
from identity.domain.errors import TenantRequiredError
from py_common.auth.errors import AuthForbiddenError, AuthTokenRequiredError
from py_common.auth.fastapi import (
    TENANT_HEADER_DESCRIPTION,
    CurrentPrincipal,
    authenticator_of,
    resolve_tenant,
)
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/identity", tags=["identity"])


async def entitlements_tenant(
    request: Request,
    principal: CurrentPrincipal,
    x_tenant_id: Annotated[UUID | None, Header(description=TENANT_HEADER_DESCRIPTION)] = None,
) -> TenantId:
    """The tenant whose entitlements are read, for the callers the module names."""
    offered = None if x_tenant_id is None else TenantId(x_tenant_id)
    if principal.kind is PrincipalKind.SERVICE:
        if not principal.has_scope(Scope.ENTITLEMENTS_READ):
            raise AuthForbiddenError(
                f"reading entitlements needs the {Scope.ENTITLEMENTS_READ.value} scope"
            )
        tenant = offered
    elif principal.kind is PrincipalKind.USER:
        tenant = resolve_tenant(principal, offered)
    else:
        if authenticator_of(request).mode != "header":
            raise AuthTokenRequiredError()
        tenant = offered
    if tenant is None:
        raise TenantRequiredError()
    return tenant


EntitlementsTenant = Annotated[TenantId, Depends(entitlements_tenant)]


@router.get(
    "/entitlements",
    summary="What the tenant's plan entitles it to: its registrations and seats",
    responses=problem_responses(401, 403),
)
def read_entitlements(tenant: EntitlementsTenant, wired: Wired) -> EntitlementsOut:
    """The plan of the tenant's current subscription (the newest active or past-due one) times
    its quantity, or the free allowance; the internal tenant has no limits. ``enforced`` says
    whether going over them is refused (the flag identity.plan_limits for the tenant)."""
    return EntitlementsOut.from_entitlements(wired.read_entitlements.run(tenant))
