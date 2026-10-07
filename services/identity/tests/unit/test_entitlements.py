"""Entitlements: what a tenant's plan allows, the route that reads them, and the seat limit an
invitation meets while the flag identity.plan_limits is on."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from domain_kernel.access import Principal, Role, Scope
from domain_kernel.ids import TenantId
from identity.application.billing import ReceiveBillingWebhook, StartSubscription
from identity.application.entitlements import ReadEntitlements, SeatCheck
from identity.application.tenancy import CreateTenant, DisableUser, InviteUser
from identity.domain.billing import PLANS, BillingPeriod, Plan, Subscription, SubscriptionStatus
from identity.domain.entitlements import FREE_PLAN, INTERNAL_PLAN, Limits, entitlements_for
from identity.domain.errors import SeatLimitReachedError
from identity.domain.flags import PLAN_LIMITS
from identity.domain.tenancy import Contact, Tenant, TenantKind
from identity.infrastructure.billing.memory import MemoryBillingProvider
from identity.infrastructure.flags import StaticFlags
from identity.infrastructure.memory import MemoryStore
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.main import build_app
from identity.testing import DEV_CLIENT_SECRET, identity_settings
from py_common.auth import TokenIssuer
from py_common.auth.testing import TestIssuer, bearer

NOW = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
FREE = Limits(registrations=1, seats=1)
ENTITLEMENTS = "/v1/identity/entitlements"
OWNER = PLANS["owner_monthly"]


def subscription(
    status: SubscriptionStatus, quantity: int = 1, plan: str = OWNER.key
) -> Subscription:
    return Subscription(TenantId.new(), plan, "sub_1", status, NOW, quantity=quantity)


def test_no_subscription_is_the_free_allowance() -> None:
    free = entitlements_for(None, PLANS, FREE)
    assert (free.plan_key, free.status, free.limits, free.enforced) == (
        FREE_PLAN,
        FREE_PLAN,
        FREE,
        False,
    )


@pytest.mark.parametrize(
    ("status", "paid"),
    [
        (SubscriptionStatus.CREATED, False),
        (SubscriptionStatus.ACTIVE, True),
        (SubscriptionStatus.PAST_DUE, True),
        (SubscriptionStatus.CANCELLED, False),
    ],
)
def test_a_paid_subscription_gives_its_plan_times_its_quantity(
    status: SubscriptionStatus, paid: bool
) -> None:
    found = entitlements_for(subscription(status, quantity=2), PLANS, FREE, enforced=True)
    assert found.enforced
    if not paid:
        assert found.limits == FREE
        return
    assert (found.plan_key, found.status) == (OWNER.key, status.value)
    assert found.limits == Limits(
        registrations=OWNER.limit("registrations", 2), seats=OWNER.limit("seats", 2)
    )


def test_a_plan_no_longer_offered_is_the_free_allowance_and_none_is_no_limit() -> None:
    gone = entitlements_for(subscription(SubscriptionStatus.ACTIVE, plan="gone"), PLANS, FREE)
    assert gone.limits == FREE
    open_plan = {"open": Plan("open", "Open", 0, BillingPeriod.MONTHLY)}
    unlimited = entitlements_for(
        subscription(SubscriptionStatus.ACTIVE, plan="open"), open_plan, FREE
    )
    assert unlimited.limits == Limits(None, None)


class Business:
    """A business signed up on the memory store with its owner."""

    def __init__(self, *flags: str, kind: TenantKind = TenantKind.BUSINESS) -> None:
        self.store = MemoryStore()
        self.provider = FakeIdentityProvider()
        issuer = TestIssuer()
        minter = IssuerMinter(
            TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
        )
        created = CreateTenant(
            self.store, self.provider, minter, ttl=timedelta(minutes=10), clock=lambda: NOW
        ).run(self.provider.issue(phone="+919876543210"), kind, "Example Traders")
        self.tenant: Tenant = created.tenant
        self.owner: Principal = created.session.principal
        self.flags = StaticFlags(*flags)
        seats = SeatCheck(PLANS, FREE, self.flags)
        self.invite = InviteUser(self.store, self.provider, seats=seats, clock=lambda: NOW)
        self.read = ReadEntitlements(self.store, PLANS, FREE, self.flags)

    def invite_staff(self, phone: str) -> None:
        self.invite.run(
            self.tenant.id, self.owner, contact=Contact(phone=phone), roles=[Role.STAFF]
        )


def test_with_the_flag_off_the_seats_are_reported_and_not_enforced() -> None:
    business = Business()
    business.invite_staff("+919812345678")
    found = business.read.run(business.tenant.id)
    assert (found.limits.seats, found.enforced) == (1, False)


def test_with_the_flag_on_an_invitation_past_the_seats_is_refused_until_one_is_free() -> None:
    business = Business(PLAN_LIMITS)
    with pytest.raises(SeatLimitReachedError) as refused:
        business.invite_staff("+919812345678")
    assert (refused.value.limit, refused.value.used) == (1, 1)
    assert refused.value.problem_extensions == {"limit": 1, "used": 1}
    subject = business.provider.subject_for(Contact(phone="+919812345678"))
    assert business.provider.lookup(subject) is None, "no provider account was made"
    provider = MemoryBillingProvider(clock=lambda: NOW)
    started = StartSubscription(provider, business.store, clock=lambda: NOW).run(
        business.tenant.id, OWNER.key, email="owner@example.com", name="Example Traders"
    )
    body = json.dumps(
        {
            "event": "subscription.activated",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": started.provider_subscription_id,
                        "notes": {"tenant_id": str(business.tenant.id)},
                    }
                }
            },
        }
    ).encode()
    ReceiveBillingWebhook(provider, business.store, clock=lambda: NOW).run(
        body, provider.sign(body)
    )
    assert business.read.run(business.tenant.id).limits.seats == OWNER.limit("seats", 1)
    business.invite_staff("+919812345678")


def test_a_disabled_user_frees_a_seat() -> None:
    business = Business()
    business.invite_staff("+919812345678")
    staff = next(u for u in business.store.users.values() if Role.STAFF in u.roles)
    business.flags = StaticFlags(PLAN_LIMITS)
    business.invite = InviteUser(
        business.store, business.provider, seats=SeatCheck(PLANS, Limits(None, 2), business.flags)
    )
    with pytest.raises(SeatLimitReachedError):
        business.invite_staff("+919811111111")
    DisableUser(business.store, clock=lambda: NOW).run(business.tenant.id, business.owner, staff.id)
    business.invite_staff("+919811111111")


def test_the_internal_tenant_has_no_limits() -> None:
    business = Business(PLAN_LIMITS)
    found = ReadEntitlements(business.store, PLANS, FREE, StaticFlags(PLAN_LIMITS))
    internal = Tenant(TenantId.new(), TenantKind.INTERNAL, "Example regulatory team", NOW)
    with business.store(internal.id) as uow:
        uow.tenants.add(internal)
    read = found.run(internal.id)
    assert (read.plan_key, read.limits, read.enforced) == (INTERNAL_PLAN, Limits(None, None), False)


# ---------------------------------------------------------------- the route


def sign_up(client: TestClient) -> tuple[str, dict[str, str]]:
    issued = client.post("/v1/identity/dev/provider-tokens", json={"phone": "+919876543210"})
    created = client.post(
        "/v1/identity/tenants",
        json={
            "kind": "business",
            "name": "Example Traders",
            "provider_token": issued.json()["provider_token"],
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body["tenant"]["id"], bearer(body["session"]["access_token"])


def service_headers(client: TestClient, client_id: str) -> dict[str, str]:
    issued = client.post(
        "/v1/identity/service-tokens",
        json={"client_id": client_id, "client_secret": DEV_CLIENT_SECRET},
    )
    assert issued.status_code == 200, issued.text
    return bearer(issued.json()["access_token"])


def test_the_route_answers_a_user_their_tenant_and_a_service_with_the_scope() -> None:
    with TestClient(
        build_app(identity_settings(auth_mode="token"), flags=StaticFlags(PLAN_LIMITS))
    ) as client:
        tenant, owner = sign_up(client)
        mine = client.get(ENTITLEMENTS, headers=owner)
        assert mine.status_code == 200, mine.text
        assert mine.json() == {
            "plan_key": "free",
            "status": "free",
            "limits": {"registrations": 1, "seats": 1},
            "enforced": True,
        }
        other = client.get(ENTITLEMENTS, headers={**owner, "x-tenant-id": str(uuid4())})
        assert other.status_code == 403
        profile = service_headers(client, "profile")
        read = client.get(ENTITLEMENTS, headers={**profile, "x-tenant-id": tenant})
        assert read.status_code == 200
        assert read.json()["limits"] == {"registrations": 1, "seats": 1}
        assert client.get(ENTITLEMENTS, headers=profile).status_code == 401
        engine = service_headers(client, "applicability-engine")
        refused = client.get(ENTITLEMENTS, headers={**engine, "x-tenant-id": tenant})
        assert refused.status_code == 403
        assert client.get(ENTITLEMENTS).status_code == 401
        invited = client.post(
            "/v1/identity/users",
            json={"phone": "+919812345678", "roles": ["staff"]},
            headers=owner,
        )
        assert invited.status_code == 402, invited.text
        problem = invited.json()
        assert problem["type"].endswith("identity-seat-limit-reached")
        assert (problem["limit"], problem["used"]) == (1, 1)
        assert "+91" not in invited.text


def test_header_mode_reads_the_header_tenant() -> None:
    with TestClient(build_app(identity_settings(), flags=StaticFlags())) as client:
        tenant = str(uuid4())
        found = client.get(ENTITLEMENTS, headers={"x-tenant-id": tenant})
        assert found.status_code == 200
        assert found.json()["enforced"] is False
        assert client.get(ENTITLEMENTS).status_code == 401


def test_a_webhook_raises_the_limits_the_route_reports() -> None:
    with TestClient(build_app(identity_settings(), flags=StaticFlags())) as client:
        tenant = {"x-tenant-id": str(uuid4())}
        started = client.post(
            "/v1/identity/billing/subscriptions",
            json={"plan_key": OWNER.key, "email": "owner@example.com", "name": "n", "quantity": 2},
            headers={**tenant, "Idempotency-Key": str(uuid4())},
        )
        assert started.status_code == 201, started.text
        body = json.dumps(
            {
                "event": "subscription.charged",
                "payload": {
                    "subscription": {
                        "entity": {
                            "id": started.json()["provider_subscription_id"],
                            "notes": {"tenant_id": tenant["x-tenant-id"]},
                        }
                    }
                },
            }
        ).encode()
        signature = hmac.new(b"memory", body, hashlib.sha256).hexdigest()
        client.post(
            "/v1/identity/billing/webhook",
            content=body,
            headers={"x-razorpay-signature": signature},
        )
        found = client.get(ENTITLEMENTS, headers=tenant).json()
        assert (found["plan_key"], found["status"]) == (OWNER.key, "active")
        assert found["limits"]["registrations"] == OWNER.limit("registrations", 2)


def test_principal_scopes_used_here_exist() -> None:
    assert Scope.ENTITLEMENTS_READ.value == "entitlements:read"
