"""The hardened resend (``POST /notifications/{id}/resend``): a reason and an Idempotency-Key,
who may resend which tenant's notification, the recipient guard, the audit entry and the replay
of a retry; and the use case on the memory store."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.audit import AuditActor
from domain_kernel.channels import Channel
from domain_kernel.ids import NotificationId, TenantId
from notification.application.resend import RESENT_ACTION, ResendNotification
from notification.domain.errors import ResendRecipientMismatchError
from notification.domain.notification import DeliveryState
from notification.domain.preferences import ConsentSource
from notification.infrastructure.memory import MemoryStore
from notification.main import build_app
from notification.testing import NOON_IST, FakeChannel, notification_settings
from py_common.auth.testing import TestIssuer, bearer

PHONE = "919876543210"
TENANT_ID = TenantId.new()
OTHER_TENANT_ID = TenantId.new()
TENANT = {"x-tenant-id": str(TENANT_ID)}
REASON = {"reason": "Example support case 2000-01: the provider was down for an hour"}


def send_body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "notification_id": str(uuid4()),
        "obligation_id": str(uuid4()),
        "business_id": str(uuid4()),
        "channel": "whatsapp",
        "recipient": PHONE,
        "template_key": "obligation_due_soon",
        "params": {
            "business_name": "Example",
            "title": "Return",
            "due_date": "20 Oct",
            "steps": "x",
        },
    }
    body.update(changes)
    return body


def failing_app(**settings: Any) -> tuple[FastAPI, FakeChannel]:
    """An app whose WhatsApp channel accepts nothing (the window is closed), so every send
    fails for good."""
    channel = FakeChannel(clock=lambda: NOON_IST)
    app = build_app(
        notification_settings(quiet_hours_start="00:00", quiet_hours_end="00:00", **settings),
        channels={Channel.WHATSAPP: channel},
    )
    app.state.wiring.set_opt_in.run(
        Channel.WHATSAPP, PHONE, opted_in=True, source=ConsentSource.API
    )
    return app, channel


def key() -> dict[str, str]:
    return {"Idempotency-Key": uuid4().hex}


def store_of(app: FastAPI) -> MemoryStore:
    store = app.state.wiring.unit_of_work
    assert isinstance(store, MemoryStore)
    return store


def failed_notification(client: TestClient, headers: dict[str, str]) -> str:
    body = send_body()
    failed = client.post("/v1/notification/send", json=body, headers=headers)
    assert failed.status_code == 200, failed.text
    assert failed.json()["outcome"] == "failed"
    return str(body["notification_id"])


def test_a_resend_needs_a_reason_and_a_key_and_replays_a_retry() -> None:
    app, _ = failing_app()
    with TestClient(app) as client:
        notification_id = failed_notification(client, TENANT)
        path = f"/v1/notification/notifications/{notification_id}/resend"
        no_reason = client.post(path, json={}, headers={**TENANT, **key()})
        assert no_reason.status_code == 422, no_reason.text
        assert no_reason.json()["type"].endswith(":request-invalid")
        no_key = client.post(path, json=REASON, headers=TENANT)
        assert no_key.status_code == 428, no_key.text
        retry = key()
        first = client.post(path, json=REASON, headers={**TENANT, **retry})
        assert first.status_code == 200, first.text
        assert (first.json()["state"], first.json()["attempts"]) == ("queued", 0)
        assert "Idempotent-Replayed" not in first.headers
        replayed = client.post(path, json=REASON, headers={**TENANT, **retry})
        assert replayed.status_code == 200, replayed.text
        assert replayed.headers["Idempotent-Replayed"] == "true"
        assert replayed.json() == first.json(), "the same answer, and nothing queued twice"
        other_body = client.post(
            path, json={"reason": "Example: another reason"}, headers={**TENANT, **retry}
        )
        assert other_body.status_code == 422
        assert other_body.json()["type"].endswith(":idempotency-key-reused")
        new_key = client.post(path, json=REASON, headers={**TENANT, **key()})
        assert new_key.status_code == 409, "queued already"
    entries = [entry for entry in store_of(app).audit if entry.action == RESENT_ACTION]
    assert len(entries) == 1, "one resend, one row; the replay writes nothing"
    (entry,) = entries
    assert (entry.tenant_id, entry.subject_type, entry.subject_id, entry.reason) == (
        TENANT_ID,
        "notification",
        notification_id,
        REASON["reason"],
    )
    assert entry.actor.label == "system:notification", "header mode names nobody"
    assert entry.before is not None
    assert entry.before["state"] == "failed"
    assert entry.after is not None
    assert (entry.after["state"], entry.after["channel"], entry.after["recipient_named"]) == (
        "queued",
        "whatsapp",
        False,
    )
    assert PHONE not in str(entry.after), "no address after"
    assert PHONE not in str(entry.before), "no address before"


def test_the_recipient_named_must_be_the_notification_s_own() -> None:
    app, _ = failing_app()
    with TestClient(app) as client:
        notification_id = failed_notification(client, TENANT)
        path = f"/v1/notification/notifications/{notification_id}/resend"
        other = client.post(
            path, json={**REASON, "recipient": "919812345678"}, headers={**TENANT, **key()}
        )
        assert other.status_code == 422, other.text
        assert other.json()["type"].endswith(":notification-resend-recipient-mismatch")
        still_failed = client.get(
            f"/v1/notification/notifications/{notification_id}", headers=TENANT
        ).json()
        assert still_failed["state"] == "failed", "nothing queued"
        own = client.post(
            path, json={**REASON, "recipient": "+91 98765 43210"}, headers={**TENANT, **key()}
        )
        assert own.status_code == 200, own.text
    (entry,) = [entry for entry in store_of(app).audit if entry.action == RESENT_ACTION]
    assert entry.after is not None
    assert entry.after["recipient_named"] is True


def test_in_token_mode_tenant_admins_resend_their_own_and_the_internal_admin_names_the_tenant() -> (
    None
):
    issuer = TestIssuer()
    app, _ = failing_app(**issuer.settings_overrides("token"))
    owner = bearer(issuer.user(TENANT_ID, [Role.OWNER]))
    staff = bearer(issuer.user(TENANT_ID, [Role.STAFF]))
    other_owner = bearer(issuer.user(OTHER_TENANT_ID, [Role.OWNER]))
    admin = bearer(issuer.user(TenantId.new(), [Role.ADMIN], mfa=True))
    analyst = bearer(issuer.user(TenantId.new(), [Role.ANALYST], mfa=True))
    sender = bearer(issuer.service("worker", [Scope.NOTIFICATION_SEND, Scope.TENANT_ACT]))
    with TestClient(app) as client:
        notification_id = failed_notification(client, {**sender, **TENANT})
        path = f"/v1/notification/notifications/{notification_id}/resend"
        assert client.post(path, json=REASON, headers=key()).status_code == 401
        for refused in (staff, analyst, sender):
            response = client.post(path, json=REASON, headers={**refused, **TENANT, **key()})
            assert response.status_code == 403, response.text
        elsewhere = client.post(path, json=REASON, headers={**other_owner, **key()})
        assert elsewhere.status_code == 404, "another tenant's owner sees no such notification"
        mismatch = client.post(path, json=REASON, headers={**other_owner, **TENANT, **key()})
        assert mismatch.status_code == 403
        assert mismatch.json()["type"].endswith(":auth-tenant-mismatch")
        no_tenant = client.post(path, json=REASON, headers={**admin, **key()})
        assert no_tenant.status_code == 401, "the internal admin names the tenant"
        assert no_tenant.json()["type"].endswith(":notification-tenant-required")
        by_admin = client.post(path, json=REASON, headers={**admin, **TENANT, **key()})
        assert by_admin.status_code == 200, by_admin.text
        second = failed_notification(client, {**sender, **TENANT})
        by_owner = client.post(
            f"/v1/notification/notifications/{second}/resend",
            json=REASON,
            headers={**owner, **key()},
        )
        assert by_owner.status_code == 200, by_owner.text
    entries = [entry for entry in store_of(app).audit if entry.action == RESENT_ACTION]
    assert [entry.actor.label for entry in entries] == ["admin", "owner"]
    assert {entry.tenant_id for entry in entries} == {TENANT_ID}


def test_the_use_case_refuses_a_blank_reason_and_a_foreign_recipient() -> None:
    app, _ = failing_app()
    with TestClient(app) as client:
        notification_id = failed_notification(client, TENANT)
    resend = ResendNotification(store_of(app))
    actor = AuditActor.system("test")
    with pytest.raises(ValueError, match="reason"):
        resend.run(TENANT_ID, NotificationId.parse(notification_id), reason=" ", actor=actor)
    with pytest.raises(ResendRecipientMismatchError):
        resend.run(
            TENANT_ID,
            NotificationId.parse(notification_id),
            reason="Example",
            actor=actor,
            recipient="919812345678",
        )
    queued = resend.run(
        TENANT_ID, NotificationId.parse(notification_id), reason="Example", actor=actor
    )
    assert queued.state is DeliveryState.QUEUED
