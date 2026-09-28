import json
from datetime import UTC, datetime

import httpx2
import pytest

from domain_kernel.ids import TenantId
from identity.application.billing import BillingLedger, ReceiveBillingWebhook, StartSubscription
from identity.domain.billing import PLANS, BillingPeriod, Plan, SubscriptionStatus
from identity.domain.errors import InvalidWebhookSignatureError
from identity.infrastructure.billing.memory import MemoryBillingProvider, parse_subscription_event
from identity.infrastructure.billing.razorpay import (
    RazorpayBillingProvider,
    RazorpayError,
    customer_body,
    subscription_body,
)

TENANT = TenantId.new()
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


def webhook(kind: str, subscription_id: str) -> bytes:
    return json.dumps(
        {
            "event": kind,
            "created_at": 1790000000,
            "payload": {"subscription": {"entity": {"id": subscription_id, "status": "x"}}},
        }
    ).encode()


def test_plans_are_placeholders_with_zero_prices() -> None:
    assert set(PLANS) == {"owner_monthly", "ca_seat_monthly"}
    assert all(plan.amount_paise == 0 for plan in PLANS.values())
    assert all("not decided" in plan.description for plan in PLANS.values())


def test_start_subscription_reuses_the_customer_and_webhooks_move_the_status() -> None:
    provider = MemoryBillingProvider(clock=lambda: NOW)
    ledger = BillingLedger()
    start = StartSubscription(provider, ledger, clock=lambda: NOW)
    first = start.run(TENANT, "owner_monthly", email="a@b.c", name="Acme")
    second = start.run(TENANT, "ca_seat_monthly", email="a@b.c", name="Acme")
    assert len(provider.customers) == 1
    assert first.status is SubscriptionStatus.CREATED
    assert {first.provider_subscription_id, second.provider_subscription_id} == set(
        ledger.subscriptions
    )
    receive = ReceiveBillingWebhook(provider, ledger)
    body = webhook("subscription.activated", first.provider_subscription_id)
    event = receive.run(body, provider.sign(body))
    assert event.status is SubscriptionStatus.ACTIVE
    assert event.occurred_at == datetime.fromtimestamp(1790000000, tz=UTC)
    assert ledger.subscriptions[first.provider_subscription_id].status is SubscriptionStatus.ACTIVE
    unknown = webhook("payment.captured", "sub_other")
    assert receive.run(unknown, provider.sign(unknown)).status is None
    with pytest.raises(InvalidWebhookSignatureError):
        receive.run(body, "bad")
    assert len(ledger.events) == 2


def test_parse_event_tolerates_missing_fields() -> None:
    event = parse_subscription_event(b"{}", NOW)
    assert (event.kind, event.provider_subscription_id, event.status, event.occurred_at) == (
        "",
        "",
        None,
        NOW,
    )


def test_razorpay_bodies_and_signature() -> None:
    plan = Plan("owner_monthly", "x", 0, BillingPeriod.MONTHLY)
    body = customer_body(TENANT, email="a@b.c", name="Acme")
    assert body["notes"] == {"tenant_id": str(TENANT)}
    provider = RazorpayBillingProvider(
        "key",
        "secret",
        "whsec",
        plan_ids={"owner_monthly": "plan_1"},
        client=httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(500))),
    )
    raw = webhook("subscription.charged", "sub_1")
    import hashlib
    import hmac

    good = hmac.new(b"whsec", raw, hashlib.sha256).hexdigest()
    assert provider.verify_webhook(raw, good)
    assert not provider.verify_webhook(raw, "0" * 64)
    assert provider.parse_event(raw).status is SubscriptionStatus.ACTIVE
    yearly = subscription_body(
        MemoryBillingProvider().create_customer(TENANT, email="a@b.c", name="n"),
        Plan("p", "n", 0, BillingPeriod.YEARLY),
        "plan_y",
    )
    assert (yearly["plan_id"], yearly["total_count"]) == ("plan_y", 1)
    assert (
        subscription_body(
            MemoryBillingProvider().create_customer(TENANT, email="e", name="n"), plan, "plan_1"
        )["total_count"]
        == 12
    )


def test_razorpay_http_calls_go_to_the_api_with_basic_auth() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/v1/customers":
            return httpx2.Response(200, json={"id": "cust_1"})
        if request.url.path == "/v1/subscriptions":
            return httpx2.Response(200, json={"id": "sub_1", "short_url": "https://rzp.io/x"})
        return httpx2.Response(404)

    client = httpx2.Client(
        base_url="https://api.razorpay.com/v1",
        auth=("k", "s"),
        transport=httpx2.MockTransport(handler),
    )
    provider = RazorpayBillingProvider(
        "k", "s", "w", plan_ids={"owner_monthly": "plan_1"}, client=client, clock=lambda: NOW
    )
    customer = provider.create_customer(TENANT, email="a@b.c", name="Acme")
    subscription = provider.create_subscription(customer, PLANS["owner_monthly"])
    assert (customer.provider_customer_id, subscription.provider_subscription_id) == (
        "cust_1",
        "sub_1",
    )
    assert subscription.checkout_url == "https://rzp.io/x"
    assert seen[0].headers["authorization"].startswith("Basic ")
    with pytest.raises(RazorpayError, match="no Razorpay plan id"):
        provider.create_subscription(customer, PLANS["ca_seat_monthly"])
    failing = RazorpayBillingProvider(
        "k",
        "s",
        "w",
        plan_ids={},
        client=httpx2.Client(
            base_url="https://api.razorpay.com/v1",
            transport=httpx2.MockTransport(
                lambda r: httpx2.Response(401, json={"error": {"description": "bad key"}})
            ),
        ),
    )
    with pytest.raises(RazorpayError, match="401"):
        failing.create_customer(TENANT, email="a@b.c", name="Acme")
    provider.close()
