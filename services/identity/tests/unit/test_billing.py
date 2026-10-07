import hashlib
import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from itertools import count

import httpx2
import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from identity.application.billing import (
    ReceiveBillingWebhook,
    StartSubscription,
    projected_payload,
)
from identity.domain.billing import (
    PLANS,
    REGISTRATIONS,
    SEATS,
    BillingPeriod,
    Customer,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from identity.domain.errors import InvalidWebhookSignatureError, SubscriptionStartPendingError
from identity.domain.repository import UnitOfWork, UnitOfWorkFactory
from identity.domain.tenancy import Tenant, TenantKind
from identity.infrastructure.billing.memory import MemoryBillingProvider, parse_subscription_event
from identity.infrastructure.billing.razorpay import (
    RazorpayBillingProvider,
    RazorpayError,
    RazorpayRefusedError,
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
    customer_id: str | None = None,
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
    if customer_id is not None:
        entity["customer_id"] = customer_id
    return json.dumps(
        {"event": kind, "created_at": created_at, "payload": {"subscription": {"entity": entity}}}
    ).encode()


def keys() -> Iterator[str]:
    for number in count(1):
        yield f"example-key-{number:04d}"


KEYS = keys()


def with_tenant(store: MemoryStore, tenant: TenantId = TENANT) -> MemoryStore:
    """``store`` with a business tenant ``tenant``: a webhook adopts only a tenant that exists."""
    with store(tenant) as uow:
        uow.tenants.add(Tenant(tenant, TenantKind.BUSINESS, "Example Traders", NOW))
    return store


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
    first = start.run(
        TENANT, "owner_monthly", key=next(KEYS), email="owner@example.com", name="Example Traders"
    )
    second = start.run(
        TENANT,
        "ca_seat_monthly",
        key=next(KEYS),
        email="owner@example.com",
        name="Example Traders",
        quantity=3,
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
    unmatched = receive.run(unknown, provider.sign(unknown))
    assert (unmatched.event.status, unmatched.ignored) == (None, True)
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
    """m1: a webhook naming another tenant for a subscription id is stored under that tenant,
    audited as unmatched and answered as ignored; the holder's row never moves."""
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    subscription = StartSubscription(provider, store, clock=lambda: NOW).run(
        TENANT, "owner_monthly", key=next(KEYS), email="owner@example.com", name="Example Traders"
    )
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW)
    anonymous = webhook(
        "subscription.activated", subscription.provider_subscription_id, tenant=None
    )
    assert receive.run(anonymous, provider.sign(anonymous)).ignored
    assert store.billing.events == []
    other = TenantId.new()
    with_tenant(store, other)
    with store(other) as uow:  # even with a customer of its own, other cannot take the id
        uow.billing.add_customer(
            Customer(other, "cust_other", "other@example.com", "Example Other"),
            provider="memory",
            at=NOW,
        )
    foreign = webhook(
        "subscription.activated",
        subscription.provider_subscription_id,
        tenant=other,
        plan_key="owner_monthly",
        customer_id="cust_other",
    )
    receipt = receive.run(foreign, provider.sign(foreign))
    assert receipt.ignored
    assert [event.tenant_id for event in store.billing.events] == [other]
    [unmatched] = [entry for entry in store.audit if entry.action == "subscription.unmatched"]
    assert (unmatched.tenant_id, unmatched.actor.label) == (other, "system:billing-webhook")
    assert store.billing.subscriptions[subscription.provider_subscription_id].tenant_id == TENANT
    with store(TENANT) as uow:
        held = uow.billing.subscription(subscription.provider_subscription_id)
    assert held is not None
    assert held.status is SubscriptionStatus.CREATED, "another tenant's webhook moves nothing"


def test_the_stored_payload_is_an_allowlisted_projection() -> None:
    """M3: names, contacts, VPAs, addresses, card and bank details never reach the ledger, even
    where the masker would not recognise them; the ids, status, plan, quantity, times, amounts
    and currency are kept."""
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    body = json.dumps(
        {
            "entity": "event",
            "account_id": "acc_example",
            "event": "subscription.charged",
            "created_at": 946_684_800,
            "contains": ["subscription", "payment"],
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_x",
                        "customer_id": "cust_x",
                        "plan_id": "plan_x",
                        "status": "active",
                        "quantity": 2,
                        "current_start": 946_684_800,
                        "notes": {
                            "tenant_id": str(TENANT),
                            "plan_key": "owner_monthly",
                            "contact_person": "Example Person",
                        },
                    }
                },
                "payment": {
                    "entity": {
                        "id": "pay_x",
                        "amount": 49_900,
                        "currency": "INR",
                        "status": "captured",
                        "email": "owner@example.com",
                        "contact": 9876543210,
                        "vpa": "example.person@okexample",
                        "card": {"name": "Example Person", "last4": "1111"},
                        "bank_account": {"account_number": "000011112222"},
                        "billing_address": {"line1": "1 Example Road"},
                        "notes": {"name": "Example Person"},
                    }
                },
            },
        }
    ).encode()
    ReceiveBillingWebhook(provider, store, clock=lambda: NOW).run(
        body, provider.sign(body), event_id="evt_example"
    )
    [stored] = store.billing.events
    assert stored.raw_event == {
        "event_id": "evt_example",
        "event": "subscription.charged",
        "created_at": 946_684_800,
        "account_id": "acc_example",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_x",
                    "customer_id": "cust_x",
                    "plan_id": "plan_x",
                    "status": "active",
                    "quantity": 2,
                    "current_start": 946_684_800,
                    "notes": {"tenant_id": str(TENANT), "plan_key": "owner_monthly"},
                }
            },
            "payment": {
                "entity": {"id": "pay_x", "amount": 49_900, "currency": "INR", "status": "captured"}
            },
        },
    }
    assert stored.body_sha256 == hashlib.sha256(body).hexdigest()
    assert projected_payload(b"not json owner@example.com") == {}
    masked = projected_payload(json.dumps({"event": "owner@example.com"}).encode())
    assert masked == {"event": "[EMAIL]"}, "the projection is masked as well"


def test_a_failed_ledger_write_is_recovered_by_the_first_webhook() -> None:
    """The provider created the subscription but the ledger's transaction failed: the first
    webhook, whose customer is the tenant's stored customer, records it and audits it."""
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = with_tenant(MemoryStore())
    start = StartSubscription(provider, failing_at(store, 3), clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="database is down"):
        start.run(
            TENANT,
            "owner_monthly",
            key=next(KEYS),
            email="owner@example.com",
            name="Example Traders",
        )
    [created] = provider.subscriptions
    [customer] = provider.customers
    with store(TENANT) as uow:
        assert uow.billing.subscriptions() == []
        assert uow.billing.customer() == customer, "the customer is stored before the start"
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW)
    body = webhook(
        "subscription.activated",
        created.provider_subscription_id,
        plan_key="owner_monthly",
        customer_id=customer.provider_customer_id,
    )
    assert not receive.run(body, provider.sign(body)).ignored
    with store(TENANT) as uow:
        adopted = uow.billing.subscription(created.provider_subscription_id)
    assert adopted is not None
    assert (adopted.plan_key, adopted.status) == ("owner_monthly", SubscriptionStatus.ACTIVE)
    [entry] = [entry for entry in store.audit if entry.action == "subscription.started"]
    assert (entry.actor.label, entry.subject_id) == (
        "system:billing-webhook",
        created.provider_subscription_id,
    )


def failing_at(store: MemoryStore, *failing: int) -> UnitOfWorkFactory:
    """``store``'s unit of work, except that the units numbered in ``failing`` (from 1) fail
    to open."""
    calls = 0

    def open_unit(tenant_id: TenantId | None) -> AbstractContextManager[UnitOfWork]:
        nonlocal calls
        calls += 1
        if calls in failing:
            raise RuntimeError("the database is down")
        return store(tenant_id)

    return open_unit


@pytest.mark.parametrize(
    ("failing", "retried"),
    [
        (1, "started"),  # the start was never recorded: the retry starts it
        (2, "started"),  # storing the customer failed before the subscription: released
        (3, "pending"),  # the provider's answer was not noted: never asked again
        (4, "recorded"),  # the ledger write failed: the retry records the noted answer
    ],
)
def test_one_key_never_makes_two_provider_subscriptions(failing: int, retried: str) -> None:
    """M1: a start that fails at any of its transactions, retried with the same key, asks the
    provider for one subscription at most."""
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    key = next(KEYS)
    start = StartSubscription(provider, failing_at(store, failing), clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="database is down"):
        start.run(
            TENANT, "owner_monthly", key=key, email="owner@example.com", name="Example Traders"
        )
    if retried == "pending":
        with pytest.raises(SubscriptionStartPendingError):
            start.run(
                TENANT, "owner_monthly", key=key, email="owner@example.com", name="Example Traders"
            )
        assert len(provider.subscriptions) == 1
        return
    again = start.run(
        TENANT, "owner_monthly", key=key, email="owner@example.com", name="Example Traders"
    )
    assert len(provider.subscriptions) == 1
    [created] = provider.subscriptions
    assert again.provider_subscription_id == created.provider_subscription_id
    assert (
        start.run(
            TENANT, "owner_monthly", key=key, email="owner@example.com", name="Example Traders"
        )
        == again
    ), "and again: the same"
    assert len(provider.subscriptions) == 1
    with store(TENANT) as uow:
        assert [s.provider_subscription_id for s in uow.billing.subscriptions()] == [
            created.provider_subscription_id
        ]
    started = [entry for entry in store.audit if entry.action == "subscription.started"]
    assert len(started) == 1


class FlakyProvider(MemoryBillingProvider):
    """Creates the subscription, then fails as a timeout would (``error``)."""

    def __init__(self, error: Exception) -> None:
        super().__init__(clock=lambda: NOW)
        self.error: Exception | None = error

    def create_subscription(
        self, customer: Customer, plan: Plan, quantity: int = 1
    ) -> Subscription:
        if self.error is not None:
            error, self.error = self.error, None
            if not isinstance(error, RazorpayRefusedError):
                super().create_subscription(customer, plan, quantity)
            raise error
        return super().create_subscription(customer, plan, quantity)


def test_a_provider_timeout_keeps_the_key_and_a_refusal_frees_it() -> None:
    timed_out = FlakyProvider(RazorpayError("timed out"))
    start = StartSubscription(timed_out, MemoryStore(), clock=lambda: NOW)
    key = next(KEYS)
    with pytest.raises(RazorpayError):
        start.run(
            TENANT, "owner_monthly", key=key, email="owner@example.com", name="Example Traders"
        )
    with pytest.raises(SubscriptionStartPendingError):
        start.run(
            TENANT, "owner_monthly", key=key, email="owner@example.com", name="Example Traders"
        )
    assert len(timed_out.subscriptions) == 1
    refused = FlakyProvider(RazorpayRefusedError("400: bad request"))
    start = StartSubscription(refused, MemoryStore(), clock=lambda: NOW)
    with pytest.raises(RazorpayRefusedError):
        start.run(
            TENANT, "owner_monthly", key=key, email="owner@example.com", name="Example Traders"
        )
    retried = start.run(
        TENANT, "owner_monthly", key=key, email="owner@example.com", name="Example Traders"
    )
    assert [s.provider_subscription_id for s in refused.subscriptions] == [
        retried.provider_subscription_id
    ]


def test_a_late_event_never_undoes_a_newer_one_and_cancelled_is_final() -> None:
    """M2: activated (t=10), cancelled (t=30), then a late charged (t=20): cancelled stays, and
    the late event is stored and audited as ignored. A later activation cannot revive it."""
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    started = StartSubscription(provider, store, clock=lambda: NOW).run(
        TENANT, "owner_monthly", key=next(KEYS), email="owner@example.com", name="Example Traders"
    )
    sid = started.provider_subscription_id
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW)
    answers = []
    for kind, at in (
        ("subscription.activated", 10),
        ("subscription.cancelled", 30),
        ("subscription.charged", 20),
        ("subscription.activated", 40),
    ):
        body = webhook(kind, sid, created_at=946_684_800 + at)
        answers.append(receive.run(body, provider.sign(body)).ignored)
    assert answers == [False, False, True, True]
    with store(TENANT) as uow:
        held = uow.billing.subscription(sid)
    assert held is not None
    assert held.status is SubscriptionStatus.CANCELLED
    assert len(store.billing.events) == 4
    ignored = [entry for entry in store.audit if entry.action == "subscription.event_ignored"]
    assert [entry.reason.split(":")[0] for entry in ignored] == [
        "subscription.charged",
        "subscription.activated",
    ]


def test_an_older_event_is_ignored_while_active() -> None:
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    sid = (
        StartSubscription(provider, store, clock=lambda: NOW)
        .run(TENANT, "owner_monthly", key=next(KEYS), email="owner@example.com", name="n")
        .provider_subscription_id
    )
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW)
    newer = webhook("subscription.charged", sid, created_at=946_684_830)
    older = webhook("subscription.pending", sid, created_at=946_684_820)
    receive.run(newer, provider.sign(newer))
    assert receive.run(older, provider.sign(older)).ignored
    with store(TENANT) as uow:
        held = uow.billing.subscription(sid)
    assert held is not None
    assert (held.status, held.last_event_at) == (
        SubscriptionStatus.ACTIVE,
        datetime.fromtimestamp(946_684_830, tz=UTC),
    )


def test_a_webhook_never_creates_a_subscription_from_its_notes_alone() -> None:
    """M4: an unknown subscription id is adopted only for a tenant that exists and whose stored
    customer is the payload's; its quantity is kept within bounds."""
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW, max_quantity=1000)
    stranger = TenantId.new()

    def send(tenant: TenantId, sid: str, customer: str | None) -> bool:
        body = webhook(
            "subscription.activated",
            sid,
            tenant=tenant,
            plan_key="owner_monthly",
            quantity=1_000_000,
            customer_id=customer,
        )
        return receive.run(body, provider.sign(body)).ignored

    assert send(stranger, "sub_forged", "cust_forged"), "no tenant, no customer"
    with_tenant(store, stranger)
    assert send(stranger, "sub_forged_2", None), "a tenant without a customer"
    with store(stranger) as uow:
        uow.billing.add_customer(
            Customer(stranger, "cust_mine", "owner@example.com", "Example Traders"),
            provider="memory",
            at=NOW,
        )
    assert send(stranger, "sub_forged_3", "cust_other"), "another customer"
    assert store.billing.subscriptions == {}
    unmatched = [entry for entry in store.audit if entry.action == "subscription.unmatched"]
    assert len(unmatched) == 3
    assert not send(stranger, "sub_mine", "cust_mine")
    assert store.billing.subscriptions["sub_mine"].quantity == 1000, "clamped"
    with store(stranger) as uow:
        assert uow.billing.customer() is not None
    orphan = TenantId.new()  # a customer stored but no tenant row: not adopted
    with store(orphan) as uow:
        uow.billing.add_customer(
            Customer(orphan, "cust_orphan", "owner@example.com", "n"), provider="memory", at=NOW
        )
    assert send(orphan, "sub_orphan", "cust_orphan")


def test_quantities_are_clamped_on_start_and_on_change() -> None:
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    started = StartSubscription(provider, store, clock=lambda: NOW, max_quantity=50).run(
        TENANT, "owner_monthly", key=next(KEYS), email="owner@example.com", name="n", quantity=999
    )
    assert started.quantity == 50
    body = webhook("subscription.charged", started.provider_subscription_id, quantity=2**40)
    ReceiveBillingWebhook(provider, store, clock=lambda: NOW, max_quantity=50).run(
        body, provider.sign(body)
    )
    assert store.billing.subscriptions[started.provider_subscription_id].quantity == 50


class AdoptingProvider(MemoryBillingProvider):
    """Delivers the activation webhook before the start's own ledger write, as a fast checkout
    would."""

    def __init__(self, store: MemoryStore) -> None:
        super().__init__(clock=lambda: NOW)
        self.store = store

    def create_subscription(
        self, customer: Customer, plan: Plan, quantity: int = 1
    ) -> Subscription:
        created = super().create_subscription(customer, plan, quantity)
        body = webhook(
            "subscription.activated",
            created.provider_subscription_id,
            plan_key=plan.key,
            customer_id=customer.provider_customer_id,
        )
        ReceiveBillingWebhook(self, self.store, clock=lambda: NOW).run(body, self.sign(body))
        return created


def test_a_start_never_overwrites_what_an_earlier_webhook_recorded() -> None:
    """m2: the webhook adopted the subscription before the start's ledger write; the start
    leaves it active and writes no second subscription.started."""
    store = with_tenant(MemoryStore())
    provider = AdoptingProvider(store)
    started = StartSubscription(provider, store, clock=lambda: NOW).run(
        TENANT, "owner_monthly", key=next(KEYS), email="owner@example.com", name="n"
    )
    assert started.status is SubscriptionStatus.ACTIVE
    started_entries = [e for e in store.audit if e.action == "subscription.started"]
    assert [e.actor.label for e in started_entries] == ["system:billing-webhook"]


class RacingProvider(MemoryBillingProvider):
    """While the first start makes its customer, a second start of the tenant runs to the end."""

    def __init__(self, store: MemoryStore) -> None:
        super().__init__(clock=lambda: NOW)
        self.store = store
        self.raced = False

    def create_customer(self, tenant_id: TenantId, *, email: str, name: str) -> Customer:
        if not self.raced:
            self.raced = True
            StartSubscription(self, self.store, clock=lambda: NOW).run(
                tenant_id, "owner_monthly", key=next(KEYS), email=email, name=name
            )
        return super().create_customer(tenant_id, email=email, name=name)


def test_two_first_starts_keep_one_customer() -> None:
    store = MemoryStore()
    provider = RacingProvider(store)
    StartSubscription(provider, store, clock=lambda: NOW).run(
        TENANT, "ca_seat_monthly", key=next(KEYS), email="owner@example.com", name="n"
    )
    with store(TENANT) as uow:
        customer = uow.billing.customer()
        held = uow.billing.subscriptions()
    assert customer is not None
    assert customer.provider_customer_id == provider.customers[0].provider_customer_id
    assert len(held) == 2
    assert {s.plan_key for s in held} == {"owner_monthly", "ca_seat_monthly"}
    created = {s.provider_subscription_id: s for s in provider.subscriptions}
    assert {created[s.provider_subscription_id].tenant_id for s in held} == {TENANT}


def test_halted_keeps_the_plan_for_the_grace_only() -> None:
    """M5: halted is past due; the plan stays for the grace after it turned past due."""
    provider = MemoryBillingProvider(clock=lambda: NOW)
    store = MemoryStore()
    sid = (
        StartSubscription(provider, store, clock=lambda: NOW)
        .run(TENANT, "owner_monthly", key=next(KEYS), email="owner@example.com", name="n")
        .provider_subscription_id
    )
    receive = ReceiveBillingWebhook(provider, store, clock=lambda: NOW)
    for kind, at in (("subscription.activated", 10), ("subscription.halted", 20)):
        body = webhook(kind, sid, created_at=946_684_800 + at)
        receive.run(body, provider.sign(body))
    held = store.billing.subscriptions[sid]
    halted_at = datetime.fromtimestamp(946_684_820, tz=UTC)
    assert (held.status, held.past_due_since) == (SubscriptionStatus.PAST_DUE, halted_at)
    grace = timedelta(days=14)
    assert held.entitled(halted_at + timedelta(days=13), grace)
    assert not held.entitled(halted_at + timedelta(days=14), grace)
    body = webhook("subscription.charged", sid, created_at=946_684_900)
    receive.run(body, provider.sign(body))
    assert store.billing.subscriptions[sid].past_due_since is None


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
    with pytest.raises(RazorpayRefusedError, match="no Razorpay plan id"):
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
