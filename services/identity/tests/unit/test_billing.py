import json
from contextlib import AbstractContextManager
from datetime import UTC, datetime

import httpx2
import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from identity.application.billing import (
    ReceiveBillingWebhook,
    StartSubscription,
    masked_payload,
)
from identity.domain.billing import (
    PLANS,
    REGISTRATIONS,
    SEATS,
    BillingPeriod,
    Plan,
    SubscriptionStatus,
)
from identity.domain.errors import InvalidWebhookSignatureError
from identity.domain.repository import UnitOfWork
from identity.infrastructure.billing.memory import MemoryBillingProvider, parse_subscription_event
from identity.infrastructure.billing.razorpay import (
    RazorpayBillingProvider,
    RazorpayError,
    customer_body,
    subscription_body,
)
from identity.infrastructure.memory import MemoryStore

TENANT = TenantId.new()
NOW = datetime(2000, 6, 1, 10, 0, tzinfo=UTC)


def webhook(
    kind: str,
    subscription_id: str,
    *,
    tenant: TenantId | None = TENANT,
    plan_key: str | None = None,
    quantity: int | None = None,
    created_at: int = 946_684_800,
) -> bytes:
    """A Razorpay-shaped webhook; the notes echo the tenant (and plan) the subscription named."""
    notes: dict[str, str] = {}
    if tenant is not None:
        notes["tenant_id"] = str(tenant)
    if plan_key is not None:
        notes["plan_key"] = plan_key
    entity: dict[str, object] = {"id": subscription_id, "status": "x", "notes": notes}
    if quantity is not None:
        entity["quantity"] = quantity
    return json.dumps(
        {"event": kind, "created_at": created_at, "payload": {"subscription": {"entity": entity}}}
    ).encode()


def test_plans_are_placeholders_with_zero_prices_and_limits() -> None:
    assert set(PLANS) == {"owner_monthly", "ca_seat_monthly"}
    assert all(plan.amount_paise == 0 for plan in PLANS.values())
    assert all("not decided" in plan.description for plan in PLANS.values())
    owner = PLANS["owner_monthly"]
    assert owner.limit(REGISTRATIONS, 2) == 2 * owner.limit(REGISTRATIONS, 1)  # type: ignore[operator]
    assert Plan("p", "n", 0, BillingPeriod.MONTHLY).limit(SEATS, 3) is None
    with pytest.raises(InvariantViolationError, match="unknown limit"):
        Plan("p", "n", 0, BillingPeriod.MONTHLY, limits={"widgets": 1})


def test_start_subscription_reuses_the_customer_and_webhooks_move_the_status() -> None:
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    start = StartSubscription(provider, store, clock=lambda: NOW)
    first = start.run(TENANT, "owner_monthly", email="owner@example.com", name="Example Traders")
    second = start.run(
        TENANT, "ca_seat_monthly", email="owner@example.com", name="Example Traders", quantity=3
    )
    assert len(provider.customers) == 1
    assert first.status is SubscriptionStatus.CREATED
    assert (second.quantity, first.updated_at) == (3, NOW)
    with store(TENANT) as uow:
        held = {s.provider_subscription_id for s in uow.billing.subscriptions()}
        assert held == {first.provider_subscription_id, second.provider_subscription_id}
        customer = uow.billing.customer()
    assert customer is not None
    assert store.billing.customers[TENANT][1] == "memory"
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW)
    body = webhook("subscription.activated", first.provider_subscription_id, quantity=2)
    receipt = receive.run(body, provider.sign(body))
    assert not receipt.ignored
    assert not receipt.duplicate
    assert receipt.event.status is SubscriptionStatus.ACTIVE
    assert receipt.event.occurred_at == datetime(2000, 1, 1, tzinfo=UTC)
    with store(TENANT) as uow:
        activated = uow.billing.subscription(first.provider_subscription_id)
    assert activated is not None
    assert (activated.status, activated.quantity) == (SubscriptionStatus.ACTIVE, 2)
    unknown = webhook("payment.captured", "sub_other")
    assert receive.run(unknown, provider.sign(unknown)).event.status is None
    with pytest.raises(InvalidWebhookSignatureError):
        receive.run(body, "bad")
    assert len(store.billing.events) == 2
    repeated = receive.run(body, provider.sign(body))
    assert repeated.duplicate
    assert len(store.billing.events) == 2

    started = [entry for entry in store.audit if entry.action == "subscription.started"]
    assert [(entry.tenant_id, entry.subject_id) for entry in started] == [
        (TENANT, first.provider_subscription_id),
        (TENANT, second.provider_subscription_id),
    ]
    assert started[0].after == {"plan_key": "owner_monthly", "status": "created", "quantity": 1}
    [changed] = [entry for entry in store.audit if entry.action == "subscription.status_changed"]
    assert changed.tenant_id == TENANT
    assert changed.subject_id == first.provider_subscription_id
    assert (changed.actor.label, changed.reason) == (
        "system:billing-webhook",
        "subscription.activated",
    )
    assert (changed.before, changed.after) == (
        {"status": "created", "quantity": 1},
        {"status": "active", "quantity": 2},
    )


def test_a_webhook_without_a_tenant_is_ignored_and_one_of_another_tenant_changes_nothing() -> None:
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    subscription = StartSubscription(provider, store, clock=lambda: NOW).run(
        TENANT, "owner_monthly", email="owner@example.com", name="Example Traders"
    )
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW)
    anonymous = webhook(
        "subscription.activated", subscription.provider_subscription_id, tenant=None
    )
    assert receive.run(anonymous, provider.sign(anonymous)).ignored
    assert store.billing.events == []
    other = TenantId.new()
    foreign = webhook("subscription.activated", subscription.provider_subscription_id, tenant=other)
    receipt = receive.run(foreign, provider.sign(foreign))
    assert not receipt.ignored
    assert [event.tenant_id for event in store.billing.events] == [other]
    with store(TENANT) as uow:
        held = uow.billing.subscription(subscription.provider_subscription_id)
    assert held is not None
    assert held.status is SubscriptionStatus.CREATED, "another tenant's webhook moves nothing"


def test_the_stored_payload_is_masked() -> None:
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "subscription": {"entity": {"id": "sub_x", "notes": {"tenant_id": str(TENANT)}}},
                "payment": {"entity": {"email": "owner@example.com", "contact": "+919876543210"}},
            },
        }
    ).encode()
    ReceiveBillingWebhook(provider, store, clock=lambda: NOW).run(body, provider.sign(body))
    [stored] = store.billing.events
    payment = stored.raw_event["payload"]["payment"]["entity"]  # type: ignore[index]
    assert payment == {"email": "[EMAIL]", "contact": "[PHONE]"}
    assert stored.raw_event["payload"]["subscription"]["entity"]["notes"] == {  # type: ignore[index]
        "tenant_id": str(TENANT)
    }
    assert masked_payload(b"not json owner@example.com") == {"body": "not json [EMAIL]"}


def test_a_failed_ledger_write_is_recovered_by_the_first_webhook() -> None:
    """The provider created the subscription but the ledger's transaction failed: the first
    webhook, whose notes name the tenant and the plan, records it and audits it."""
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    calls = 0

    def failing_second(tenant_id: TenantId | None) -> AbstractContextManager[UnitOfWork]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("the database is down")
        return store(tenant_id)

    start = StartSubscription(provider, failing_second, clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="database is down"):
        start.run(TENANT, "owner_monthly", email="owner@example.com", name="Example Traders")
    [created] = provider.subscriptions
    with store(TENANT) as uow:
        assert uow.billing.subscriptions() == []
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW)
    body = webhook(
        "subscription.activated", created.provider_subscription_id, plan_key="owner_monthly"
    )
    receive.run(body, provider.sign(body))
    with store(TENANT) as uow:
        adopted = uow.billing.subscription(created.provider_subscription_id)
    assert adopted is not None
    assert (adopted.plan_key, adopted.status) == ("owner_monthly", SubscriptionStatus.ACTIVE)
    [entry] = [entry for entry in store.audit if entry.action == "subscription.started"]
    assert (entry.actor.label, entry.subject_id) == (
        "system:billing-webhook",
        created.provider_subscription_id,
    )


def test_parse_event_tolerates_missing_fields() -> None:
    for body in (b"{}", b"[]", b"not json"):
        event = parse_subscription_event(body, NOW)
        assert (event.kind, event.provider_subscription_id, event.status, event.occurred_at) == (
            "",
            "",
            None,
            NOW,
        )
        assert (event.tenant_id, event.plan_key, event.quantity) == (None, None, None)
    odd = parse_subscription_event(
        json.dumps(
            {
                "event": "subscription.activated",
                "created_at": True,
                "payload": {
                    "subscription": {
                        "entity": {"id": "s" * 65, "quantity": 0, "notes": {"tenant_id": "x"}}
                    }
                },
            }
        ).encode(),
        NOW,
    )
    assert (odd.provider_subscription_id, odd.quantity, odd.tenant_id, odd.occurred_at) == (
        "",
        None,
        None,
        NOW,
    )


def test_razorpay_bodies_and_signature() -> None:
    plan = Plan("owner_monthly", "x", 0, BillingPeriod.MONTHLY)
    body = customer_body(TENANT, email="owner@example.com", name="Example Traders")
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
        MemoryBillingProvider().create_customer(TENANT, email="owner@example.com", name="n"),
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
    assert (
        subscription_body(
            MemoryBillingProvider().create_customer(TENANT, email="e", name="n"),
            plan,
            "plan_1",
            quantity=4,
        )["quantity"]
        == 4
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
    customer = provider.create_customer(TENANT, email="owner@example.com", name="Example Traders")
    subscription = provider.create_subscription(customer, PLANS["owner_monthly"], 2)
    assert (customer.provider_customer_id, subscription.provider_subscription_id) == (
        "cust_1",
        "sub_1",
    )
    assert (subscription.checkout_url, subscription.quantity) == ("https://rzp.io/x", 2)
    assert json.loads(seen[1].content)["quantity"] == 2
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
        failing.create_customer(TENANT, email="owner@example.com", name="Example Traders")
    provider.close()
