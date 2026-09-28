"""Request-scoped dependencies: the tenant from the header (required for sends) and the wiring."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request

from domain_kernel.ids import TenantId
from notification.wiring import Wiring


async def tenant_id_from_header(
    x_tenant_id: Annotated[
        UUID | None, Header(description="Tenant UUID; required until identity issues tokens")
    ] = None,
) -> AsyncIterator[TenantId | None]:
    tenant_id = None if x_tenant_id is None else TenantId(x_tenant_id)
    if tenant_id is not None:
        structlog.contextvars.bind_contextvars(tenant_id=str(tenant_id))
    try:
        yield tenant_id
    finally:
        if tenant_id is not None:
            structlog.contextvars.unbind_contextvars("tenant_id")


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Tenant = Annotated[TenantId | None, Depends(tenant_id_from_header)]
Wired = Annotated[Wiring, Depends(wiring)]
