"""The notification routes in header, dual and token mode: the scopes a service token needs for
preferences, sends and receipts, the tenant a user's token names, and the service token the
rulebook reader sends."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from domain_kernel.access import Role, Scope
from domain_kernel.ids import RuleVersionId, TenantId
from notification.domain.errors import DependencyUnavailableError
from notification.infrastructure.rulebook_client import HttpRuleVersionReader
from notification.main import build_app
from notification.testing import BOT_TOKEN, FakeClock, notification_settings
from py_common.auth import BearerAuth, ServiceTokenSource
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ISSUER = TestIssuer()
TENANT = TenantId.new()
OTHER_TENANT = TenantId.new()
AS_TENANT = {"x-tenant-id": str(TENANT)}
AS_OTHER = {"x-tenant-id": str(OTHER_TENANT)}
BOT = {"x-cw-bot-token": BOT_TOKEN}
PHONE = "+919876543210"
PREFERENCE = f"/v1/notification/preferences/whatsapp/{PHONE}"
SEND = "/v1/notification/send"
RECEIPTS = "/v1/notification/receipts/whatsapp"
RECIPIENTS = "/v1/notification/recipients"
BOT_CLIENT = bearer(
    ISSUER.service(
        "whatsapp-bot",
        [Scope.NOTIFICATION_PREFERENCES, Scope.NOTIFICATION_RECEIPTS, Scope.TENANT_ACT],
    )
)
SENDER = bearer(ISSUER.service("obligation", [Scope.NOTIFICATION_SEND, Scope.TENANT_ACT]))
SENDER_WITHOUT_TENANT = bearer(ISSUER.service("obligation", [Scope.NOTIFICATION_SEND]))
OWNER = bearer(ISSUER.user(TENANT, [Role.OWNER]))
OTHER_OWNER = bearer(ISSUER.user(OTHER_TENANT, [Role.OWNER]))
REVIEWER = bearer(ISSUER.user(TENANT, [Role.REVIEWER], mfa=True))
OPT_IN = {"opted_in": True, "source": "api"}


def client_in(mode: AuthMode, **overrides: Any) -> Iterator[TestClient]:
    settings = notification_settings(**ISSUER.settings_overrides(mode), **overrides)
    with TestClient(build_app(settings)) as client:
        yield client


@pytest.fixture
def header_mode() -> Iterator[TestClient]:
    yield from client_in("header", notification_bot_token=BOT_TOKEN)


@pytest.fixture
def dual_mode() -> Iterator[TestClient]:
    yield from client_in("dual", notification_bot_token=BOT_TOKEN)


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    yield from client_in("token", notification_bot_token=BOT_TOKEN)


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def send_body() -> dict[str, object]:
    return {
        "notification_id": str(uuid4()),
        "obligation_id": str(uuid4()),
        "business_id": str(uuid4()),
        "channel": "whatsapp",
        "recipient": PHONE,
        "template_key": "obligation_due_soon",
        "params": {"business_name": "Acme", "title": "GSTR-3B", "due_date": "D", "steps": "S"},
    }


def recipient_body() -> dict[str, object]:
    return {
        "role": "owner",
        "addresses": [{"channel": "whatsapp", "address": PHONE}],
        "businesses": [{"business_id": str(uuid4()), "label": "Acme Traders"}],
    }


# ---------------------------------------------------------------- header mode


def test_header_mode_serves_every_route_as_before(header_mode: TestClient) -> None:
    assert header_mode.put(PREFERENCE, json=OPT_IN, headers=OWNER).status_code == 200
    assert (
        header_mode.post(SEND, json=send_body(), headers={**AS_TENANT, **OWNER}).status_code == 200
    )
    missing = header_mode.post(SEND, json=send_body(), headers=SENDER)
    assert (missing.status_code, problem(missing)) == (401, "notification-tenant-required")
    assert header_mode.post(RECEIPTS, json={}, headers=BOT).status_code == 200
    refused = header_mode.post(RECEIPTS, json={}, headers=BOT_CLIENT)
    assert (refused.status_code, problem(refused)) == (401, "notification-receipt-token-invalid")


def test_header_mode_keeps_the_receipts_closed_without_a_bot_token() -> None:
    for client in client_in("header"):
        closed = client.post(RECEIPTS, json={}, headers=BOT)
        assert (closed.status_code, problem(closed)) == (503, "notification-receipts-disabled")


# ---------------------------------------------------------------- dual mode


def test_dual_mode_needs_the_preferences_scope_from_a_bearer(dual_mode: TestClient) -> None:
    keyword = {"opted_in": False, "source": "whatsapp_keyword"}
    assert dual_mode.put(PREFERENCE, json=keyword).status_code == 200
    anonymous = dual_mode.put(PREFERENCE, json=OPT_IN)
    assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required"), (
        "an api source skips the consent check, so only a service's token records it"
    )
    assert dual_mode.put(PREFERENCE, json=OPT_IN, headers=BOT_CLIENT).status_code == 200
    assert dual_mode.get(PREFERENCE, headers=BOT_CLIENT).json()["opted_in"] is True
    for caller in (OWNER, SENDER):
        refused = dual_mode.put(PREFERENCE, json=OPT_IN, headers=caller)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    bad = dual_mode.get(PREFERENCE, headers=bearer("not-a-token"))
    assert (bad.status_code, problem(bad)) == (401, "auth-token-invalid")


def test_dual_mode_sends_for_a_sender_acting_for_the_tenant(dual_mode: TestClient) -> None:
    assert dual_mode.post(SEND, json=send_body(), headers=AS_TENANT).status_code == 200
    sent = dual_mode.post(SEND, json=send_body(), headers={**SENDER, **AS_TENANT})
    assert sent.status_code == 200, sent.text
    no_tenant_act = dual_mode.post(
        SEND, json=send_body(), headers={**SENDER_WITHOUT_TENANT, **AS_TENANT}
    )
    assert (no_tenant_act.status_code, problem(no_tenant_act)) == (403, "auth-forbidden")
    for caller in (OWNER, BOT_CLIENT):
        refused = dual_mode.post(SEND, json=send_body(), headers={**caller, **AS_TENANT})
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    unnamed = dual_mode.post(SEND, json=send_body(), headers=SENDER)
    assert (unnamed.status_code, problem(unnamed)) == (401, "notification-tenant-required")


def test_dual_mode_takes_receipts_by_secret_or_by_scope(dual_mode: TestClient) -> None:
    assert dual_mode.post(RECEIPTS, json={}, headers=BOT).status_code == 200
    assert dual_mode.post(RECEIPTS, json={}, headers=BOT_CLIENT).status_code == 200
    refused = dual_mode.post(RECEIPTS, json={}, headers={**BOT, **SENDER})
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")


def test_dual_mode_without_a_bot_token_asks_for_an_access_token() -> None:
    for client in client_in("dual"):
        missing = client.post(RECEIPTS, json={}, headers=BOT)
        assert (missing.status_code, problem(missing)) == (401, "auth-token-required")
        assert client.post(RECEIPTS, json={}, headers=BOT_CLIENT).status_code == 200


def test_dual_mode_takes_the_recipients_tenant_from_the_bearer(dual_mode: TestClient) -> None:
    path = f"{RECIPIENTS}/{uuid4()}"
    assert dual_mode.put(path, json=recipient_body(), headers=OWNER).status_code == 200
    assert dual_mode.get(path, headers=AS_TENANT).status_code == 200
    assert dual_mode.get(path, headers=OTHER_OWNER).status_code == 404
    mismatch = dual_mode.get(path, headers={**OWNER, **AS_OTHER})
    assert (mismatch.status_code, problem(mismatch)) == (403, "auth-tenant-mismatch")


# ---------------------------------------------------------------- token mode


def test_token_mode_needs_a_bearer_on_every_guarded_route(token_mode: TestClient) -> None:
    for method, path, body in (
        ("PUT", PREFERENCE, OPT_IN),
        ("GET", PREFERENCE, None),
        ("POST", SEND, send_body()),
        ("POST", RECEIPTS, {}),
        ("GET", f"{RECIPIENTS}/{uuid4()}", None),
    ):
        refused = token_mode.request(method, path, json=body, headers={**AS_TENANT, **BOT})
        assert (refused.status_code, problem(refused)) == (401, "auth-token-required"), path
        assert refused.headers["www-authenticate"] == "Bearer"
    assert token_mode.get("/v1/notification/templates").status_code == 200


def test_token_mode_serves_each_caller_its_routes(token_mode: TestClient) -> None:
    assert token_mode.put(PREFERENCE, json=OPT_IN, headers=BOT_CLIENT).status_code == 200
    assert token_mode.post(RECEIPTS, json={}, headers=BOT_CLIENT).status_code == 200
    sent = token_mode.post(SEND, json=send_body(), headers={**SENDER, **AS_TENANT})
    assert sent.status_code == 200, sent.text
    path = f"{RECIPIENTS}/{uuid4()}"
    assert token_mode.put(path, json=recipient_body(), headers=OWNER).status_code == 200
    assert token_mode.get(path, headers={**BOT_CLIENT, **AS_TENANT}).status_code == 200
    assert token_mode.get(path, headers=OTHER_OWNER).status_code == 404
    other = token_mode.get(path, headers={**OWNER, **AS_OTHER})
    assert (other.status_code, problem(other)) == (403, "auth-tenant-mismatch")
    regulatory = token_mode.get(path, headers=REVIEWER)
    assert (regulatory.status_code, problem(regulatory)) == (403, "auth-forbidden")


# ---------------------------------------------------------------- the rulebook reader


def test_the_rulebook_reader_sends_the_service_token() -> None:
    seen: list[str | None] = []

    def identity(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"access_token": "tok-1", "expires_in": 600})

    def rulebook(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization"))
        return httpx2.Response(404, json={})

    source = ServiceTokenSource(
        "http://identity",
        "notification",
        SecretStr("dev-secret"),
        client=httpx2.Client(transport=httpx2.MockTransport(identity)),
    )
    rules = HttpRuleVersionReader(
        client=httpx2.Client(base_url="http://rulebook", transport=httpx2.MockTransport(rulebook)),
        auth=BearerAuth(source),
        clock=FakeClock(),
    )
    assert rules.get(RuleVersionId.new()) is None
    assert seen == ["Bearer tok-1"]
    plain = HttpRuleVersionReader(
        client=httpx2.Client(base_url="http://rulebook", transport=httpx2.MockTransport(rulebook)),
        clock=FakeClock(),
    )
    assert plain.get(RuleVersionId.new()) is None
    assert seen == ["Bearer tok-1", None]


def test_a_service_token_identity_refuses_is_a_dependency_outage() -> None:
    def identity(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"type": "urn:x:identity-service-client-invalid"})

    def rulebook(request: httpx2.Request) -> httpx2.Response:  # pragma: no cover - never reached
        return httpx2.Response(200, json={})

    source = ServiceTokenSource(
        "http://identity",
        "notification",
        SecretStr("dev-secret"),
        client=httpx2.Client(transport=httpx2.MockTransport(identity)),
    )
    rules = HttpRuleVersionReader(
        client=httpx2.Client(base_url="http://rulebook", transport=httpx2.MockTransport(rulebook)),
        auth=BearerAuth(source),
        clock=FakeClock(),
    )
    with pytest.raises(DependencyUnavailableError, match="no service token"):
        rules.get(RuleVersionId.new())
