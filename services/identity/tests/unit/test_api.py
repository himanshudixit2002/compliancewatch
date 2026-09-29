import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from identity.main import build_app
from identity.testing import CHANNEL_TOKEN, identity_settings

TENANT = {"x-tenant-id": str(uuid4())}
SERVICE = {"x-cw-service-token": CHANNEL_TOKEN}
CHANNEL_CONSENTS = "/v1/identity/channel-consents"
NUMBER = "919876543210"
NOTICE = "whatsapp-consent 0.1-draft"


def channel_consent(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "channel": "whatsapp",
        "subject": NUMBER,
        "purpose": "whatsapp_reminders",
        "granted": True,
        "source": "whatsapp_keyword",
        "notice_version": NOTICE,
        "evidence": "keyword START in WhatsApp message wamid.1",
        "message_id": "wamid.1",
    }
    body.update(changes)
    return body


def test_channel_consents_round_trip(client: TestClient) -> None:
    created = client.post(CHANNEL_CONSENTS, json=channel_consent(), headers=SERVICE)
    assert created.status_code == 201, created.text
    assert created.json()["subject"] == NUMBER
    again = client.post(CHANNEL_CONSENTS, json=channel_consent(), headers=SERVICE)
    assert again.status_code == 200
    assert again.json() == created.json()
    withdrawn = client.post(
        CHANNEL_CONSENTS,
        json=channel_consent(
            subject="+" + NUMBER, granted=False, notice_version="", message_id="wamid.2"
        ),
        headers=SERVICE,
    )
    assert withdrawn.status_code == 201
    summary = client.get(f"{CHANNEL_CONSENTS}/whatsapp/%2B{NUMBER}", headers=SERVICE)
    assert summary.status_code == 200
    body = summary.json()
    assert (body["channel"], body["subject"]) == ("whatsapp", NUMBER)
    assert body["states"] == [
        {
            "purpose": "whatsapp_reminders",
            "granted": False,
            "notice_version": "",
            "since": withdrawn.json()["recorded_at"],
            "source": "whatsapp_keyword",
        }
    ]
    assert [item["message_id"] for item in body["history"]] == ["wamid.1", "wamid.2"]
    unknown = client.get(f"{CHANNEL_CONSENTS}/whatsapp/919999999999", headers=SERVICE)
    assert unknown.json() == {
        "channel": "whatsapp",
        "subject": "919999999999",
        "states": [],
        "history": [],
    }


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"notice_version": ""}, "consent-notice-version-required"),
        ({"purpose": "terms"}, "identity-channel-purpose-invalid"),
        ({"subject": "12345"}, "request-invalid"),
        ({"subject": "+0919876543210"}, "request-invalid"),
        ({"source": "api"}, "invariant-violation"),
        ({"channel": "email"}, "request-invalid"),
    ],
)
def test_a_channel_consent_the_service_refuses_is_422(
    client: TestClient, changes: dict[str, object], problem: str
) -> None:
    response = client.post(CHANNEL_CONSENTS, json=channel_consent(**changes), headers=SERVICE)
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith(":" + problem)
    bad_path = client.get(f"{CHANNEL_CONSENTS}/whatsapp/12345", headers=SERVICE)
    assert bad_path.status_code == 422


def test_channel_consents_need_the_service_token(client: TestClient) -> None:
    for headers in ({}, {"x-cw-service-token": "wrong"}, TENANT):
        post = client.post(CHANNEL_CONSENTS, json=channel_consent(), headers=headers)
        assert post.status_code == 401
        assert post.json()["type"].endswith(":identity-channel-token-invalid")
        assert client.get(f"{CHANNEL_CONSENTS}/whatsapp/{NUMBER}", headers=headers).status_code == (
            401
        )


@pytest.mark.parametrize("token", [None, ""])
def test_channel_consents_are_503_without_a_configured_token(token: str | None) -> None:
    with TestClient(build_app(identity_settings(identity_channel_token=token))) as client:
        post = client.post(CHANNEL_CONSENTS, json=channel_consent(), headers=SERVICE)
        assert post.status_code == 503
        assert post.json()["type"].endswith(":identity-channel-writes-disabled")
        read = client.get(f"{CHANNEL_CONSENTS}/whatsapp/{NUMBER}", headers=SERVICE)
        assert read.status_code == 503


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


def test_a_consent_changed_on_the_web_settings_pages_keeps_its_source(client: TestClient) -> None:
    withdrawn = client.post(
        "/v1/identity/consents",
        json={
            "subject": "settings-user",
            "purpose": "analytics",
            "granted": False,
            "source": "web_settings",
            "evidence": "toggle: Share usage analytics",
        },
        headers=TENANT,
    )
    assert withdrawn.status_code == 201, withdrawn.text
    assert withdrawn.json()["source"] == "web_settings"
    summary = client.get(
        "/v1/identity/consents", params={"subject": "settings-user"}, headers=TENANT
    ).json()
    assert [(state["purpose"], state["source"]) for state in summary["states"]] == [
        ("analytics", "web_settings")
    ]


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
