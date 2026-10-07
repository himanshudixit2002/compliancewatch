"""FastAPI dependencies that read the caller from a bearer token, by ``CW_AUTH_MODE``.

``create_app`` puts an ``Authenticator`` on ``app.state``. ``authenticate`` reads
``Authorization: Bearer <token>`` and returns the ``Principal``:

- ``header``: the anonymous principal, whatever the request carries, as before tokens existed;
- ``dual``: the principal a bearer token names when the request carries one (a bad token is a
  401), and the anonymous principal otherwise;
- ``token``: a bearer token is required (401 ``auth-token-required`` without one).

Only routes that depend on it read the caller. A route that does not (the probes, sign-in, the
reads that are the same for everyone) stays open in every mode, so a route that must be guarded
in ``token`` mode declares one of the dependencies below.

The principal is bound for the request (``py_common.auth.context``): ``actor`` and, for a user,
``tenant_id`` appear on every log line. The dependency is ``async`` so the binding happens in the
request task and reaches the threadpool that runs ``def`` endpoints; verification itself, which
may fetch keys, runs in the threadpool.

On top of it:

- ``tenant_scope(required, missing_error)``: the request's tenant. A user's token names it, and
  an ``x-tenant-id`` header that names another is a 403 ``auth-tenant-mismatch``. A service names
  it in ``x-tenant-id`` and needs ``tenant:act`` to do so, unless its token is bound to a tenant
  (``Principal.acts_for``): then it acts for that tenant only, and a header naming another is a
  403 ``auth-tenant-mismatch``. The anonymous principal names it in the header, as before. No
  tenant at all is the service's own ``missing_error``.
- ``data_export_scope(service, missing_error)``: the tenant whose data export ``service``
  answers. A user with a tenant admin role (owner, ca_admin) for their own tenant; a service only
  with a token bound to that tenant, addressed to ``service`` and holding ``data:export``, as
  identity mints one per service an export reads; the anonymous principal of ``header`` mode for
  the header's tenant. Anyone else is a 403.
- ``require_roles(*roles, scopes=...)``: a user with one of the roles or a service with one of the
  scopes; anyone else is a 403 ``auth-forbidden``. It lets the anonymous principal through, so
  ``header`` mode (and ``dual`` without a token) behaves as before.
- ``shared_token_or_roles(setting, header, roles, scopes)``: routes that a shared secret guarded
  before tokens existed. A bearer with one of the roles or scopes is accepted in ``dual`` and
  ``token`` mode; the shared secret (the settings field ``setting``, sent in ``header``) is
  accepted only in ``header`` and ``dual`` mode, and fails closed when it is not configured.
"""

import hmac
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Annotated, Final, Literal, Self, overload
from uuid import UUID

import structlog
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from domain_kernel.access import (
    ANONYMOUS,
    TENANT_ADMIN_ROLES,
    Principal,
    PrincipalKind,
    Role,
    Scope,
)
from domain_kernel.errors import DomainError
from domain_kernel.ids import TenantId
from py_common.auth.context import TENANT_FIELD, bind_principal, unbind_principal
from py_common.auth.errors import (
    AuthForbiddenError,
    AuthTenantMismatchError,
    AuthTokenRequiredError,
)
from py_common.auth.tokens import TokenVerifier
from py_common.settings import AuthMode, Settings

AUTH_MODES: Final[tuple[AuthMode, ...]] = ("header", "dual", "token")
TENANT_HEADER_DESCRIPTION: Final = (
    "Tenant UUID. A user's access token names the tenant, so a user leaves the header out or "
    "repeats that tenant; a service token names one here with the tenant:act scope."
)

bearer_scheme = HTTPBearer(
    auto_error=False,
    description=(
        "An access token from the identity service. Read when CW_AUTH_MODE is dual or token; "
        "required when it is token."
    ),
)


class Authenticator:
    """Turns a request's bearer token, or its absence, into a principal by ``mode``.
    ``verifier`` is required in ``dual`` and ``token`` mode."""

    def __init__(self, mode: AuthMode, verifier: TokenVerifier | None = None) -> None:
        if mode not in AUTH_MODES:
            raise ValueError(f"auth mode must be one of {', '.join(AUTH_MODES)}, got {mode!r}")
        if mode != "header" and verifier is None:
            raise ValueError(f"auth mode {mode} needs a token verifier")
        self.mode: AuthMode = mode
        self.verifier = verifier

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """The authenticator ``CW_AUTH_MODE`` and the ``CW_AUTH_*`` settings describe."""
        if settings.auth_mode == "header":
            return cls("header")
        return cls(settings.auth_mode, TokenVerifier.from_settings(settings))

    @property
    def accepts_shared_tokens(self) -> bool:
        """Whether shared secrets still open the routes they guarded (not in ``token`` mode)."""
        return self.mode != "token"

    def principal_for(self, token: str | None) -> Principal:
        """The principal for a request that carries ``token`` (None: no bearer token)."""
        if self.mode == "header":
            return ANONYMOUS
        if token is None:
            if self.mode == "token":
                raise AuthTokenRequiredError()
            return ANONYMOUS
        if self.verifier is None:  # pragma: no cover - refused by __init__
            raise AuthTokenRequiredError()
        return self.verifier.verify(token)


def authenticator_of(request: Request) -> Authenticator:
    """The app's authenticator, which ``create_app`` sets."""
    authenticator = getattr(request.app.state, "authenticator", None)
    if not isinstance(authenticator, Authenticator):
        raise RuntimeError("the app has no authenticator; build it with py_common.app.create_app")
    return authenticator


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AsyncIterator[Principal]:
    """The request's principal, bound into the context for the rest of the request."""
    authenticator = authenticator_of(request)
    token = None if credentials is None else credentials.credentials
    if authenticator.mode == "header" or token is None:
        principal = authenticator.principal_for(token)
    else:
        principal = await run_in_threadpool(authenticator.principal_for, token)
    bind_principal(principal)
    try:
        yield principal
    finally:
        unbind_principal(principal)


CurrentPrincipal = Annotated[Principal, Depends(authenticate)]


async def require_authenticated(principal: CurrentPrincipal) -> Principal:
    """A principal a verified token named; the anonymous principal is a 401."""
    if not principal.is_authenticated:
        raise AuthTokenRequiredError()
    return principal


Authenticated = Annotated[Principal, Depends(require_authenticated)]


def resolve_tenant(principal: Principal, offered: TenantId | None) -> TenantId | None:
    """The tenant a request acts for: the user's own, a service's ``x-tenant-id`` (with
    ``tenant:act``), the one a bound service token names, or the anonymous principal's
    header."""
    if principal.kind is PrincipalKind.USER:
        if offered is not None and offered != principal.tenant_id:
            raise AuthTenantMismatchError()
        return principal.tenant_id
    if principal.acts_for is not None:
        if offered is not None and offered != principal.acts_for:
            raise AuthTenantMismatchError(
                "x-tenant-id names another tenant than the one the service token is bound to"
            )
        return principal.acts_for
    if (
        principal.kind is PrincipalKind.SERVICE
        and offered is not None
        and not principal.has_scope(Scope.TENANT_ACT)
    ):
        raise AuthForbiddenError(
            f"a service acts for a tenant only with the {Scope.TENANT_ACT.value} scope"
        )
    return offered


@overload
def tenant_scope(
    required: Literal[True],
    missing_error: type[DomainError],
    *,
    description: str = ...,
) -> Callable[..., AsyncIterator[TenantId]]: ...


@overload
def tenant_scope(
    required: Literal[False],
    missing_error: type[DomainError] | None = None,
    *,
    description: str = ...,
) -> Callable[..., AsyncIterator[TenantId | None]]: ...


def tenant_scope(
    required: bool,
    missing_error: type[DomainError] | None = None,
    *,
    description: str = TENANT_HEADER_DESCRIPTION,
) -> Callable[..., AsyncIterator[TenantId]] | Callable[..., AsyncIterator[TenantId | None]]:
    """A dependency that resolves the request's tenant and binds it into the log context.

    With ``required`` a request without a tenant raises ``missing_error``, the service's own
    problem, so problem types stay stable; otherwise it gets None. ``x-tenant-id`` is declared in
    the spec with ``description``.
    """
    if required and missing_error is None:
        raise ValueError("a required tenant scope needs the service's missing-tenant error")

    async def tenant(
        principal: CurrentPrincipal,
        x_tenant_id: Annotated[UUID | None, Header(description=description)] = None,
    ) -> AsyncIterator[TenantId | None]:
        offered = None if x_tenant_id is None else TenantId(x_tenant_id)
        resolved = resolve_tenant(principal, offered)
        if resolved is None:
            if missing_error is not None and required:
                raise missing_error()
            yield None
            return
        structlog.contextvars.bind_contextvars(**{TENANT_FIELD: str(resolved)})
        try:
            yield resolved
        finally:
            structlog.contextvars.unbind_contextvars(TENANT_FIELD)

    return tenant


def data_export_scope(
    service: str, missing_error: type[DomainError]
) -> Callable[..., Awaitable[TenantId]]:
    """A dependency that resolves the tenant whose data export ``service`` answers, once the
    caller may read it (see the module's docstring); ``missing_error`` is the service's own
    problem for a request with no tenant."""
    tenant_of_request = tenant_scope(True, missing_error)

    async def export_tenant(
        principal: CurrentPrincipal,
        tenant: Annotated[TenantId, Depends(tenant_of_request)],
    ) -> TenantId:
        if not principal.is_authenticated:
            return tenant
        if principal.kind is PrincipalKind.USER:
            if principal.has_role(*TENANT_ADMIN_ROLES):
                return tenant
            raise AuthForbiddenError(_needs(TENANT_ADMIN_ROLES, frozenset({Scope.DATA_EXPORT})))
        if not principal.has_scope(Scope.DATA_EXPORT):
            raise AuthForbiddenError(f"a service exports data only with {Scope.DATA_EXPORT.value}")
        if principal.acts_for is None or principal.acts_for != tenant:
            raise AuthForbiddenError("an export token is bound to the tenant it exports")
        if principal.audience != service:
            raise AuthForbiddenError(f"this export token is not addressed to {service}")
        return tenant

    return export_tenant


def _roles(roles: Iterable[Role | Iterable[Role]]) -> frozenset[Role]:
    found: set[Role] = set()
    for item in roles:
        if isinstance(item, Role):
            found.add(item)
        else:
            found.update(item)
    return frozenset(found)


def _allowed(principal: Principal, roles: frozenset[Role], scopes: frozenset[Scope]) -> bool:
    return principal.has_role(*roles) or any(principal.has_scope(scope) for scope in scopes)


def require_roles(
    *roles: Role | Iterable[Role], scopes: Iterable[Scope] = ()
) -> Callable[..., Awaitable[Principal]]:
    """A dependency that lets through a user holding one of ``roles`` (members or sets of them,
    such as ``TENANT_MEMBER_ROLES``) or a service holding one of ``scopes``, and the anonymous
    principal of ``header`` mode; anyone else is a 403."""
    wanted_roles = _roles(roles)
    wanted_scopes = frozenset(scopes)
    if not wanted_roles and not wanted_scopes:
        raise ValueError("require_roles needs at least one role or scope")

    async def check(principal: CurrentPrincipal) -> Principal:
        if not principal.is_authenticated or _allowed(principal, wanted_roles, wanted_scopes):
            return principal
        raise AuthForbiddenError(_needs(wanted_roles, wanted_scopes))

    return check


def _needs(roles: frozenset[Role], scopes: frozenset[Scope]) -> str:
    named = sorted(role.value for role in roles) + sorted(scope.value for scope in scopes)
    return f"this request needs one of: {', '.join(named)}"


def _configured_secret(value: object) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value if isinstance(value, str) else ""


def shared_token_or_roles(
    setting: str,
    header: str,
    roles: Iterable[Role | Iterable[Role]] = (),
    scopes: Iterable[Scope] = (),
    *,
    disabled_error: type[DomainError],
    invalid_error: type[DomainError],
    description: str | None = None,
) -> Callable[..., Awaitable[Principal]]:
    """A dependency for a route a shared secret guarded before tokens existed.

    - A verified bearer (``dual`` or ``token`` mode) needs one of ``roles`` or ``scopes``; without
      them it is a 403, whatever secret the request also sends.
    - Without a bearer (``header`` mode, or ``dual`` without a token) the request needs the secret
      in ``header`` that equals the settings field ``setting`` of the app's settings. A missing
      or wrong secret is the service's ``invalid_error``. An unset secret is its
      ``disabled_error`` in ``header`` mode (the route fails closed) and a 401 asking for a token
      in ``dual`` mode, where a token would open it.
    - ``token`` mode never gets there: ``authenticate`` already required the bearer.

    The comparison takes the same time for any wrong secret. ``disabled_error`` and
    ``invalid_error`` are the service's own problems, whose titles name the service.
    """
    if not setting.isidentifier():
        raise ValueError(f"setting must name a settings field, got {setting!r}")
    wanted_roles = _roles(roles)
    wanted_scopes = frozenset(scopes)
    if not wanted_roles and not wanted_scopes:
        raise ValueError("shared_token_or_roles needs at least one role or scope")
    header_description = description or (
        f"Shared secret (CW_{setting.upper()}), accepted when CW_AUTH_MODE is header or dual "
        "and the request carries no bearer token"
    )

    async def check(
        request: Request,
        principal: CurrentPrincipal,
        shared_token: Annotated[
            str | None, Header(alias=header, description=header_description)
        ] = None,
    ) -> Principal:
        if principal.is_authenticated:
            if _allowed(principal, wanted_roles, wanted_scopes):
                return principal
            raise AuthForbiddenError(_needs(wanted_roles, wanted_scopes))
        authenticator = authenticator_of(request)
        configured = _configured_secret(getattr(request.app.state.settings, setting, None))
        if not configured:
            if authenticator.mode == "dual":
                raise AuthTokenRequiredError()
            raise disabled_error()
        given = (shared_token or "").encode("utf-8")
        if not hmac.compare_digest(given, configured.encode("utf-8")):
            raise invalid_error()
        return principal

    return check
