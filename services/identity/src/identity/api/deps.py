"""Request-scoped dependencies: the tenant from the header (required), the wiring, and the
service token of the channel consent routes."""

import hmac
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request

from domain_kernel.ids import TenantId
from identity.domain.errors import (
    ChannelTokenInvalidError,
    ChannelWritesDisabledError,
    TenantRequiredError,
)
from identity.wiring import Wiring


async def tenant_id_from_header(
    x_tenant_id: Annotated[
        UUID | None,
        Header(description="Tenant UUID; required until the identity service issues tokens"),
    ] = None,
) -> AsyncIterator[TenantId]:
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


def require_channel_token(
    wired: Wired,
    x_cw_service_token: Annotated[
        str | None, Header(description="Shared secret of the caller (CW_IDENTITY_CHANNEL_TOKEN)")
    ] = None,
) -> None:
    """Channel consents are keyed by a phone number and no tenant guards them, so the routes
    fail closed: no configured token is a 503, a missing or wrong one a 401. The comparison
    takes the same time for any wrong token."""
    configured = wired.settings.identity_channel_token
    if configured is None or not configured.get_secret_value():
        raise ChannelWritesDisabledError()
    given = (x_cw_service_token or "").encode("utf-8")
    if not hmac.compare_digest(given, configured.get_secret_value().encode("utf-8")):
        raise ChannelTokenInvalidError()


ChannelAccess = Depends(require_channel_token)
