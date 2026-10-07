"""A billing provider that lives in the process: no money moves, every call is recorded."""

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.domain.billing import (
    BillingEvent,
    Customer,
    Plan,
    Subscription,
    SubscriptionStatus,
)

MAX_KIND_CHARS = 64
MAX_PROVIDER_ID_CHARS = 64

STATUS_BY_EVENT = {
    "subscription.activated": SubscriptionStatus.ACTIVE,
    "subscription.charged": SubscriptionStatus.ACTIVE,
    "subscription.pending": SubscriptionStatus.PAST_DUE,
    "subscription.halted": SubscriptionStatus.PAST_DUE,
    "subscription.cancelled": SubscriptionStatus.CANCELLED,
    "subscription.completed": SubscriptionStatus.CANCELLED,
}


class MemoryBillingProvider:
    name = "memory"

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

    def create_subscription(
        self, customer: Customer, plan: Plan, quantity: int = 1
    ) -> Subscription:
        subscription = Subscription(
            tenant_id=customer.tenant_id,
            plan_key=plan.key,
            provider_subscription_id=f"sub_mem_{len(self.subscriptions) + 1}",
            status=SubscriptionStatus.CREATED,
            started_at=self._clock(),
            checkout_url="",
            quantity=quantity,
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
    """Razorpay's webhook shape: ``event``, ``created_at`` and ``payload.subscription.entity``
    with its ``id``, ``quantity`` and the ``notes`` this service set when it created the
    subscription (``tenant_id`` and ``plan_key``). A field that is missing or of the wrong shape
    is left out; a body that is not JSON is an event with no kind."""
    try:
        data: object = json.loads(body)
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    kind = str(data.get("event", ""))[:MAX_KIND_CHARS]
    entity = _mapping(_mapping(_mapping(data.get("payload")).get("subscription")).get("entity"))
    notes = _mapping(entity.get("notes"))
    created = data.get("created_at")
    occurred_at = (
        datetime.fromtimestamp(created, tz=now.tzinfo)
        if isinstance(created, int) and not isinstance(created, bool)
        else now
    )
    subscription_id = entity.get("id")
    quantity = entity.get("quantity")
    plan_key = notes.get("plan_key")
    return BillingEvent(
        kind=kind,
        provider_subscription_id=(
            subscription_id
            if isinstance(subscription_id, str) and len(subscription_id) <= MAX_PROVIDER_ID_CHARS
            else ""
        ),
        status=STATUS_BY_EVENT.get(kind),
        occurred_at=occurred_at,
        raw_event=body.decode("utf-8", errors="replace"),
        tenant_id=_tenant(notes.get("tenant_id")),
        plan_key=plan_key if isinstance(plan_key, str) and plan_key else None,
        quantity=(
            quantity
            if isinstance(quantity, int) and not isinstance(quantity, bool) and quantity >= 1
            else None
        ),
    )


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tenant(value: object) -> TenantId | None:
    if not isinstance(value, str):
        return None
    try:
        return TenantId.parse(value)
    except ValueError:
        return None
