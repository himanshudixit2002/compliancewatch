from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.channels import Channel
from domain_kernel.ids import NotificationId, TenantId
from notification.composition import WHATSAPP_DISABLED, wire
from notification.domain.notification import DeliveryState
from notification.domain.preferences import ConsentSource
from notification.infrastructure.ses_feedback import SnsFeedbackReader
from notification.main import build_app
from notification.testing import (
    BOT_TOKEN,
    EMAIL_FEEDBACK_TOKEN,
    NOON_IST,
    FakeChannel,
    FakeRuleVersionReader,
    FakeSns,
    notification_settings,
    ses_report,
)

PHONE = "919876543210"
TENANT = {"x-tenant-id": str(uuid4())}
BOT = {"x-cw-bot-token": BOT_TOKEN}


def wrote_now(client: TestClient, phone: str = PHONE) -> None:
    """The bot forwards that the number just wrote to us: the 24-hour window is open."""
    now = datetime.now(UTC).isoformat()
    response = client.post(
        "/v1/notification/receipts/whatsapp",
        json={"inbound": [{"address": phone, "at": now}]},
        headers=BOT,
    )
    assert response.status_code == 200, response.text
    assert response.json()["inbound"] == 1


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
    assert (body["recipient"], body["address"]) == (PHONE, "+919876543210")
    got = client.get("/v1/notification/preferences/whatsapp/+91 98765 43210")
    assert got.json()["opted_in"] is True
    assert got.json()["recipient"] == "+91 98765 43210"
    bad = client.put(
        f"/v1/notification/preferences/whatsapp/{PHONE}",
        json={"opted_in": True, "source": "carrier pigeon"},
    )
    assert bad.status_code == 422


def test_an_address_that_is_not_one_is_a_422_problem(client: TestClient) -> None:
    for method in ("GET", "PUT"):
        response = client.request(
            method,
            "/v1/notification/preferences/whatsapp/call-me-maybe",
            json={"opted_in": True, "source": "api"},
        )
        assert response.status_code == 422
        assert response.json()["type"].endswith(":notification-address-invalid")
    email = client.get("/v1/notification/preferences/email/nobody")
    assert email.status_code == 422


def test_sends_go_through_the_channels_given_to_build_app() -> None:
    channel = FakeChannel(clock=lambda: NOON_IST)
    app = build_app(
        notification_settings(notification_bot_token=BOT_TOKEN),
        channels={Channel.WHATSAPP: channel},
    )
    wiring = app.state.wiring
    wiring.set_opt_in.run(Channel.WHATSAPP, PHONE, opted_in=True, source=ConsentSource.API)
    body = send_body()
    with TestClient(app) as client:
        wrote_now(client)
        first = client.post("/v1/notification/send", json=body, headers=TENANT)
        again = client.post("/v1/notification/send", json=body, headers=TENANT)
    assert first.json()["outcome"] in {"sent", "deferred"}
    if first.json()["outcome"] == "sent":
        assert first.json()["provider_message_id"] == "fake-1"
        assert again.json()["outcome"] == "duplicate"
        assert channel.sent[0].recipient == "+919876543210"


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
    assert unauthenticated.json()["type"].endswith(":notification-tenant-required")
    # The tenant is checked before the body: no tenant and no body is still a 401.
    assert client.post("/v1/notification/send").status_code == 401
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


def test_a_failed_send_stays_queued_and_the_old_attempt_field_is_ignored() -> None:
    channel = FakeChannel(clock=lambda: NOON_IST)
    channel.fail_next = 1
    never_quiet = notification_settings(
        quiet_hours_start="00:00", quiet_hours_end="00:00", notification_bot_token=BOT_TOKEN
    )
    app = build_app(
        never_quiet, channels={Channel.WHATSAPP: channel}, rules=FakeRuleVersionReader()
    )
    wiring = app.state.wiring
    wiring.set_opt_in.run(Channel.WHATSAPP, PHONE, opted_in=True, source=ConsentSource.API)
    body = send_body(attempt=3)
    with TestClient(app) as client:
        wrote_now(client)
        failed = client.post("/v1/notification/send", json=body, headers=TENANT)
        again = client.post("/v1/notification/send", json=body, headers=TENANT)
    assert failed.status_code == 200, failed.text
    assert (failed.json()["outcome"], failed.json()["error"]) == ("failed", "fake: down")
    assert again.json()["outcome"] == "duplicate", "the service retries, not the caller"
    with wiring.unit_of_work(TenantId(UUID(TENANT["x-tenant-id"]))) as unit:
        stored = unit.notifications.get(NotificationId(UUID(str(body["notification_id"]))))
    assert stored is not None
    assert (stored.state, stored.attempts) == (DeliveryState.QUEUED, 1)


def receipts_app(**settings: object) -> tuple[FastAPI, FakeChannel]:
    channel = FakeChannel(clock=lambda: NOON_IST)
    never_quiet = notification_settings(
        quiet_hours_start="00:00", quiet_hours_end="00:00", **settings
    )
    app = build_app(never_quiet, channels={Channel.WHATSAPP: channel})
    app.state.wiring.set_opt_in.run(
        Channel.WHATSAPP, PHONE, opted_in=True, source=ConsentSource.API
    )
    return app, channel


def test_the_receipt_route_needs_the_bot_token(client: TestClient) -> None:
    unset = client.post("/v1/notification/receipts/whatsapp", json={}, headers=BOT)
    assert unset.status_code == 503
    assert unset.json()["type"].endswith(":notification-receipts-disabled")
    app, _ = receipts_app(notification_bot_token=BOT_TOKEN)
    with TestClient(app) as guarded:
        missing = guarded.post("/v1/notification/receipts/whatsapp", json={})
        wrong = guarded.post(
            "/v1/notification/receipts/whatsapp", json={}, headers={"x-cw-bot-token": "nope"}
        )
        empty = guarded.post("/v1/notification/receipts/whatsapp", json={}, headers=BOT)
        naive = guarded.post(
            "/v1/notification/receipts/whatsapp",
            json={"inbound": [{"address": PHONE, "at": "2026-09-28T12:00:00"}]},
            headers=BOT,
        )
    assert missing.status_code == wrong.status_code == 401
    assert wrong.json()["type"].endswith(":notification-receipt-token-invalid")
    assert empty.json() == {"applied": 0, "unchanged": 0, "unknown": 0, "ignored": 0, "inbound": 0}
    assert naive.status_code == 422, "a time without its offset is refused"


def test_statuses_move_a_sent_notification_on_and_the_history_shows_it() -> None:
    app, channel = receipts_app(notification_bot_token=BOT_TOKEN)
    body = send_body()
    business = str(body["business_id"])
    with TestClient(app) as client:
        wrote_now(client)
        sent = client.post("/v1/notification/send", json=body, headers=TENANT).json()
        assert sent["outcome"] == "sent"
        forwarded = client.post(
            "/v1/notification/receipts/whatsapp",
            json={
                "statuses": [
                    {"provider_message_id": "fake-1", "status": "read", "at": iso(NOON_IST)},
                    {"provider_message_id": "fake-1", "status": "delivered", "at": iso(NOON_IST)},
                    {"provider_message_id": "wamid.reply", "status": "sent", "at": iso(NOON_IST)},
                    {"provider_message_id": "fake-1", "status": "deleted", "at": iso(NOON_IST)},
                ]
            },
            headers=BOT,
        )
        assert forwarded.json() == {
            "applied": 1,
            "unchanged": 1,
            "unknown": 1,
            "ignored": 1,
            "inbound": 0,
        }
        one = client.get(
            f"/v1/notification/notifications/{body['notification_id']}", headers=TENANT
        )
        page = client.get(
            "/v1/notification/notifications", params={"business_id": business}, headers=TENANT
        )
        other = client.get(f"/v1/notification/notifications/{uuid4()}", headers=TENANT)
    assert one.status_code == 200, one.text
    assert (one.json()["state"], one.json()["provider_message_id"]) == ("read", "fake-1")
    assert one.json()["read_at"] is not None
    assert [item["id"] for item in page.json()["items"]] == [body["notification_id"]]
    assert page.json()["next_cursor"] is None
    assert other.status_code == 404
    assert other.json()["type"].endswith(":notification-not-found")
    assert channel.sent[0].recipient == "+919876543210"


def test_a_failed_notification_can_be_resent_once_and_nothing_else_can() -> None:
    app, channel = receipts_app()
    failed_body = send_body()
    with TestClient(app) as client:
        failed = client.post("/v1/notification/send", json=failed_body, headers=TENANT).json()
        assert failed["outcome"] == "failed", "outside the window with a draft template"
        path = f"/v1/notification/notifications/{failed_body['notification_id']}/resend"
        resent = client.post(path, headers=TENANT)
        again = client.post(path, headers=TENANT)
        missing = client.post(f"/v1/notification/notifications/{uuid4()}/resend", headers=TENANT)
        without_tenant = client.post(path)
    assert resent.status_code == 200, resent.text
    assert (resent.json()["state"], resent.json()["attempts"], resent.json()["error"]) == (
        "queued",
        0,
        "",
    )
    assert again.status_code == 409
    assert again.json()["type"].endswith(":notification-resend-not-allowed")
    assert missing.status_code == 404
    assert without_tenant.status_code == 401
    assert channel.sent == []


def test_the_history_pages_newest_first_and_filters_by_state() -> None:
    app, _ = receipts_app()
    business = str(uuid4())
    ids: list[str] = []
    with TestClient(app) as client:
        for _ in range(3):
            body = send_body(business_id=business)
            ids.append(str(body["notification_id"]))
            assert (
                client.post("/v1/notification/send", json=body, headers=TENANT).status_code == 200
            )
        first = client.get(
            "/v1/notification/notifications",
            params={"business_id": business, "limit": 2},
            headers=TENANT,
        ).json()
        second = client.get(
            "/v1/notification/notifications",
            params={"business_id": business, "limit": 2, "cursor": first["next_cursor"]},
            headers=TENANT,
        ).json()
        sent = client.get(
            "/v1/notification/notifications",
            params={"business_id": business, "state": "sent"},
            headers=TENANT,
        ).json()
        bad_cursor = client.get(
            "/v1/notification/notifications",
            params={"business_id": business, "cursor": "not-a-cursor"},
            headers=TENANT,
        )
    listed = [item["id"] for item in first["items"]] + [item["id"] for item in second["items"]]
    assert sorted(listed) == sorted(ids)
    assert len(first["items"]) == 2
    assert second["next_cursor"] is None
    assert sent["items"] == [], "every send failed outside the window"
    assert bad_cursor.status_code == 422


def iso(moment: datetime) -> str:
    return moment.isoformat()


def test_the_email_feedback_route_takes_sns_basic_credentials(client: TestClient) -> None:
    sns = FakeSns()
    body = sns.notification(ses_report("Complaint", "Owner@Example.com"))
    unset = client.post("/v1/notification/receipts/email", content=body)
    assert unset.status_code == 503
    assert "CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN" in unset.json()["detail"]
    app = build_app(
        notification_settings(notification_email_feedback_token=EMAIL_FEEDBACK_TOKEN),
        email_feedback=SnsFeedbackReader(sns.certificates, topic_arn=FakeSns.TOPIC),
    )
    headers = {"content-type": "text/plain; charset=UTF-8"}
    with TestClient(app) as guarded:
        missing = guarded.post("/v1/notification/receipts/email", content=body, headers=headers)
        wrong = guarded.post(
            "/v1/notification/receipts/email",
            content=body,
            headers=headers,
            auth=("sns", "not-the-secret"),
        )
        garbage = guarded.post(
            "/v1/notification/receipts/email",
            content="not json",
            headers=headers,
            auth=("sns", EMAIL_FEEDBACK_TOKEN),
        )
        accepted = guarded.post(
            "/v1/notification/receipts/email",
            content=body,
            headers=headers,
            auth=("sns", EMAIL_FEEDBACK_TOKEN),
        )
        confirmation = guarded.post(
            "/v1/notification/receipts/email",
            content=sns.confirmation(),
            headers=headers,
            auth=("anyone", EMAIL_FEEDBACK_TOKEN),
        )
        with app.state.wiring.unit_of_work.shared() as unit:
            suppression = unit.suppressions.get(Channel.EMAIL, "owner@example.com")
    assert missing.status_code == wrong.status_code == 401
    assert missing.headers["www-authenticate"].startswith("Basic ")
    assert wrong.json()["type"].endswith(":notification-email-feedback-unauthorized")
    assert garbage.status_code == 422
    assert garbage.json()["type"].endswith(":notification-email-feedback-invalid")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {
        "kind": "report",
        "applied": 0,
        "unchanged": 0,
        "unknown": 0,
        "suppressed": 1,
    }
    assert confirmation.json()["kind"] == "subscription_confirmation"
    assert suppression is not None
