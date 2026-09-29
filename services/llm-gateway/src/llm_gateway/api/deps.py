"""Request-scoped dependencies: the caller and its tenant, the correlation id, the wired objects.

The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``. Without a token (``header``
mode, or ``dual`` mode without one) every route works as before tokens existed. With a token:

- ``ModelCaller`` (completions and embeddings): a service with the llm:call scope. Users call
  models only through a service.
- ``Operator`` (usage, the routing table and the prompt registry): a user with a regulatory role
  (analyst, reviewer or admin) or a service with llm:call.

Anyone else is a 403 ``auth-forbidden``. ``Tenant`` is optional: regulatory work, such as the
pipeline's extraction, has no tenant, and a tenant only attributes cost. A service names it in
``x-tenant-id`` and needs the tenant:act scope to do so; a user's token names its own, and a
header naming another is a 403 ``auth-tenant-mismatch``. A header value that is not a UUID is a
request validation error (422 problem naming the header). The tenant is bound into the log
context for the rest of the request.
"""

from typing import Annotated

from fastapi import Depends, Request

from domain_kernel.access import REGULATORY_ROLES, Principal, Scope
from domain_kernel.ids import TenantId
from llm_gateway.wiring import GatewayWiring
from py_common.auth.fastapi import require_roles, tenant_scope
from py_common.request_context import correlation_id_of

TENANT_HEADER = (
    "Tenant UUID the call is for, which attributes its cost; empty for regulatory work. A service "
    "names a tenant only with the tenant:act scope, and a user's token already names one."
)


def correlation_id(request: Request) -> str:
    return correlation_id_of(request) or ""


def gateway(request: Request) -> GatewayWiring:
    wiring: GatewayWiring = request.app.state.gateway
    return wiring


Tenant = Annotated[TenantId | None, Depends(tenant_scope(False, description=TENANT_HEADER))]
Correlation = Annotated[str, Depends(correlation_id)]
Gateway = Annotated[GatewayWiring, Depends(gateway)]
ModelCaller = Annotated[Principal, Depends(require_roles(scopes={Scope.LLM_CALL}))]
Operator = Annotated[Principal, Depends(require_roles(REGULATORY_ROLES, scopes={Scope.LLM_CALL}))]
