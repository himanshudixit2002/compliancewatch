"""What the API layer gets from the composition root, typed by protocols and use cases."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from identity.application.billing import BillingLedger, ReceiveBillingWebhook, StartSubscription
from identity.application.consents import ConsentStatus, RecordConsent
from identity.domain.consent import UnitOfWorkFactory
from identity.settings import IdentitySettings


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: IdentitySettings
    unit_of_work: UnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    record_consent: RecordConsent
    consent_status: ConsentStatus
    billing_enabled: bool
    billing_ledger: BillingLedger
    start_subscription: StartSubscription | None
    receive_billing_webhook: ReceiveBillingWebhook | None
