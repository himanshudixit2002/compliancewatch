"""Request-scoped dependencies: the tenant from the header (required for tenant data), the
wiring, the shared secret of the bot's receipts and the basic credentials of SNS's email
feedback."""

import hmac
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from domain_kernel.ids import TenantId
from notification.domain.errors import (
    EmailFeedbackUnauthorizedError,
    ReceiptsDisabledError,
    ReceiptTokenInvalidError,
    TenantRequiredError,
)
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


def require_bot_token(
    wired: Wired,
    x_cw_bot_token: Annotated[
        str | None,
        Header(description="Shared secret of the WhatsApp bot (CW_NOTIFICATION_BOT_TOKEN)"),
    ] = None,
) -> None:
    """Receipts name no tenant and change delivery records of every tenant, so the route fails
    closed: no configured token is a 503, a missing or wrong one a 401. The comparison takes the
    same time for any wrong token."""
    configured = wired.settings.notification_bot_token
    if configured is None or not configured.get_secret_value():
        raise ReceiptsDisabledError("CW_NOTIFICATION_BOT_TOKEN")
    given = (x_cw_bot_token or "").encode("utf-8")
    if not hmac.compare_digest(given, configured.get_secret_value().encode("utf-8")):
        raise ReceiptTokenInvalidError()


BotAccess = Depends(require_bot_token)


sns_basic = HTTPBasic(
    auto_error=False,
    description=(
        "The credentials in the SNS subscription URL; the password is "
        "CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN, the user name is not checked"
    ),
)


def require_feedback_credentials(
    wired: Wired,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(sns_basic)] = None,
) -> None:
    """The email feedback route takes SNS's HTTP basic credentials, so the secret is never in
    the path that logs and spans record. It fails closed like the bot's route: no configured
    secret is a 503, and missing or wrong credentials a 401 with the challenge SNS answers."""
    configured = wired.settings.notification_email_feedback_token
    if configured is None or not configured.get_secret_value():
        raise ReceiptsDisabledError("CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN")
    given = b"" if credentials is None else credentials.password.encode("utf-8")
    if not hmac.compare_digest(given, configured.get_secret_value().encode("utf-8")):
        raise EmailFeedbackUnauthorizedError()


FeedbackAccess = Depends(require_feedback_credentials)
