"""Composition root for the identity service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
Consent records are the first thing this service owns (tenants and users arrive with Supabase
Auth per ADR-014). Billing is behind ``CW_BILLING_PROVIDER``.
"""

from collections.abc import Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError
from identity import __version__
from identity.api.router import router
from identity.application.billing import BillingLedger, ReceiveBillingWebhook, StartSubscription
from identity.application.consents import ConsentStatus, RecordConsent
from identity.domain.billing import BillingProvider
from identity.domain.consent import UnitOfWorkFactory
from identity.domain.errors import (
    BillingDisabledError,
    InvalidWebhookSignatureError,
    NoticeVersionRequiredError,
    TenantRequiredError,
)
from identity.infrastructure.billing.memory import MemoryBillingProvider
from identity.infrastructure.billing.razorpay import RazorpayBillingProvider
from identity.infrastructure.memory import MemoryStore
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from identity.settings import IdentitySettings
from identity.wiring import Wiring
from py_common.app import create_app

SERVICE_NAME = "identity"
PROBLEM_STATUS: dict[type[DomainError], int] = {
    TenantRequiredError: 401,
    NoticeVersionRequiredError: 422,
    BillingDisabledError: 503,
    InvalidWebhookSignatureError: 401,
}


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


def wire(settings: IdentitySettings) -> Wiring:
    unit_of_work: UnitOfWorkFactory
    ping: Callable[[], bool]
    if settings.identity_store == "memory":
        memory = MemoryStore()
        unit_of_work, ping = memory, memory.ping
    else:
        postgres = PostgresUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    provider = billing_provider(settings)
    ledger = BillingLedger()
    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        record_consent=RecordConsent(unit_of_work),
        consent_status=ConsentStatus(unit_of_work),
        billing_enabled=provider is not None,
        billing_ledger=ledger,
        start_subscription=None if provider is None else StartSubscription(provider, ledger),
        receive_billing_webhook=None
        if provider is None
        else ReceiveBillingWebhook(provider, ledger),
    )


def build_app(settings: IdentitySettings | None = None) -> FastAPI:
    settings = settings or IdentitySettings(service_name=SERVICE_NAME)
    wiring = wire(settings)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        problem_status=PROBLEM_STATUS,
    )
    app.state.wiring = wiring
    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("identity.main:app", host="127.0.0.1", port=8001, reload=True)
