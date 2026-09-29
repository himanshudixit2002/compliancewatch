"""Request-scoped dependencies: the tenant from the header (required here), the wiring and the
clock."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Final
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from profile_service.domain.errors import TenantRequiredError
from profile_service.wiring import Wiring


async def tenant_id_from_header(
    x_tenant_id: Annotated[
        UUID | None,
        Header(description="Tenant UUID; required until the identity service issues tokens"),
    ] = None,
) -> AsyncIterator[TenantId]:
    """Profiles are tenant data, so the header is required: a missing one is a 401 problem."""
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


TENANT_MEMBER_ROLES: Final = ("owner", "staff", "ca_admin", "ca_staff", "compliance_lead")
"""The roles of a tenant's members; each public route lists who may call it as ``x-roles``. The
identity service enforces them once it issues tokens; until then the tenant header scopes the
routes."""
PUBLIC_ROUTE: Final[dict[str, Any]] = {"x-roles": list(TENANT_MEMBER_ROLES)}
"""``openapi_extra`` of a public route every member of the tenant may call."""

Tenant = Annotated[TenantId, Depends(tenant_id_from_header)]
Wired = Annotated[Wiring, Depends(wiring)]


def clock() -> datetime:
    """The current time; tests override this dependency to fix it."""
    return utc_now()


Now = Annotated[datetime, Depends(clock)]
