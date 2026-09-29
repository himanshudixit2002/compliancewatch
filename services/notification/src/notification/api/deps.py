"""Request-scoped dependencies: the caller and its tenant, the wiring, the guards of the service
routes and the basic credentials of SNS's email feedback.

The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``. Without a token (``header``
mode, or ``dual`` mode without one) everything works as before tokens existed: the tenant is the
``x-tenant-id`` header and the bot's receipts carry its shared secret. With a token:

- ``Tenant`` (recipients and notifications): a user's token names the tenant and needs a tenant
  member role; a service names it in ``x-tenant-id`` with the tenant:act scope. A header naming
  another tenant than the user's token is a 403 ``auth-tenant-mismatch``.
- ``SendTenant`` (``/send``): a service with the notification:send scope, naming the tenant with
  tenant:act.
- ``PreferenceAccess``: a service with the notification:preferences scope. Preferences are keyed
  by channel and address and name no tenant, so no user may change them directly.
- ``BotAccess`` (WhatsApp receipts): a service with the notification:receipts scope, or the bot's
  shared secret in ``header`` and ``dual`` mode only.

No tenant at all is this service's own 401 ``notification-tenant-required``.
"""

import hmac
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from domain_kernel.access import TENANT_MEMBER_ROLES, Principal, Scope
from domain_kernel.ids import TenantId
from notification.domain.errors import (
    EmailFeedbackUnauthorizedError,
    ReceiptsDisabledError,
    ReceiptTokenInvalidError,
    TenantRequiredError,
)
from notification.wiring import Wiring
from py_common.auth.fastapi import require_roles, shared_token_or_roles, tenant_scope

tenant_of_request = tenant_scope(True, TenantRequiredError)
member = require_roles(TENANT_MEMBER_ROLES, scopes={Scope.TENANT_ACT})
"""A user with a tenant member role or a service with tenant:act; the anonymous principal of
``header`` mode passes."""
sender = require_roles(scopes={Scope.NOTIFICATION_SEND})
"""A service with notification:send; the anonymous principal of ``header`` mode passes."""


async def member_tenant(
    principal: Annotated[Principal, Depends(member)],
    tenant: Annotated[TenantId, Depends(tenant_of_request)],
) -> TenantId:
    """The request's tenant, once the caller is known to be one of its members."""
    return tenant


async def send_tenant(
    principal: Annotated[Principal, Depends(sender)],
    tenant: Annotated[TenantId, Depends(tenant_of_request)],
) -> TenantId:
    """The tenant a send is for, once the caller is known to be a sender. It is resolved while
    the dependencies resolve, before the body is validated, so a request without a tenant is
    refused as such whatever its body."""
    return tenant


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Tenant = Annotated[TenantId, Depends(member_tenant)]
SendTenant = Annotated[TenantId, Depends(send_tenant)]
Wired = Annotated[Wiring, Depends(wiring)]

PreferenceAccess = Depends(require_roles(scopes={Scope.NOTIFICATION_PREFERENCES}))
"""A service token needs notification:preferences; without a token the routes work as before."""

BotAccess = Depends(
    shared_token_or_roles(
        "notification_bot_token",
        "x-cw-bot-token",
        scopes=[Scope.NOTIFICATION_RECEIPTS],
        disabled_error=ReceiptsDisabledError,
        invalid_error=ReceiptTokenInvalidError,
        description=(
            "Shared secret of the WhatsApp bot (CW_NOTIFICATION_BOT_TOKEN), accepted when "
            "CW_AUTH_MODE is header or dual and the request carries no bearer token; a service "
            "token needs the notification:receipts scope"
        ),
    )
)
"""Receipts name no tenant and change delivery records of every tenant, so the route fails
closed: without a bearer, no configured secret is a 503 (header mode) and a missing or wrong one
a 401, compared in constant time. A service token needs notification:receipts; token mode
accepts nothing else."""


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
