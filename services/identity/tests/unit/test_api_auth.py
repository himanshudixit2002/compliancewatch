"""The sign-in routes, service tokens, the public keys and ``/me``, in header, dual and token
mode."""

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.ids import TenantId
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.main import build_app
from identity.testing import (
    CHANNEL_TOKEN,
    DEV_CLIENT_SECRET,
    FAKE_PROVIDER_SECRET,
    SIGNING_KEYS,
    identity_settings,
)
from identity.wiring import Wiring
from py_common.auth import StaticKeySource, TokenVerifier
from py_common.auth.testing import bearer

PHONE = "+919876543210"
OTHER_PHONE = "+919812345678"
SESSIONS = "/v1/identity/sessions"
TENANTS = "/v1/identity/tenants"
SERVICE_TOKENS = "/v1/identity/service-tokens"
JWKS = "/v1/identity/.well-known/jwks.json"
ME = "/v1/identity/me"
DEV_TOKENS = "/v1/identity/dev/provider-tokens"
CHANNEL_CONSENTS = "/v1/identity/channel-consents"


def client_for(**overrides: Any) -> Iterator[TestClient]:
    with TestClient(build_app(identity_settings(**overrides))) as client:
        yield client


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    yield from client_for(auth_mode="token")


@pytest.fixture
def dual_mode() -> Iterator[TestClient]:
    yield from client_for(auth_mode="dual")


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def provider_token(client: TestClient, *, phone: str = PHONE, aal: str = "aal1") -> str:
    response = client.post(DEV_TOKENS, json={"phone": phone, "aal": aal})
    assert response.status_code == 200, response.text
    token: str = response.json()["provider_token"]
    return token


def sign_up(client: TestClient, *, kind: str = "business", phone: str = PHONE) -> dict[str, Any]:
    aal = "aal2" if kind == "ca_firm" else "aal1"
    created = client.post(
        TENANTS,
        json={
            "kind": kind,
            "name": "Acme Traders",
            "provider_token": provider_token(client, phone=phone, aal=aal),
            "display_name": "Asha",
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def wiring_of(client: TestClient) -> Wiring:
    app = client.app
    assert isinstance(app, FastAPI)
    wired: Wiring = app.state.wiring
    return wired


# ---------------------------------------------------------------- sign-up and sign-in


def test_sign_up_then_sign_in_in_token_mode(token_mode: TestClient) -> None:
    created = sign_up(token_mode)
    tenant, user, session = created["tenant"], created["user"], created["session"]
    assert (tenant["kind"], tenant["region"], tenant["status"]) == ("business", "in", "active")
    assert (user["roles"], user["phone"], user["display_name"]) == (["owner"], PHONE, "Asha")
    assert session["tenant_id"] == tenant["id"] == user["tenant_id"]
    assert (session["token_type"], session["expires_in"], session["mfa"]) == ("Bearer", 600, False)
    exchanged = token_mode.post(SESSIONS, json={"provider_token": provider_token(token_mode)})
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["user_id"] == user["id"]
    me = token_mode.get(ME, headers=bearer(exchanged.json()["access_token"]))
    assert me.status_code == 200, me.text
    assert me.json() == {
        "kind": "user",
        "user_id": user["id"],
        "tenant": tenant,
        "roles": ["owner"],
        "session_version": 0,
        "mfa": False,
        "email": "",
        "phone": PHONE,
        "display_name": "Asha",
    }


def test_a_new_person_is_not_provisioned_and_signs_up_once(token_mode: TestClient) -> None:
    unknown = token_mode.post(SESSIONS, json={"provider_token": provider_token(token_mode)})
    assert unknown.status_code == 404
    assert problem(unknown) == "identity-user-not-provisioned"
    sign_up(token_mode)
    again = token_mode.post(
        TENANTS,
        json={"kind": "ca_firm", "name": "Other", "provider_token": provider_token(token_mode)},
    )
    assert again.status_code == 409
    assert problem(again) == "identity-subject-registered"


def test_a_ca_firm_needs_a_second_factor(token_mode: TestClient) -> None:
    refused = token_mode.post(
        TENANTS,
        json={"kind": "ca_firm", "name": "Mehta", "provider_token": provider_token(token_mode)},
    )
    assert refused.status_code == 403
    assert problem(refused) == "identity-mfa-required"
    session = sign_up(token_mode, kind="ca_firm")["session"]
    assert (session["roles"], session["mfa"]) == (["ca_admin"], True)
    one_factor = token_mode.post(SESSIONS, json={"provider_token": provider_token(token_mode)})
    assert problem(one_factor) == "identity-mfa-required"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"provider_token": "not-a-token"}, 401),
        ({"provider_token": ""}, 422),
        ({"provider_token": "x", "extra": 1}, 422),
    ],
)
def test_a_bad_provider_token_is_refused(
    token_mode: TestClient, body: dict[str, Any], status: int
) -> None:
    response = token_mode.post(SESSIONS, json=body)
    assert response.status_code == status
    if status == 401:
        assert problem(response) == "identity-provider-token-invalid"
    tenant = token_mode.post(TENANTS, json={"kind": "internal", "name": "x", **body})
    assert tenant.status_code == 422


# ---------------------------------------------------------------- /me by mode


def test_me_in_token_mode_needs_the_users_own_token(token_mode: TestClient) -> None:
    session = sign_up(token_mode)["session"]
    no_token = token_mode.get(ME)
    assert no_token.status_code == 401
    assert problem(no_token) == "auth-token-required"
    assert no_token.headers["www-authenticate"] == "Bearer"
    other_tenant = token_mode.get(
        ME, headers={**bearer(session["access_token"]), "x-tenant-id": str(uuid4())}
    )
    assert other_tenant.status_code == 403
    assert problem(other_tenant) == "auth-tenant-mismatch"
    service = service_token(token_mode, "qa")
    as_service = token_mode.get(ME, headers={**bearer(service), "x-tenant-id": str(uuid4())})
    assert as_service.status_code == 403
    assert problem(as_service) == "auth-forbidden"
    forged = token_mode.get(ME, headers=bearer(session["access_token"] + "x"))
    assert forged.status_code == 401
    assert problem(forged) == "auth-token-invalid"


def test_me_is_revoked_when_the_session_version_moves(token_mode: TestClient) -> None:
    created = sign_up(token_mode)
    headers = bearer(created["session"]["access_token"])
    assert token_mode.get(ME, headers=headers).status_code == 200
    tenant_id = TenantId.parse(created["tenant"]["id"])
    with wiring_of(token_mode).unit_of_work(tenant_id) as uow:
        (user,) = uow.users.list()
        tenant = uow.tenants.get(tenant_id)
        assert tenant is not None
        uow.users.save(
            user.with_roles(
                [Role.OWNER, Role.COMPLIANCE_LEAD], tenant, colleagues=[], at=user.updated_at
            )
        )
    revoked = token_mode.get(ME, headers=headers)
    assert revoked.status_code == 401
    assert problem(revoked) == "identity-session-revoked"
    assert revoked.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    fresh = token_mode.post(SESSIONS, json={"provider_token": provider_token(token_mode)})
    me = token_mode.get(ME, headers=bearer(fresh.json()["access_token"])).json()
    assert (me["session_version"], me["roles"]) == (1, ["compliance_lead", "owner"])


def test_me_in_header_mode_needs_a_tenant_and_then_a_token() -> None:
    for client in client_for():
        session = sign_up(client)["session"]
        no_tenant = client.get(ME, headers=bearer(session["access_token"]))
        assert no_tenant.status_code == 401
        assert problem(no_tenant) == "identity-tenant-required"
        header_only = client.get(ME, headers={"x-tenant-id": session["tenant_id"]})
        assert header_only.status_code == 401
        assert problem(header_only) == "auth-token-required"


def test_me_in_dual_mode_reads_a_bearer_when_one_comes(dual_mode: TestClient) -> None:
    session = sign_up(dual_mode)["session"]
    me = dual_mode.get(ME, headers=bearer(session["access_token"]))
    assert me.status_code == 200
    assert me.json()["tenant"]["id"] == session["tenant_id"]
    without = dual_mode.get(ME, headers={"x-tenant-id": session["tenant_id"]})
    assert problem(without) == "auth-token-required"


# ---------------------------------------------------------------- service tokens


def service_token(client: TestClient, client_id: str) -> str:
    response = client.post(
        SERVICE_TOKENS, json={"client_id": client_id, "client_secret": DEV_CLIENT_SECRET}
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def test_dev_clients_get_service_tokens_with_their_scopes(token_mode: TestClient) -> None:
    response = token_mode.post(
        SERVICE_TOKENS, json={"client_id": "whatsapp-bot", "client_secret": DEV_CLIENT_SECRET}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["token_type"], body["expires_in"]) == ("Bearer", 600)
    assert set(body["scopes"]) == {
        "identity:channel-consents",
        "notification:preferences",
        "notification:receipts",
        "tenant:act",
    }
    for wrong in (
        {"client_id": "whatsapp-bot", "client_secret": "wrong"},
        {"client_id": "nobody", "client_secret": DEV_CLIENT_SECRET},
    ):
        refused = token_mode.post(SERVICE_TOKENS, json=wrong)
        assert refused.status_code == 401
        assert problem(refused) == "identity-service-client-invalid"
    assert token_mode.post(SERVICE_TOKENS, json={"client_id": "Bad Id"}).status_code == 422


def test_without_a_dev_secret_there_are_no_dev_clients() -> None:
    for client in client_for(identity_dev_client_secret=None):
        refused = client.post(
            SERVICE_TOKENS, json={"client_id": "qa", "client_secret": DEV_CLIENT_SECRET}
        )
        assert refused.status_code == 401


def test_channel_consents_take_a_service_token_in_token_mode(token_mode: TestClient) -> None:
    body = {
        "channel": "whatsapp",
        "subject": "919876543210",
        "purpose": "whatsapp_reminders",
        "granted": False,
        "source": "whatsapp_keyword",
        "message_id": "wamid.token-mode",
    }
    shared_secret = {"x-cw-service-token": CHANNEL_TOKEN}
    shared = token_mode.post(CHANNEL_CONSENTS, json=body, headers=shared_secret)
    assert shared.status_code == 401
    assert problem(shared) == "auth-token-required"
    bot = token_mode.post(
        CHANNEL_CONSENTS, json=body, headers=bearer(service_token(token_mode, "whatsapp-bot"))
    )
    assert bot.status_code == 201, bot.text
    qa_token = bearer(service_token(token_mode, "qa"))
    qa = token_mode.post(CHANNEL_CONSENTS, json=body, headers=qa_token)
    assert qa.status_code == 403
    assert problem(qa) == "auth-forbidden"


# ---------------------------------------------------------------- the public keys


def test_the_jwks_route_publishes_only_public_keys(token_mode: TestClient) -> None:
    response = token_mode.get(JWKS)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    document = response.json()
    assert document == SIGNING_KEYS.public_jwks()
    (key,) = document["keys"]
    assert "d" not in key
    assert (key["kty"], key["crv"], key["alg"], key["use"]) == ("EC", "P-256", "ES256", "sig")
    verifier = TokenVerifier(
        StaticKeySource.from_jwks(json.dumps(document)),
        issuer="urn:compliancewatch:identity",
        audience="compliancewatch",
    )
    principal = verifier.verify(service_token(token_mode, "pipeline"))
    assert principal.scopes == {Scope.RULEBOOK_WRITE, Scope.LLM_CALL, Scope.TENANT_ACT}


# ---------------------------------------------------------------- the dev sign-in


def test_the_dev_sign_in_answers_with_the_fake_provider_locally(token_mode: TestClient) -> None:
    response = token_mode.post(DEV_TOKENS, json={"email": "Owner@Acme.Example", "aal": "aal2"})
    assert response.status_code == 200
    identity = FakeIdentityProvider(FAKE_PROVIDER_SECRET.encode()).verify(
        response.json()["provider_token"]
    )
    assert (identity.email, identity.mfa, identity.subject) == (
        "owner@acme.example",
        True,
        response.json()["subject"],
    )
    assert token_mode.post(DEV_TOKENS, json={}).status_code == 422
    assert token_mode.post(DEV_TOKENS, json={"phone": "12345"}).status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"env": "staging", "identity_dev_client_secret": None},
        {
            "auth_provider": "supabase",
            "supabase_url": "https://project-ref.supabase.test",
            "supabase_service_role_key": "test-service-role-value",
        },
    ],
)
def test_the_dev_sign_in_is_404_elsewhere(overrides: dict[str, Any]) -> None:
    for client in client_for(**overrides):
        response = client.post(DEV_TOKENS, json={"phone": PHONE})
        assert response.status_code == 404
        assert problem(response) == "identity-dev-sign-in-unavailable"


# ---------------------------------------------------------------- consents under tokens


def test_in_token_mode_recorded_by_is_the_signed_in_user(token_mode: TestClient) -> None:
    session = sign_up(token_mode)["session"]
    recorded = token_mode.post(
        "/v1/identity/consents",
        json={
            "subject": session["user_id"],
            "purpose": "terms",
            "source": "web_onboarding",
            "notice_version": "0.1-draft",
            "recorded_by": str(uuid4()),
        },
        headers=bearer(session["access_token"]),
    )
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["recorded_by"] == session["user_id"]
    anonymous = token_mode.get("/v1/identity/consents", params={"subject": "u"})
    assert anonymous.status_code == 401


def test_in_header_mode_recorded_by_comes_from_the_body() -> None:
    for client in client_for():
        named = str(uuid4())
        recorded = client.post(
            "/v1/identity/consents",
            json={
                "subject": "u",
                "purpose": "terms",
                "source": "web_onboarding",
                "notice_version": "0.1-draft",
                "recorded_by": named,
            },
            headers={"x-tenant-id": str(uuid4())},
        )
        assert recorded.json()["recorded_by"] == named
