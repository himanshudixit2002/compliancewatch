"""Start a subscription and take in a provider webhook, through the ``BillingProvider``."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.domain.billing import (
    PLANS,
    BillingEvent,
    BillingProvider,
    Customer,
    Plan,
    Subscription,
)
from identity.domain.errors import InvalidWebhookSignatureError


@dataclass
class BillingLedger:
    """What the service remembers about billing until its own table lands: in memory."""

    customers: dict[TenantId, Customer] = field(default_factory=dict)
    subscriptions: dict[str, Subscription] = field(default_factory=dict)
    events: list[BillingEvent] = field(default_factory=list)


class StartSubscription:
    def __init__(
        self,
        provider: BillingProvider,
        ledger: BillingLedger,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._provider = provider
        self._ledger = ledger
        self._clock = clock

    def run(self, tenant_id: TenantId, plan_key: str, *, email: str, name: str) -> Subscription:
        plan: Plan = PLANS[plan_key]
        customer = self._ledger.customers.get(tenant_id)
        if customer is None:
            customer = self._provider.create_customer(tenant_id, email=email, name=name)
            self._ledger.customers[tenant_id] = customer
        subscription = self._provider.create_subscription(customer, plan)
        self._ledger.subscriptions[subscription.provider_subscription_id] = subscription
        return subscription


class ReceiveBillingWebhook:
    def __init__(self, provider: BillingProvider, ledger: BillingLedger) -> None:
        self._provider = provider
        self._ledger = ledger

    def run(self, body: bytes, signature: str) -> BillingEvent:
        if not self._provider.verify_webhook(body, signature):
            raise InvalidWebhookSignatureError()
        event = self._provider.parse_event(body)
        self._ledger.events.append(event)
        current = self._ledger.subscriptions.get(event.provider_subscription_id)
        if current is not None and event.status is not None:
            self._ledger.subscriptions[event.provider_subscription_id] = Subscription(
                tenant_id=current.tenant_id,
                plan_key=current.plan_key,
                provider_subscription_id=current.provider_subscription_id,
                status=event.status,
                started_at=current.started_at,
                checkout_url=current.checkout_url,
            )
        return event
