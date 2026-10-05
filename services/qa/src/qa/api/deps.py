"""Request-scoped dependencies: the caller and its tenant, the wiring, and the question id every
model call of the request is tagged with.

The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``. ``Tenant`` is the tenant a
member of it asks for:

- a user's access token names the tenant, and an ``x-tenant-id`` header naming another is a 403
  ``auth-tenant-mismatch``; the user needs one of the tenant member roles;
- a service names the tenant in ``x-tenant-id`` and needs the tenant:act scope;
- without a token (``header`` mode, or ``dual`` mode without one) the header names the tenant, as
  before tokens existed.

Answers read tenant data (profiles, obligations), so no tenant at all is this service's own 401
``qa-tenant-required``. ``PUBLIC_ROUTE`` is the ``openapi_extra`` of the public API's ask: the
roles that may call it, as ``x-roles``.
"""

from typing import Annotated, Any, Final
from uuid import uuid4

from fastapi import Depends, Request

from domain_kernel.access import TENANT_MEMBER_ROLES, Principal, Role, Scope
from domain_kernel.ids import TenantId
from py_common.auth.fastapi import require_roles, tenant_scope
from py_common.request_context import correlation_id_of
from qa.domain.errors import QaTenantRequiredError
from qa.wiring import Wiring

member = require_roles(TENANT_MEMBER_ROLES, scopes={Scope.TENANT_ACT})
"""A user with a tenant member role or a service with tenant:act; the anonymous principal of
``header`` mode passes."""
tenant_of_request = tenant_scope(True, QaTenantRequiredError)

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


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


def question_id(request: Request) -> str:
    """The request's ``x-request-id`` (or the one the middleware minted)."""
    return correlation_id_of(request) or uuid4().hex


Tenant = Annotated[TenantId, Depends(member_tenant)]
Wired = Annotated[Wiring, Depends(wiring)]
QuestionId = Annotated[str, Depends(question_id)]
