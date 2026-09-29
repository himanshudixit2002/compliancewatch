"""Sign-in and service tokens: provider tokens and client secrets exchanged for access tokens.

``ExchangeSession`` verifies a provider token, finds the user its subject signs in as, checks
that the user and the tenant are active and that roles needing a second factor had one, and mints
an access token carrying the user's session version. ``IssueServiceToken`` checks a service
client's secret and mints a token with the client's scopes. ``check_session`` is what the identity
service's own routes run on a user's token: the session version must still be the user's, so a
change of roles or a disabled user takes effect here at once.
"""

import hmac
from dataclasses import dataclass
from datetime import timedelta

from domain_kernel.access import Principal, PrincipalKind
from identity.domain.errors import (
    MfaRequiredError,
    ServiceClientInvalidError,
    SessionRevokedError,
    TenantInactiveError,
    UserDisabledError,
    UserNotProvisionedError,
)
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.service_clients import secret_digest
from identity.domain.sessions import AccessToken, TokenMinter
from identity.domain.tenancy import Tenant, User

UNKNOWN_CLIENT_DIGEST = secret_digest("")
"""Compared against when the client is unknown, so a wrong id takes as long as a wrong secret."""


@dataclass(frozen=True, slots=True)
class Session:
    """A signed-in user's access token, with who it names."""

    token: AccessToken
    principal: Principal
    tenant: Tenant
    user: User


@dataclass(frozen=True, slots=True)
class ServiceSession:
    token: AccessToken
    principal: Principal


def user_principal(user: User, *, mfa: bool) -> Principal:
    """The principal an access token names for ``user``."""
    return Principal.user(
        user.id, user.tenant_id, user.roles, mfa=mfa, session_version=user.session_version
    )


def check_session(uow: UnitOfWork, principal: Principal) -> tuple[Tenant, User]:
    """The tenant and user a user's access token names, in a unit of work of that tenant.
    ``SessionRevokedError`` when the user is gone, disabled, or has another session version."""
    user_id = principal.user_id
    if principal.kind is not PrincipalKind.USER or user_id is None:
        raise SessionRevokedError()
    user = uow.users.get(user_id)
    tenant = None if principal.tenant_id is None else uow.tenants.get(principal.tenant_id)
    if (
        user is None
        or tenant is None
        or not user.is_active
        or user.session_version != principal.session_version
    ):
        raise SessionRevokedError()
    if not tenant.is_active:
        raise TenantInactiveError()
    return tenant, user


class ExchangeSession:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        provider: IdentityProvider,
        minter: TokenMinter,
        *,
        ttl: timedelta,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._provider = provider
        self._minter = minter
        self._ttl = ttl

    def run(self, provider_token: str) -> Session:
        identity = self._provider.verify(provider_token)
        with self._unit_of_work(None) as uow:
            entry = uow.subjects.find(self._provider.name, identity.subject)
        if entry is None:
            raise UserNotProvisionedError()
        with self._unit_of_work(entry.tenant_id) as uow:
            tenant = uow.tenants.get(entry.tenant_id)
            user = uow.users.get(entry.user_id)
        if tenant is None or user is None:
            raise UserNotProvisionedError()
        if not tenant.is_active:
            raise TenantInactiveError()
        if not user.is_active:
            raise UserDisabledError()
        if user.requires_mfa and not identity.mfa:
            raise MfaRequiredError()
        principal = user_principal(user, mfa=identity.mfa)
        return Session(self._minter.mint(principal, self._ttl), principal, tenant, user)


class IssueServiceToken:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, minter: TokenMinter, *, ttl: timedelta
    ) -> None:
        self._unit_of_work = unit_of_work
        self._minter = minter
        self._ttl = ttl

    def run(self, client_id: str, secret: str) -> ServiceSession:
        with self._unit_of_work(None) as uow:
            client = uow.service_clients.get(client_id)
        if client is None:
            hmac.compare_digest(secret_digest(secret), UNKNOWN_CLIENT_DIGEST)
            raise ServiceClientInvalidError()
        if not client.matches(secret) or not client.is_active:
            raise ServiceClientInvalidError()
        principal = Principal.service(client.client_id, client.scopes)
        return ServiceSession(self._minter.mint(principal, self._ttl), principal)
