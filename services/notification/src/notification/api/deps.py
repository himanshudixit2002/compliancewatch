"""Request-scoped dependencies: the tenant from the header (required for sends) and the wiring."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request

from domain_kernel.ids import TenantId
from notification.domain.errors import TenantRequiredError
from notification.wiring import Wiring


async def tenant_id_from_header(
    x_tenant_id: Annotated[
        UUID | None, Header(description="Tenant UUID; required until identity issues tokens")
    ] = None,
) -> AsyncIterator[TenantId]:
    """Sends are tenant data: a missing header is a 401 problem. It is raised while the
    dependencies resolve, before the body is validated, so a request without a tenant is refused
    as such whatever its body."""
    if x_tenant_id is None:
        raise TenantRequiredError()
    tenant_id = TenantId(x_tenant_id)
    structlog.contextvars.bind_contextvars(tenant_id=str(tenant_id))
    try:
        yield tenant_id
    finally:
        structlog.contextvars.unbind_contextvars("tenant_id")


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Tenant = Annotated[TenantId, Depends(tenant_id_from_header)]
Wired = Annotated[Wiring, Depends(wiring)]
