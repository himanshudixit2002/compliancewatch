"""Composition root for the identity service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The service owns tenants, users and roles, signs people in through the identity provider
(``CW_AUTH_PROVIDER``, ADR-014) and issues the access tokens every service verifies, with its own
ES256 keys (``CW_IDENTITY_SIGNING_KEYS``). It verifies its own tokens in the process: the
authenticator it hands to ``create_app`` holds the same keys. It also keeps consent records,
channel consents for numbers no tenant owns yet, and billing behind ``CW_BILLING_PROVIDER``.

In local and test, with ``CW_IDENTITY_DEV_CLIENT_SECRET`` set, the app makes the dev service
clients exist when it starts.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError
from identity import __version__
from identity.api.auth import router as auth_router
from identity.api.router import router
from identity.api.tenancy import router as tenancy_router
from identity.application.billing import BillingLedger, ReceiveBillingWebhook, StartSubscription
from identity.application.bootstrap import EnsureDevServiceClients
from identity.application.channel_consents import ChannelConsentStatus, RecordChannelConsent
from identity.application.consents import ConsentStatus, RecordConsent
from identity.application.sessions import ExchangeSession, IssueServiceToken
from identity.application.tenancy import (
    ChangeRoles,
    CreateTenant,
    CurrentUser,
    DisableUser,
    InviteUser,
    ListUsers,
    ReadMembership,
)
from identity.composition import identity_provider
from identity.domain.billing import BillingProvider
from identity.domain.channel_consent import ChannelUnitOfWorkFactory
from identity.domain.errors import (
    BillingDisabledError,
    ChannelPurposeInvalidError,
    ChannelSubjectInvalidError,
    ChannelTokenInvalidError,
    ChannelWritesDisabledError,
    DevSignInUnavailableError,
    InternalTenantExistsError,
    InvalidWebhookSignatureError,
    LastAdminError,
    MfaRequiredError,
    NoticeVersionRequiredError,
    ProviderAccountExistsError,
    ProviderTokenInvalidError,
    ProviderUnavailableError,
    RoleNotAllowedError,
    ServiceClientInvalidError,
    SessionRevokedError,
    SubjectRegisteredError,
    TenantInactiveError,
    TenantNotFoundError,
    TenantRequiredError,
    UserDisabledError,
    UserNotFoundError,
    UserNotProvisionedError,
)
from identity.domain.provider import DevIdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.infrastructure.billing.memory import MemoryBillingProvider
from identity.infrastructure.billing.razorpay import RazorpayBillingProvider
from identity.infrastructure.memory import MemoryChannelStore, MemoryStore
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from identity.settings import IdentitySettings
from identity.wiring import Wiring
from py_common.app import create_app, module_app
from py_common.auth import (
    KeySet,
    StaticKeySource,
    TokenIssuer,
    TokenVerifier,
    generate_signing_key,
    load_signing_keys,
)
from py_common.auth.fastapi import Authenticator
from py_common.logging import get_logger

SERVICE_NAME = "identity"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    TenantRequiredError: 401,
    NoticeVersionRequiredError: 422,
    BillingDisabledError: 503,
    InvalidWebhookSignatureError: 401,
    ChannelWritesDisabledError: 503,
    ChannelTokenInvalidError: 401,
    ChannelSubjectInvalidError: 422,
    ChannelPurposeInvalidError: 422,
    RoleNotAllowedError: 422,
    LastAdminError: 409,
    UserNotFoundError: 404,
    UserDisabledError: 403,
    SubjectRegisteredError: 409,
    ProviderTokenInvalidError: 401,
    ProviderUnavailableError: 503,
    ProviderAccountExistsError: 409,
    UserNotProvisionedError: 404,
    MfaRequiredError: 403,
    TenantInactiveError: 403,
    SessionRevokedError: 401,
    ServiceClientInvalidError: 401,
    DevSignInUnavailableError: 404,
    TenantNotFoundError: 404,
    InternalTenantExistsError: 409,
}

log = get_logger(__name__)


def billing_provider(settings: IdentitySettings) -> BillingProvider | None:
    if settings.billing_provider == "memory":
        return MemoryBillingProvider()
    if (
        settings.billing_provider == "razorpay"
        and settings.razorpay_key_id
        and settings.razorpay_key_secret is not None
        and settings.razorpay_webhook_secret is not None
    ):
        return RazorpayBillingProvider(
            settings.razorpay_key_id,
            settings.razorpay_key_secret.get_secret_value(),
            settings.razorpay_webhook_secret.get_secret_value(),
            plan_ids=settings.razorpay_plan_ids,
        )
    return None


def signing_keys(settings: IdentitySettings) -> KeySet:
    """The configured key set; in local and test without one, a key made now, which every token
    signed with it outlives only until the process stops."""
    configured = settings.identity_signing_keys
    if configured is not None and configured.get_secret_value():
        return load_signing_keys(configured.get_secret_value())
    if not settings.is_dev:  # pragma: no cover - refused by the settings
        raise ValueError(f"CW_ENV={settings.env} needs CW_IDENTITY_SIGNING_KEYS")
    kid = f"ephemeral-{uuid4().hex[:8]}"
    log.warning(
        "identity_ephemeral_signing_key",
        kid=kid,
        hint="set CW_IDENTITY_SIGNING_KEYS (identity-admin signing-key new) to keep tokens valid "
        "across restarts",
    )
    return KeySet((generate_signing_key(kid),))


def token_verifier(settings: IdentitySettings, keys: KeySet) -> TokenVerifier:
    """A verifier of this service's own tokens, against its keys in the process."""
    return TokenVerifier(
        StaticKeySource.from_key_set(keys),
        issuer=settings.auth_issuer,
        audience=settings.auth_audience,
        leeway=timedelta(seconds=settings.auth_leeway_seconds),
    )


def wire(settings: IdentitySettings) -> Wiring:
    unit_of_work: UnitOfWorkFactory
    channel_unit_of_work: ChannelUnitOfWorkFactory
    ping: Callable[[], bool]
    if settings.identity_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping = memory, memory.ping
        channel_unit_of_work = MemoryChannelStore()
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping
        channel_unit_of_work = postgres.channel_unit_of_work

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    billing = billing_provider(settings)
    ledger = BillingLedger()
    keys = signing_keys(settings)
    minter = IssuerMinter(
        TokenIssuer(keys, issuer=settings.auth_issuer, audience=settings.auth_audience)
    )
    provider = identity_provider(settings)
    dev_provider: DevIdentityProvider | None = None
    if isinstance(provider, FakeIdentityProvider) and settings.is_dev:
        dev_provider = provider
    access_ttl = timedelta(seconds=settings.access_token_ttl_seconds)
    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        record_consent=RecordConsent(unit_of_work),
        consent_status=ConsentStatus(unit_of_work),
        channel_unit_of_work=channel_unit_of_work,
        record_channel_consent=RecordChannelConsent(channel_unit_of_work),
        channel_consent_status=ChannelConsentStatus(channel_unit_of_work),
        billing_enabled=billing is not None,
        billing_ledger=ledger,
        start_subscription=None if billing is None else StartSubscription(billing, ledger),
        receive_billing_webhook=None if billing is None else ReceiveBillingWebhook(billing, ledger),
        keys=keys,
        provider=provider,
        dev_provider=dev_provider,
        exchange_session=ExchangeSession(unit_of_work, provider, minter, ttl=access_ttl),
        issue_service_token=IssueServiceToken(
            unit_of_work, minter, ttl=timedelta(seconds=settings.service_token_ttl_seconds)
        ),
        create_tenant=CreateTenant(unit_of_work, provider, minter, ttl=access_ttl),
        current_user=CurrentUser(unit_of_work),
        list_users=ListUsers(unit_of_work),
        read_membership=ReadMembership(unit_of_work),
        invite_user=InviteUser(unit_of_work, provider),
        change_roles=ChangeRoles(unit_of_work),
        disable_user=DisableUser(unit_of_work),
    )


def ensure_dev_clients(wiring: Wiring) -> None:
    """In local and test with a dev client secret, make the dev service clients exist. A store
    that cannot be written yet (not migrated, not running) leaves a warning, not a failed start."""
    settings = wiring.settings
    secret = settings.identity_dev_client_secret
    if not settings.is_dev or secret is None or not secret.get_secret_value():
        return
    try:
        ensured = EnsureDevServiceClients(wiring.unit_of_work).run(
            settings.dev_clients, secret.get_secret_value()
        )
    except SQLAlchemyError as exc:
        log.warning("identity_dev_clients_not_ensured", error=type(exc).__name__)
        return
    log.info("identity_dev_clients_ensured", clients=[client.client_id for client in ensured])


def build_app(settings: IdentitySettings | None = None) -> FastAPI:
    settings = settings or IdentitySettings(service_name=SERVICE_NAME)
    wiring = wire(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(ensure_dev_clients, wiring)
        yield

    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router, auth_router, tenancy_router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        lifespan=lifespan,
        problem_status=PROBLEM_STATUS,
        authenticator=Authenticator(settings.auth_mode, token_verifier(settings, wiring.keys)),
    )
    app.state.wiring = wiring
    return app


def __getattr__(name: str) -> FastAPI:
    """``app`` is built on first access, so importing this module builds nothing."""
    return module_app(name, build_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("identity.main:app", host="127.0.0.1", port=8001, reload=True)
