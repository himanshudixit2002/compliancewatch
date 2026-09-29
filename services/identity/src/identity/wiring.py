"""What the API layer gets from the composition root, typed by protocols and use cases."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from identity.application.billing import BillingLedger, ReceiveBillingWebhook, StartSubscription
from identity.application.channel_consents import ChannelConsentStatus, RecordChannelConsent
from identity.application.consents import ConsentStatus, RecordConsent
from identity.application.sessions import ExchangeSession, IssueServiceToken
from identity.application.tenancy import CreateTenant, CurrentUser
from identity.domain.channel_consent import ChannelUnitOfWorkFactory
from identity.domain.provider import DevIdentityProvider, IdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.settings import IdentitySettings
from py_common.auth import KeySet


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: IdentitySettings
    unit_of_work: UnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    record_consent: RecordConsent
    consent_status: ConsentStatus
    channel_unit_of_work: ChannelUnitOfWorkFactory
    record_channel_consent: RecordChannelConsent
    channel_consent_status: ChannelConsentStatus
    billing_enabled: bool
    billing_ledger: BillingLedger
    start_subscription: StartSubscription | None
    receive_billing_webhook: ReceiveBillingWebhook | None
    keys: KeySet
    provider: IdentityProvider
    dev_provider: DevIdentityProvider | None
    """The fake provider, for the dev sign-in route: set only with it in local and test."""
    exchange_session: ExchangeSession
    issue_service_token: IssueServiceToken
    create_tenant: CreateTenant
    current_user: CurrentUser
