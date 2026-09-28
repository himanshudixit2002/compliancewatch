"""A billing provider that lives in the process: no money moves, every call is recorded."""

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.domain.billing import (
    BillingEvent,
    Customer,
    Plan,
    Subscription,
    SubscriptionStatus,
)

STATUS_BY_EVENT = {
    "subscription.activated": SubscriptionStatus.ACTIVE,
    "subscription.charged": SubscriptionStatus.ACTIVE,
    "subscription.pending": SubscriptionStatus.PAST_DUE,
    "subscription.halted": SubscriptionStatus.PAST_DUE,
    "subscription.cancelled": SubscriptionStatus.CANCELLED,
    "subscription.completed": SubscriptionStatus.CANCELLED,
}


class MemoryBillingProvider:
    def __init__(
        self, webhook_secret: str = "memory", *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._secret = webhook_secret
        self._clock = clock
        self.customers: list[Customer] = []
        self.subscriptions: list[Subscription] = []

    def create_customer(self, tenant_id: TenantId, *, email: str, name: str) -> Customer:
        customer = Customer(tenant_id, f"cust_mem_{len(self.customers) + 1}", email, name)
        self.customers.append(customer)
        return customer

    def create_subscription(self, customer: Customer, plan: Plan) -> Subscription:
        subscription = Subscription(
            tenant_id=customer.tenant_id,
            plan_key=plan.key,
            provider_subscription_id=f"sub_mem_{len(self.subscriptions) + 1}",
            status=SubscriptionStatus.CREATED,
            started_at=self._clock(),
            checkout_url="",
        )
        self.subscriptions.append(subscription)
        return subscription

    def sign(self, body: bytes) -> str:
        return hmac.new(self._secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(body), signature)

    def parse_event(self, body: bytes) -> BillingEvent:
        return parse_subscription_event(body, self._clock())


def parse_subscription_event(body: bytes, now: datetime) -> BillingEvent:
    """Razorpay's webhook shape: ``event`` and ``payload.subscription.entity.id``."""
    data = json.loads(body)
    kind = str(data.get("event", ""))
    payload = data.get("payload", {}) if isinstance(data, dict) else {}
    subscription = (
        payload.get("subscription", {}).get("entity", {}) if isinstance(payload, dict) else {}
    )
    created = data.get("created_at") if isinstance(data, dict) else None
    occurred_at = (
        datetime.fromtimestamp(int(created), tz=now.tzinfo) if isinstance(created, int) else now
    )
    return BillingEvent(
        kind=kind,
        provider_subscription_id=str(subscription.get("id", "")),
        status=STATUS_BY_EVENT.get(kind),
        occurred_at=occurred_at,
        raw_event=body.decode("utf-8", errors="replace"),
    )
