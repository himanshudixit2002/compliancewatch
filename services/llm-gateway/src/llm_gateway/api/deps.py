"""Request-scoped dependencies: tenant from the header, correlation id, the wired objects."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request

from domain_kernel.ids import TenantId
from llm_gateway.wiring import GatewayWiring
from py_common.request_context import correlation_id_of


async def tenant_id_from_header(
    x_tenant_id: Annotated[
        UUID | None,
        Header(description="Tenant UUID; optional until the identity service issues tokens"),
    ] = None,
) -> AsyncIterator[TenantId | None]:
    """The tenant is an optional ``x-tenant-id`` header for now.

    A value that is not a UUID is a request validation error (422 problem naming the header).
    The id is bound into the log context for the rest of the request; ``async`` so the binding
    happens in the request task and is visible to the threadpool that runs the ``def`` endpoints.
    """
    if x_tenant_id is None:
        yield None
        return
    tenant_id = TenantId(x_tenant_id)
    structlog.contextvars.bind_contextvars(tenant_id=str(tenant_id))
    try:
        yield tenant_id
    finally:
        structlog.contextvars.unbind_contextvars("tenant_id")


def correlation_id(request: Request) -> str:
    return correlation_id_of(request) or ""


def gateway(request: Request) -> GatewayWiring:
    wiring: GatewayWiring = request.app.state.gateway
    return wiring


Tenant = Annotated[TenantId | None, Depends(tenant_id_from_header)]
Correlation = Annotated[str, Depends(correlation_id)]
Gateway = Annotated[GatewayWiring, Depends(gateway)]
