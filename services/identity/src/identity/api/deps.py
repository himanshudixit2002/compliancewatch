"""Request-scoped dependencies: the caller and its tenant, the wiring, and the guard of the channel
consent routes.

The caller comes from ``py_common.auth.fastapi`` by ``CW_AUTH_MODE``. ``Tenant`` is the request's
tenant: a user's token names it, a service names it in ``x-tenant-id`` with the tenant:act scope,
and in header mode (or dual mode without a token) the header names it as before tokens existed. No
tenant is this service's own 401 identity-tenant-required. ``SignedInUser`` is a user a verified
token names; anyone else is refused.
"""

from typing import Annotated

from fastapi import Depends, Request

from domain_kernel.access import Principal, PrincipalKind, Scope
from domain_kernel.ids import TenantId
from identity.domain.errors import (
    ChannelTokenInvalidError,
    ChannelWritesDisabledError,
    TenantRequiredError,
)
from identity.wiring import Wiring
from py_common.auth.errors import AuthForbiddenError, AuthTokenRequiredError
from py_common.auth.fastapi import CurrentPrincipal, shared_token_or_roles, tenant_scope


def wiring(request: Request) -> Wiring:
    wired: Wiring = request.app.state.wiring
    return wired


Tenant = Annotated[TenantId, Depends(tenant_scope(True, TenantRequiredError))]
Wired = Annotated[Wiring, Depends(wiring)]


async def signed_in_user(principal: CurrentPrincipal) -> Principal:
    """A user a verified access token names: no token is a 401, a service's token a 403."""
    if principal.kind is PrincipalKind.USER:
        return principal
    if principal.kind is PrincipalKind.SERVICE:
        raise AuthForbiddenError("this route answers for a signed-in user, not a service")
    raise AuthTokenRequiredError()


SignedInUser = Annotated[Principal, Depends(signed_in_user)]

ChannelAccess = Depends(
    shared_token_or_roles(
        "identity_channel_token",
        "x-cw-service-token",
        scopes=[Scope.IDENTITY_CHANNEL_CONSENTS],
        disabled_error=ChannelWritesDisabledError,
        invalid_error=ChannelTokenInvalidError,
        description=(
            "Shared secret of the caller (CW_IDENTITY_CHANNEL_TOKEN), accepted when CW_AUTH_MODE "
            "is header or dual and the request carries no bearer token; a service token needs "
            "the identity:channel-consents scope"
        ),
    )
)
"""Channel consents are keyed by a phone number and no tenant guards them, so the routes fail
closed: without a bearer, no configured secret is a 503 (header mode) and a missing or wrong one
a 401, compared in constant time. A service token needs identity:channel-consents; token mode
accepts nothing else."""
