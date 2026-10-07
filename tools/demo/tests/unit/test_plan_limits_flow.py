"""Plan limits across identity and profile, with the flag identity.plan_limits on.

Identity runs with the memory billing provider and profile asks it for the tenant's entitlements
over HTTP with its own service token (``entitlements:read``), as it does in the product; here
the HTTP client is identity's test client, and the token is minted with identity's issuer, as
the one process mints them. Both read the flag from the environment, through the shared flags
reader.

A business owner signs up on the free allowance (one GSTIN registration). Their first business
is created; the second is refused with 402 and the limit and the count, and no GSTIN in the
answer. They start a subscription (with an Idempotency-Key), the provider's signed webhook
activates it, and once the profile's minute-long cache of the entitlements has passed, the
second business is created. The owner's audit trail shows the subscription started and its
status changed by the billing webhook. A signed webhook that names the tenant for a subscription
it never started changes nothing, and once the subscription is cancelled a late charge does not
revive it: the tenant is back on the free allowance. Nothing reaches a real billing provider.
"""

import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any, Final
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from domain_kernel.access import Principal, Scope
from identity.infrastructure.billing.memory import MemoryBillingProvider
from identity.main import build_app as build_identity
from identity.testing import identity_settings
from profile_service.infrastructure.entitlements import FlaggedEntitlements, HttpEntitlements
from profile_service.infrastructure.flags import OpenFeatureFlags
from profile_service.main import build_app as build_profile
from profile_service.settings import ProfileSettings
from py_common.auth import BearerAuth, IssuerTokenSource, TokenIssuer
from py_common.auth.testing import bearer

IDENTITY: Final = "/v1/identity"
BUSINESSES: Final = "/v1/businesses"
OWNER_PHONE: Final = "+919876543210"
FIRST: Final = {"name": "Example Traders", "gstin": "29ABCDE1234F1Z5"}
SECOND: Final = {"name": "Example Stores", "gstin": "29BBBBB2222B1Z5"}


@pytest.fixture
def flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CW_PLAN_LIMITS_ENFORCED", "true")
    monkeypatch.delenv("CW_PLAN_LIMITS_TENANTS", raising=False)


@pytest.fixture
def identity(flag_on: None) -> Iterator[TestClient]:
    with TestClient(build_identity(identity_settings(auth_mode="token"))) as client:
        yield client


class Clock:
    """The profile's monotonic clock, moved by hand past the entitlements cache."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def profile(identity: TestClient, clock: Clock) -> Iterator[TestClient]:
    app = identity.app
    assert isinstance(app, FastAPI)
    wiring = app.state.wiring
    issuer = TokenIssuer(
        wiring.keys, issuer=wiring.settings.auth_issuer, audience=wiring.settings.auth_audience
    )
    token = IssuerTokenSource(issuer, Principal.service("profile", [Scope.ENTITLEMENTS_READ]))
    reader = HttpEntitlements(client=identity, auth=BearerAuth(token), monotonic=clock)
    settings = ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="memory",
        profile_gstin_lookup="static",
        auth_mode="token",
        auth_jwks_json=SecretStr(identity.get(f"{IDENTITY}/.well-known/jwks.json").text),
    )
    entitlements = FlaggedEntitlements(OpenFeatureFlags(), reader)
    with TestClient(build_profile(settings, entitlements=entitlements)) as client:
        yield client


def sign_up(identity: TestClient) -> tuple[str, dict[str, str]]:
    issued = identity.post(f"{IDENTITY}/dev/provider-tokens", json={"phone": OWNER_PHONE})
    assert issued.status_code == 200, issued.text
    created = identity.post(
        f"{IDENTITY}/tenants",
        json={
            "kind": "business",
            "name": "Example Traders",
            "provider_token": issued.json()["provider_token"],
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body["tenant"]["id"], bearer(body["session"]["access_token"])


def create_business(profile: TestClient, owner: dict[str, str], body: dict[str, str]) -> Any:
    return profile.post(BUSINESSES, json=body, headers={**owner, "Idempotency-Key": str(uuid4())})


def signed(body: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    signature = hmac.new(b"memory", raw, hashlib.sha256).hexdigest()
    return raw, {"x-razorpay-signature": signature}


def test_a_paid_plan_lifts_the_free_registration_limit(
    identity: TestClient, profile: TestClient, clock: Clock
) -> None:
    tenant, owner = sign_up(identity)
    free = identity.get(f"{IDENTITY}/entitlements", headers=owner).json()
    assert free == {
        "plan_key": "free",
        "status": "free",
        "limits": {"registrations": 1, "seats": 1},
        "enforced": True,
    }

    # 1. The first business takes the free registration; the second is refused.
    assert create_business(profile, owner, FIRST).status_code == 201
    refused = create_business(profile, owner, SECOND)
    assert refused.status_code == 402, refused.text
    problem = refused.json()
    assert problem["type"].endswith("profile-plan-limit-reached")
    assert (problem["limit"], problem["used"]) == (1, 1)
    assert SECOND["gstin"] not in refused.text

    # 2. A subscription, started once whatever the retries, activated by the provider.
    key = {"Idempotency-Key": str(uuid4())}
    request = {"plan_key": "owner_monthly", "email": "owner@example.com", "name": "Example"}
    started = identity.post(
        f"{IDENTITY}/billing/subscriptions", json=request, headers={**owner, **key}
    )
    assert started.status_code == 201, started.text
    retried = identity.post(
        f"{IDENTITY}/billing/subscriptions", json=request, headers={**owner, **key}
    )
    assert retried.json() == started.json()
    app = identity.app
    assert isinstance(app, FastAPI)
    provider = app.state.wiring.start_subscription._provider
    assert isinstance(provider, MemoryBillingProvider)
    assert len(provider.subscriptions) == 1, "the retry started nothing at the provider"
    subscription_id = started.json()["provider_subscription_id"]
    raw, signature = signed(
        {
            "event": "subscription.activated",
            "created_at": 946_684_810,
            "payload": {
                "subscription": {
                    "entity": {
                        "id": subscription_id,
                        "notes": {"tenant_id": tenant, "plan_key": "owner_monthly"},
                    }
                }
            },
        }
    )
    activated = identity.post(f"{IDENTITY}/billing/webhook", content=raw, headers=signature)
    assert activated.status_code == 200, activated.text
    paid = identity.get(f"{IDENTITY}/entitlements", headers=owner).json()
    assert (paid["plan_key"], paid["status"]) == ("owner_monthly", "active")
    assert paid["limits"]["registrations"] > 1

    # 3. Within the profile's cache the old limit still holds; after it, the second business.
    assert create_business(profile, owner, SECOND).status_code == 402
    clock.now += 61
    second = create_business(profile, owner, SECOND)
    assert second.status_code == 201, second.text

    # 4. The owner's audit trail shows the subscription's life.
    trail = identity.get(f"{IDENTITY}/audit", params={"limit": 200}, headers=owner)
    assert trail.status_code == 200, trail.text
    subscription = sorted(
        (item["action"], item["actor"]["kind"], item["actor"]["label"])
        for item in trail.json()["items"]
        if item["subject"] == {"type": "subscription", "id": subscription_id}
    )
    assert [(action, kind) for action, kind, _ in subscription] == [
        ("subscription.started", "user"),
        ("subscription.status_changed", "system"),
    ]
    assert subscription[1][2] == "system:billing-webhook"

    # 5. A webhook for a subscription the tenant never started, with no customer of its own, is
    # answered and ignored; a cancellation is final even when a late charge follows it.
    forged, forged_signature = signed(
        {
            "event": "subscription.activated",
            "payload": {
                "subscription": {
                    "entity": {
                        "id": "sub_example_forged",
                        "customer_id": "cust_example_forged",
                        "quantity": 1_000_000,
                        "notes": {"tenant_id": tenant, "plan_key": "ca_seat_monthly"},
                    }
                }
            },
        }
    )
    ignored = identity.post(f"{IDENTITY}/billing/webhook", content=forged, headers=forged_signature)
    assert (ignored.status_code, ignored.json()["ignored"]) == (200, True)
    for kind, created_at in (
        ("subscription.cancelled", 946_684_830),
        ("subscription.charged", 946_684_820),
    ):
        raw, signature = signed(
            {
                "event": kind,
                "created_at": created_at,
                "payload": {
                    "subscription": {
                        "entity": {"id": subscription_id, "notes": {"tenant_id": tenant}}
                    }
                },
            }
        )
        assert (
            identity.post(f"{IDENTITY}/billing/webhook", content=raw, headers=signature).status_code
            == 200
        )
    after = identity.get(f"{IDENTITY}/entitlements", headers=owner).json()
    assert (after["plan_key"], after["limits"]["registrations"]) == ("free", 1)
    trail = identity.get(f"{IDENTITY}/audit", params={"limit": 200}, headers=owner).json()
    actions = {item["action"] for item in trail["items"]}
    assert {"subscription.unmatched", "subscription.event_ignored"} <= actions
