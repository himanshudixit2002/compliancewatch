"""Composition root for the identity service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The service owns tenants, users and roles, signs people in through the identity provider
(``CW_AUTH_PROVIDER``, ADR-014) and issues the access tokens every service verifies, with its own
ES256 keys (``CW_IDENTITY_SIGNING_KEYS``). It verifies its own tokens in the process: the
authenticator it hands to ``create_app`` holds the same keys. It also keeps consent records,
channel consents for numbers no tenant owns yet, and billing behind ``CW_BILLING_PROVIDER`` with
the entitlements a tenant's plan gives (``GET /v1/identity/entitlements``), and it reads the
audit log every service writes (``GET /v1/identity/audit``). A tenant's data requests and its
export (``/v1/identity/data-requests``) gather identity's own data and the data each service of
``CW_IDENTITY_EXPORT_SOURCES`` answers, called with a service token identity mints for itself;
``export_sources`` replaces them (tests and demos). With telemetry on, the app reports every
tenant's open and overdue data requests (``install_data_request_metrics``). A deletion request
turns the tenant ``deletion_requested`` and asks every service to erase it; identity's own worker
(``identity.worker``) erases identity's part and records the answers.

In local and test, with ``CW_IDENTITY_DEV_CLIENT_SECRET`` set, the app makes the dev service
clients exist when it starts.
"""

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from domain_kernel.access import Principal, Scope
from domain_kernel.errors import DomainError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity import __version__
from identity.api.audit import router as audit_router
from identity.api.auth import router as auth_router
from identity.api.data_requests import router as data_requests_router
from identity.api.entitlements import router as entitlements_router
from identity.api.router import router
from identity.api.tenancy import router as tenancy_router
from identity.application.audit import ReadAuditTrail
from identity.application.billing import ReceiveBillingWebhook, StartSubscription
from identity.application.bootstrap import EnsureDevServiceClients
from identity.application.channel_consents import ChannelConsentStatus, RecordChannelConsent
from identity.application.consents import ConsentStatus, RecordConsent
from identity.application.data_requests import (
    ExportTenantData,
    ListDataRequests,
    ReadDataRequest,
    RequestDeletion,
    RequestExport,
)
from identity.application.entitlements import ReadEntitlements, SeatCheck
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
from identity.domain.audit import AuditReader
from identity.domain.billing import PLANS, BillingProvider
from identity.domain.channel_consent import ChannelUnitOfWorkFactory
from identity.domain.data_requests import DataRequestDirectory, ExportSource
from identity.domain.entitlements import Limits
from identity.domain.errors import (
    BillingDisabledError,
    ChannelPurposeInvalidError,
    ChannelSubjectInvalidError,
    ChannelTokenInvalidError,
    ChannelWritesDisabledError,
    DataRequestNotFoundError,
    DeletionRequestNotFoundError,
    DevSignInUnavailableError,
    ExportNotReadyError,
    InternalTenantExistsError,
    InvalidWebhookSignatureError,
    LastAdminError,
    MfaRequiredError,
    NoticeVersionRequiredError,
    ProviderAccountExistsError,
    ProviderTokenInvalidError,
    ProviderUnavailableError,
    RoleNotAllowedError,
    SeatLimitReachedError,
    ServiceClientInvalidError,
    SessionRevokedError,
    SubjectRegisteredError,
    SubscriptionStartPendingError,
    TenantDeletingError,
    TenantInactiveError,
    TenantNotErasableError,
    TenantNotFoundError,
    TenantRequiredError,
    UserDisabledError,
    UserNotFoundError,
    UserNotProvisionedError,
)
from identity.domain.flags import FeatureFlags
from identity.domain.provider import DevIdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.infrastructure.audit_reader import PostgresAuditReader
from identity.infrastructure.billing.memory import MemoryBillingProvider
from identity.infrastructure.billing.razorpay import RazorpayBillingProvider
from identity.infrastructure.data_request_metrics import register_data_request_gauges
from identity.infrastructure.export_sources import HttpExportSource
from identity.infrastructure.flags import OpenFeatureFlags
from identity.infrastructure.memory import (
    MemoryAuditReader,
    MemoryChannelStore,
    MemoryDataRequestDirectory,
    MemoryStore,
)
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.infrastructure.repository import (
    PostgresDataRequestDirectory,
    PostgresUnitOfWorkFactory,
)
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
from py_common.flags import configure_flags
from py_common.idempotency import IdempotencyStore, MemoryIdempotencyStore
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore
from py_common.logging import get_logger
from py_common.telemetry import Telemetry

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
    TenantDeletingError: 403,
    SessionRevokedError: 401,
    ServiceClientInvalidError: 401,
    DevSignInUnavailableError: 404,
    TenantNotFoundError: 404,
    InternalTenantExistsError: 409,
    SeatLimitReachedError: 402,
    SubscriptionStartPendingError: 409,
    DataRequestNotFoundError: 404,
    ExportNotReadyError: 409,
    TenantNotErasableError: 422,
    DeletionRequestNotFoundError: 404,
}
EXPORT_SCOPES = frozenset({Scope.DATA_EXPORT})
"""What identity's own token carries when it asks a service for a tenant's data: data:export
only, bound to that tenant and addressed to that service (no tenant:act, which would open every
tenant route of every service)."""
EXPORT_TOKEN_TTL = timedelta(minutes=2)

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


def export_sources(settings: IdentitySettings, minter: IssuerMinter) -> list[ExportSource]:
    """One ``HttpExportSource`` per service of ``CW_IDENTITY_EXPORT_SOURCES``, each sending a
    token identity mints for itself per call: data:export only, bound to the tenant exported
    and addressed to that service, for two minutes."""

    def token_for(service: str) -> Callable[[TenantId], str]:
        def token(tenant: TenantId) -> str:
            principal = Principal.service(
                SERVICE_NAME, EXPORT_SCOPES, acts_for=tenant, audience=service
            )
            return minter.mint(principal, EXPORT_TOKEN_TTL).token

        return token

    return [
        HttpExportSource(
            service,
            url,
            token=token_for(service),
            timeout_seconds=settings.identity_export_timeout_seconds,
        )
        for service, url in settings.export_sources.items()
    ]


def wire(
    settings: IdentitySettings,
    *,
    flags: FeatureFlags | None = None,
    sources: Sequence[ExportSource] | None = None,
) -> Wiring:
    """The use cases on the store the settings name. Without ``flags`` the process-wide
    OpenFeature provider is configured from the settings and answers them. Idempotency keys
    live next to the identity tables (``idempotency_key``, migration 0008). ``sources`` replace
    the export sources of the settings."""
    if flags is None:
        configure_flags(settings)
        flags = OpenFeatureFlags()
    unit_of_work: UnitOfWorkFactory
    channel_unit_of_work: ChannelUnitOfWorkFactory
    audit_reader: AuditReader
    directory: DataRequestDirectory
    idempotency: IdempotencyStore
    ping: Callable[[], bool]
    if settings.identity_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping = memory, memory.ping
        channel_unit_of_work = MemoryChannelStore()
        audit_reader = MemoryAuditReader(memory)
        directory = MemoryDataRequestDirectory(memory, utc_now)
        idempotency = MemoryIdempotencyStore()
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping
        channel_unit_of_work = postgres.channel_unit_of_work
        audit_reader = PostgresAuditReader(postgres.engine)
        directory = PostgresDataRequestDirectory(postgres.engine)
        idempotency = SqlAlchemyIdempotencyStore(postgres.engine)

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    billing = billing_provider(settings)
    free = Limits(registrations=settings.plan_free_registrations, seats=settings.plan_free_seats)
    grace = timedelta(days=settings.plan_past_due_grace_days)
    max_quantity = settings.plan_max_quantity
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
        start_subscription=None
        if billing is None
        else StartSubscription(billing, unit_of_work, max_quantity=max_quantity),
        receive_billing_webhook=None
        if billing is None
        else ReceiveBillingWebhook(billing, unit_of_work, max_quantity=max_quantity),
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
        invite_user=InviteUser(
            unit_of_work, provider, seats=SeatCheck(PLANS, free, flags, past_due_grace=grace)
        ),
        change_roles=ChangeRoles(unit_of_work),
        disable_user=DisableUser(unit_of_work),
        read_audit_trail=ReadAuditTrail(audit_reader, unit_of_work),
        read_entitlements=ReadEntitlements(unit_of_work, PLANS, free, flags, past_due_grace=grace),
        idempotency=idempotency,
        request_export=RequestExport(unit_of_work),
        request_deletion=RequestDeletion(unit_of_work),
        list_data_requests=ListDataRequests(unit_of_work),
        read_data_request=ReadDataRequest(unit_of_work),
        export_tenant_data=ExportTenantData(
            unit_of_work,
            export_sources(settings, minter) if sources is None else sources,
            concurrency=settings.identity_export_concurrency,
            deadline_seconds=settings.identity_export_deadline_seconds,
        ),
        data_request_directory=directory,
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


def install_data_request_metrics(app: FastAPI, wiring: Wiring) -> bool:
    """Register the data request gauges when telemetry is on; whether it did."""
    telemetry: Telemetry = app.state.telemetry
    if not telemetry.enabled or telemetry.meter_provider is None:
        return False
    register_data_request_gauges(
        wiring.data_request_directory,
        utc_now,
        telemetry.meter_provider.get_meter(SERVICE_NAME, __version__),
    )
    return True


def build_app(
    settings: IdentitySettings | None = None,
    *,
    flags: FeatureFlags | None = None,
    export_sources: Sequence[ExportSource] | None = None,
) -> FastAPI:
    """``flags`` replaces the OpenFeature flags and ``export_sources`` the services an export
    calls (tests and demos)."""
    settings = settings or IdentitySettings(service_name=SERVICE_NAME)
    wiring = wire(settings, flags=flags, sources=export_sources)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(ensure_dev_clients, wiring)
        yield

    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[
            router,
            auth_router,
            tenancy_router,
            audit_router,
            entitlements_router,
            data_requests_router,
        ],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        lifespan=lifespan,
        problem_status=PROBLEM_STATUS,
        authenticator=Authenticator(settings.auth_mode, token_verifier(settings, wiring.keys)),
    )
    app.state.wiring = wiring
    install_data_request_metrics(app, wiring)
    return app


def __getattr__(name: str) -> FastAPI:
    """``app`` is built on first access, so importing this module builds nothing."""
    return module_app(name, build_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("identity.main:app", host="127.0.0.1", port=8001, reload=True)
