from uuid import uuid4

from fastapi.testclient import TestClient

from notification.main import WHATSAPP_DISABLED, build_app, wire
from notification.testing import notification_settings

PHONE = "919876543210"
TENANT = {"x-tenant-id": str(uuid4())}


def send_body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "notification_id": str(uuid4()),
        "obligation_id": str(uuid4()),
        "business_id": str(uuid4()),
        "channel": "whatsapp",
        "recipient": PHONE,
        "template_key": "obligation_due_soon",
        "params": {
            "business_name": "Acme",
            "title": "GSTR-3B",
            "due_date": "20 Oct",
            "steps": "file",
        },
    }
    body.update(changes)
    return body


def test_preferences_round_trip(client: TestClient) -> None:
    missing = client.get(f"/v1/notification/preferences/whatsapp/{PHONE}")
    assert missing.status_code == 404
    put = client.put(
        f"/v1/notification/preferences/whatsapp/{PHONE}",
        json={
            "opted_in": True,
            "source": "whatsapp_keyword",
            "language": "hi",
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert (body["opted_in"], body["language"], body["quiet_hours_start"]) == (True, "hi", "22:00")
    got = client.get(f"/v1/notification/preferences/whatsapp/{PHONE}")
    assert got.json()["opted_in"] is True
    bad = client.put(
        f"/v1/notification/preferences/whatsapp/{PHONE}",
        json={"opted_in": True, "source": "carrier pigeon"},
    )
    assert bad.status_code == 422


def test_quiet_hours_past_23_59_are_a_422_problem(client: TestClient) -> None:
    body = {
        "opted_in": True,
        "source": "api",
        "quiet_hours_start": "24:00",
        "quiet_hours_end": "08:00",
    }
    response = client.put(f"/v1/notification/preferences/whatsapp/{PHONE}", json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["errors"][0]["loc"] == ["body", "quiet_hours_start"]


def test_send_needs_a_tenant_then_reports_the_disabled_channel(client: TestClient) -> None:
    unauthenticated = client.post("/v1/notification/send", json=send_body())
    assert unauthenticated.status_code == 401
    not_opted = client.post("/v1/notification/send", json=send_body(), headers=TENANT)
    assert not_opted.json()["outcome"] == "not_opted_in"
    client.put(
        f"/v1/notification/preferences/whatsapp/{PHONE}", json={"opted_in": True, "source": "api"}
    )
    sent = client.post("/v1/notification/send", json=send_body(), headers=TENANT)
    body = sent.json()
    assert body["outcome"] in {"failed", "deferred"}
    if body["outcome"] == "failed":
        assert body["error"] == WHATSAPP_DISABLED
    missing_param = client.post("/v1/notification/send", json=send_body(params={}), headers=TENANT)
    assert missing_param.status_code in {422, 200}
    if missing_param.status_code == 200:
        assert missing_param.json()["outcome"] == "deferred"


def test_templates_are_listed_with_status(client: TestClient) -> None:
    response = client.get("/v1/notification/templates")
    assert response.status_code == 200
    templates = response.json()
    assert any(t["key"] == "obligation_due_soon" and t["language"] == "hi" for t in templates)
    assert all(t["status"] == "draft" for t in templates)
    assert {"business_name", "title", "due_date", "steps"} <= set(templates[0]["placeholders"])


def test_ready_and_the_enabled_channel_wiring() -> None:
    from domain_kernel.channels import Channel
    from notification.infrastructure.whatsapp import WhatsAppCloudChannel

    wiring = wire(
        notification_settings(
            whatsapp_enabled=True, whatsapp_phone_number_id="42", whatsapp_access_token="tok"
        )
    )
    assert isinstance(wiring.channels[Channel.WHATSAPP], WhatsAppCloudChannel)
    with TestClient(build_app(notification_settings())) as client:
        assert client.get("/ready").json()["status"] == "ready"
