"""Razorpay as the ``BillingProvider``: a skeleton behind ``CW_BILLING_PROVIDER=razorpay``.

What is real here and testable without an account: the webhook signature check (HMAC-SHA256
of the raw body with the webhook secret, sent as ``X-Razorpay-Signature``), the event parser,
and the request bodies for customers and subscriptions. The HTTP calls go to
``https://api.razorpay.com/v1`` with basic auth ``key_id:key_secret`` and only run when the
keys are configured; nothing creates a Razorpay account or a plan. Manual steps: create the
account, the plans matching ``identity.domain.billing.PLANS`` (note their plan ids in
``CW_RAZORPAY_PLAN_IDS``), a webhook to ``/v1/identity/billing/webhook`` with a secret, and
the API keys; then flip the flag.
"""

import hashlib
import hmac
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx2

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.domain.billing import (
    BillingEvent,
    BillingPeriod,
    Customer,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from identity.infrastructure.billing.memory import parse_subscription_event

BASE_URL = "https://api.razorpay.com/v1"


class RazorpayError(RuntimeError):
    """Razorpay refused or failed a call; the body is its error object."""


class RazorpayBillingProvider:
    def __init__(
        self,
        key_id: str,
        key_secret: str,
        webhook_secret: str,
        *,
        plan_ids: Mapping[str, str],
        client: httpx2.Client | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client or httpx2.Client(
            base_url=BASE_URL, auth=(key_id, key_secret), timeout=30.0
        )
        self._webhook_secret = webhook_secret
        self._plan_ids = dict(plan_ids)
        self._clock = clock

    def create_customer(self, tenant_id: TenantId, *, email: str, name: str) -> Customer:
        data = self._post("/customers", customer_body(tenant_id, email=email, name=name))
        return Customer(tenant_id, str(data["id"]), email, name)

    def create_subscription(self, customer: Customer, plan: Plan) -> Subscription:
        plan_id = self._plan_ids.get(plan.key)
        if plan_id is None:
            raise RazorpayError(f"no Razorpay plan id configured for {plan.key}")
        data = self._post("/subscriptions", subscription_body(customer, plan, plan_id))
        return Subscription(
            tenant_id=customer.tenant_id,
            plan_key=plan.key,
            provider_subscription_id=str(data["id"]),
            status=SubscriptionStatus.CREATED,
            started_at=self._clock(),
            checkout_url=str(data.get("short_url", "")),
        )

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        expected = hmac.new(self._webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip())

    def parse_event(self, body: bytes) -> BillingEvent:
        return parse_subscription_event(body, self._clock())

    def close(self) -> None:
        self._client.close()

    def _post(self, path: str, body: Mapping[str, object]) -> Mapping[str, object]:
        response = self._client.post(path, json=body)
        if response.status_code >= 400:
            raise RazorpayError(f"{response.status_code}: {response.text[:300]}")
        data = response.json()
        if not isinstance(data, Mapping):
            raise RazorpayError("unexpected response shape")
        return data


def customer_body(tenant_id: TenantId, *, email: str, name: str) -> dict[str, object]:
    return {
        "name": name,
        "email": email,
        "fail_existing": "0",
        "notes": {"tenant_id": str(tenant_id)},
    }


def subscription_body(customer: Customer, plan: Plan, plan_id: str) -> dict[str, object]:
    return {
        "plan_id": plan_id,
        "customer_id": customer.provider_customer_id,
        "total_count": 12 if plan.period is BillingPeriod.MONTHLY else 1,
        "quantity": 1,
        "customer_notify": 1,
        "notes": {"tenant_id": str(customer.tenant_id), "plan_key": plan.key},
    }
