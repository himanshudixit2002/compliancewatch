import hashlib
import hmac
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from identity.main import build_app
from identity.testing import identity_settings

TENANT = {"x-tenant-id": str(uuid4())}


def test_consents_round_trip(client: TestClient) -> None:
    unauthenticated = client.post(
        "/v1/identity/consents", json={"subject": "u", "purpose": "terms", "source": "api"}
    )
    assert unauthenticated.status_code == 401
    refused = client.post(
        "/v1/identity/consents",
        json={"subject": "u", "purpose": "terms", "source": "web_onboarding"},
        headers=TENANT,
    )
    assert refused.status_code == 422
    assert "notice_version" in refused.json()["detail"]
    created = client.post(
        "/v1/identity/consents",
        json={
            "subject": "u",
            "purpose": "whatsapp_reminders",
            "source": "web_onboarding",
            "notice_version": "0.1-draft",
            "evidence": "checkbox",
        },
        headers=TENANT,
    )
    assert created.status_code == 201, created.text
    withdrawn = client.post(
        "/v1/identity/consents",
        json={
            "subject": "u",
            "purpose": "whatsapp_reminders",
            "granted": False,
            "source": "whatsapp_keyword",
            "evidence": "STOP",
        },
        headers=TENANT,
    )
    assert withdrawn.status_code == 201
    summary = client.get("/v1/identity/consents", params={"subject": "u"}, headers=TENANT).json()
    assert summary["states"] == [
        {
            "purpose": "whatsapp_reminders",
            "granted": False,
            "notice_version": "",
            "since": withdrawn.json()["recorded_at"],
            "source": "whatsapp_keyword",
        }
    ]
    assert len(summary["history"]) == 2
    other = client.get(
        "/v1/identity/consents", params={"subject": "u"}, headers={"x-tenant-id": str(uuid4())}
    ).json()
    assert other["history"] == []


def test_billing_with_the_memory_provider(client: TestClient) -> None:
    plans = client.get("/v1/identity/billing/plans").json()
    assert [p["key"] for p in plans] == ["owner_monthly", "ca_seat_monthly"]
    started = client.post(
        "/v1/identity/billing/subscriptions",
        json={"plan_key": "owner_monthly", "email": "a@b.c", "name": "Acme"},
        headers=TENANT,
    )
    assert started.status_code == 201, started.text
    subscription_id = started.json()["provider_subscription_id"]
    body = json.dumps(
        {
            "event": "subscription.activated",
            "payload": {"subscription": {"entity": {"id": subscription_id}}},
        }
    ).encode()
    signature = hmac.new(b"memory", body, hashlib.sha256).hexdigest()
    ok = client.post(
        "/v1/identity/billing/webhook", content=body, headers={"x-razorpay-signature": signature}
    )
    assert ok.status_code == 200
    assert ok.json() == {
        "kind": "subscription.activated",
        "provider_subscription_id": subscription_id,
        "status": "active",
    }
    bad = client.post(
        "/v1/identity/billing/webhook", content=body, headers={"x-razorpay-signature": "nope"}
    )
    assert bad.status_code == 401
    unknown_plan = client.post(
        "/v1/identity/billing/subscriptions",
        json={"plan_key": "gold", "email": "a@b.c", "name": "n"},
        headers=TENANT,
    )
    assert unknown_plan.status_code == 422


def test_billing_is_503_while_disabled() -> None:
    with TestClient(build_app(identity_settings(billing_provider="none"))) as client:
        response = client.post(
            "/v1/identity/billing/subscriptions",
            json={"plan_key": "owner_monthly", "email": "a@b.c", "name": "n"},
            headers=TENANT,
        )
        assert response.status_code == 503
        assert client.post("/v1/identity/billing/webhook", content=b"{}").status_code == 503
        assert client.get("/ready").json()["status"] == "ready"


def test_razorpay_wiring_needs_every_key() -> None:
    from identity.main import billing_provider

    assert billing_provider(identity_settings(billing_provider="razorpay")) is None
    provider = billing_provider(
        identity_settings(
            billing_provider="razorpay",
            razorpay_key_id="rzp_test_x",
            razorpay_key_secret="s",
            razorpay_webhook_secret="w",
            razorpay_plan_ids="owner_monthly=plan_1,ca_seat_monthly=plan_2",
        )
    )
    assert provider is not None
    assert identity_settings(razorpay_plan_ids="a=b").razorpay_plan_ids == {"a": "b"}
