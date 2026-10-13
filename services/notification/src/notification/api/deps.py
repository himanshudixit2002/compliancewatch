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
- ``BulkCaller`` (``/bulk``, the public API's bulk change card): a user of a CA firm (``ca_admin``
  or ``ca_staff``) whose token names the tenant, never a service; it carries the audit actor and
  the request's correlation id. ``PUBLIC_CA_ROUTE`` is its ``openapi_extra``: those roles as
  ``x-roles``.
- ``PreferenceAccess``: a service with the notification:preferences scope, or a user with a
  tenant member role (the web sends the signed-in person's token, and a web change is the
  tenant's). Preferences are keyed by channel and address and name no tenant themselves.
- ``PreferenceCaller``: for a change given on the web, the tenant (``resolve_tenant``: the
  user's own, a service's ``x-tenant-id`` with tenant:act, or the anonymous principal's
  header), and for a web opt-in, which identity's consent must cover, the consent subject: a
  user's token names its own user, and a body subject that differs is a 403; a service token
  or the anonymous principal of header mode names it in the body, the web app's server's word
  for its signed-in user, the trust boundary ``notification.application.preferences``
  describes. The ``api`` and ``support`` sources, which skip the consent check, are a
  service's: a person's token never records one, and outside header mode they need that
  service's token.
- ``Resender`` (``/notifications/{id}/resend``): who resends a failed notification, and for which
  tenant. A tenant admin (owner or ca_admin) resends their own tenant's, which their token names,
  as a CA firm's people send its bulk card; an admin of the internal tenant resends any tenant's,
  naming it in ``x-tenant-id`` (the regulatory team's console browses by tenant); a service and
  every other role are refused, and outside header mode so is a request without a token. It
  carries the audit actor and the request's correlation id for the ``notification.resent`` entry.
- ``ExportTenant`` (``/data-export``, ``py_common.auth.fastapi.data_export_scope``): a user with a
  tenant admin role (owner, ca_admin) for their own tenant, or a service only with a data:export
  token bound to that tenant and addressed to this service, as identity mints one per export.
- ``BotAccess`` (WhatsApp receipts): a service with the notification:receipts scope, or the bot's
  shared secret in ``header`` and ``dual`` mode only.

No tenant at all is this service's own 401 ``notification-tenant-required``.
"""

import hmac
from dataclasses import dataclass
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from domain_kernel.access import (
    TENANT_ADMIN_ROLES,
    TENANT_MEMBER_ROLES,
    Principal,
    PrincipalKind,
    Role,
    Scope,
)
from domain_kernel.audit import AuditActor
from domain_kernel.ids import TenantId
from notification.domain.errors import (
    EmailFeedbackUnauthorizedError,
    ReceiptsDisabledError,
    ReceiptTokenInvalidError,
    TenantRequiredError,
)
from notification.wiring import Wiring
from py_common.audit import audit_actor, current_correlation_id
from py_common.auth.errors import AuthForbiddenError, AuthTokenRequiredError
from py_common.auth.fastapi import (
    TENANT_HEADER_DESCRIPTION,
    CurrentPrincipal,
    authenticator_of,
    data_export_scope,
    refuse_erased,
    require_roles,
    resolve_tenant,
    shared_token_or_roles,
    tenant_scope,
)

SERVICE_NAME: Final = "notification"
CA_ROLES: Final = (Role.CA_ADMIN, Role.CA_STAFF)
PUBLIC_CA_ROUTE: Final[dict[str, Any]] = {"x-roles": [role.value for role in CA_ROLES]}
"""``openapi_extra`` of a public route only a CA firm's people may call."""

tenant_of_request = tenant_scope(True, TenantRequiredError)
member = require_roles(TENANT_MEMBER_ROLES, scopes={Scope.TENANT_ACT})
"""A user with a tenant member role or a service with tenant:act; the anonymous principal of
``header`` mode passes."""
sender = require_roles(scopes={Scope.NOTIFICATION_SEND})
"""A service with notification:send; the anonymous principal of ``header`` mode passes."""
ca_member = require_roles(CA_ROLES)
"""A user with a CA firm's role; a service is refused, and the anonymous principal of ``header``
mode passes."""
resend_roles = require_roles(TENANT_ADMIN_ROLES, Role.ADMIN)
"""A tenant admin or the regulatory team's admin; a service is refused, and the anonymous
principal of ``header`` mode passes."""


@dataclass(frozen=True, slots=True)
class OptInCaller:
    """Who changes a preference, the tenant the request offers, and whether the service runs in
    header mode."""

    principal: Principal
    offered_tenant: TenantId | None = None
    header_mode: bool = False

    def tenant(self) -> TenantId | None:
        """The request's tenant: a service's ``x-tenant-id`` with tenant:act, or the anonymous
        principal's header; None without."""
        return resolve_tenant(self.principal, self.offered_tenant)

    def subject(self, named: str | None) -> str | None:
        """The consent subject of a web opt-in: a person's token names its own user, and a
        body naming anyone else is refused; any other caller names it in the body."""
        if self.principal.kind is PrincipalKind.USER:
            own = str(self.principal.user_id)
            if named is not None and named != own:
                raise AuthForbiddenError(
                    "a person records a preference under their own consent subject"
                )
            return own
        return named

    def require_service(self, source: str) -> None:
        """Outside header mode, a change only a service records needs its token; a person's
        token never records one, whatever the mode."""
        if self.principal.kind is PrincipalKind.USER:
            raise AuthForbiddenError(
                f"a preference with source {source} is recorded by a service, not by a person"
            )
        if not self.principal.is_authenticated and not self.header_mode:
            raise AuthTokenRequiredError(
                f"a preference with source {source} is recorded by a service: send its token"
            )


async def preference_caller(
    request: Request,
    principal: CurrentPrincipal,
    x_tenant_id: Annotated[UUID | None, Header(description=TENANT_HEADER_DESCRIPTION)] = None,
) -> OptInCaller:
    return OptInCaller(
        principal,
        None if x_tenant_id is None else TenantId(x_tenant_id),
        header_mode=authenticator_of(request).mode == "header",
    )


@dataclass(frozen=True, slots=True)
class ResendCaller:
    """Who resends a notification of which tenant: the actor its audit entry names and the
    request's correlation id."""

    tenant_id: TenantId
    actor: AuditActor
    correlation_id: str | None = None


async def resend_caller(
    request: Request,
    principal: Annotated[Principal, Depends(resend_roles)],
    x_tenant_id: Annotated[UUID | None, Header(description=TENANT_HEADER_DESCRIPTION)] = None,
) -> ResendCaller:
    """Who resends, for which tenant: an internal admin names any tenant in ``x-tenant-id``; a
    tenant admin's token names their own (a header naming another is a 403); the anonymous
    caller of header mode names it in the header. No tenant is a 401 ``tenant-required``."""
    offered = None if x_tenant_id is None else TenantId(x_tenant_id)
    if not principal.is_authenticated and authenticator_of(request).mode != "header":
        raise AuthTokenRequiredError(
            "Resending needs a tenant admin's or an admin's access token as "
            "Authorization: Bearer <token>"
        )
    if principal.kind is PrincipalKind.USER and principal.has_role(Role.ADMIN):
        tenant = offered
    else:
        tenant = resolve_tenant(principal, offered)
    if tenant is None:
        raise TenantRequiredError()
    await refuse_erased(request, tenant)
    return ResendCaller(
        tenant_id=tenant,
        actor=audit_actor(SERVICE_NAME, principal),
        correlation_id=current_correlation_id(),
    )


@dataclass(frozen=True, slots=True)
class BulkCaller:
    """Who sends a bulk notification for which tenant: the actor its audit entry names and the
    request's correlation id."""

    tenant_id: TenantId
    actor: AuditActor
    correlation_id: str | None = None


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


async def bulk_caller(
    principal: Annotated[Principal, Depends(ca_member)],
    tenant: Annotated[TenantId, Depends(tenant_of_request)],
) -> BulkCaller:
    """Who sends a bulk notification of the request's tenant, once the caller is known to be one
    of its CA firm's people."""
    return BulkCaller(
        tenant_id=tenant,
        actor=audit_actor(SERVICE_NAME, principal),
        correlation_id=current_correlation_id(),
    )


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Tenant = Annotated[TenantId, Depends(member_tenant)]
SendTenant = Annotated[TenantId, Depends(send_tenant)]
Bulk = Annotated[BulkCaller, Depends(bulk_caller)]
Resender = Annotated[ResendCaller, Depends(resend_caller)]
ExportTenant = Annotated[TenantId, Depends(data_export_scope(SERVICE_NAME, TenantRequiredError))]
PreferenceCaller = Annotated[OptInCaller, Depends(preference_caller)]
Wired = Annotated[Wiring, Depends(wiring)]

PreferenceAccess = Depends(
    require_roles(TENANT_MEMBER_ROLES, scopes={Scope.NOTIFICATION_PREFERENCES})
)
"""A tenant member's token (the web app's settings and onboarding pages set and read a person's
preference for them) or a service token with notification:preferences; without a token the
routes work as before. A person's token records web sources only (``OptInCaller``)."""

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
