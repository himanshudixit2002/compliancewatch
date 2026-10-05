"""Signing in with a token, across identity and profile in one process.

The path a person and a service take once ``CW_AUTH_MODE=token``. A person gets a provider token
from the identity provider (the fake one, through identity's dev route) and learns they are not
provisioned yet, so they sign up, which creates their tenant with them as its first user.
Signing in again exchanges a fresh provider token for identity's ES256 access token. The
profile service in token mode trusts only the keys identity publishes: it registers a GSTIN for
the tenant the token names, refuses a request without a token, and refuses a token whose tenant
differs from the ``x-tenant-id`` header. A service client exchanges its id and secret for a
token of its own and acts for a tenant only with tenant:act. Revoking a user takes effect at
identity at once, and at profile when the token the user already holds expires.

Both apps run on their memory stores. Nothing here reaches a real identity provider.
"""

import base64
import json
import secrets
from collections.abc import Iterator
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from domain_kernel.ids import UserId
from identity.main import build_app as build_identity
from identity.testing import DEV_CLIENT_SECRET, identity_settings
from profile_service.domain.events import ProfileUpdated
from profile_service.infrastructure.memory import MemoryStore
from profile_service.main import build_app as build_profile
from profile_service.settings import ProfileSettings
from py_common.auth import (
    ALGORITHM,
    BearerAuth,
    ServiceTokenSource,
    ServiceTokenUnavailableError,
    TokenVerifier,
)
from py_common.auth.fastapi import Authenticator
from py_common.auth.testing import bearer

IDENTITY: Final = "/v1/identity"
DEV_TOKENS: Final = f"{IDENTITY}/dev/provider-tokens"
TENANTS: Final = f"{IDENTITY}/tenants"
SESSIONS: Final = f"{IDENTITY}/sessions"
JWKS: Final = f"{IDENTITY}/.well-known/jwks.json"
ME: Final = f"{IDENTITY}/me"
USERS: Final = f"{IDENTITY}/users"
REGISTRATIONS: Final = "/v1/profile/registrations"
NODES: Final = "/v1/profile/nodes"
OWNER_PHONE: Final = "+919876543210"
OTHER_PHONE: Final = "+919812345678"
STAFF_PHONE: Final = "+919900112233"
REGISTRATION: Final = {"gstin": "29ABCDE1234F1Z5", "name": "Acme Bengaluru", "entity_name": "Acme"}
OTHER_REGISTRATION: Final = {
    "gstin": "07AAACB1234C1Z1",
    "name": "Bharat Stores Delhi",
    "entity_name": "Bharat Stores",
}
ACCESS_TOKEN_TTL_SECONDS: Final = 600
"""Identity's default ``access_token_ttl_seconds``: the longest a revoked session lasts in
another service."""
CANONICAL_CLAIMS: Final = frozenset(
    {"iss", "aud", "sub", "kind", "tid", "roles", "scp", "sv", "mfa", "iat", "exp", "jti"}
)
"""The claims every user token carries; a service token has no ``tid``."""
PIPELINE_SCOPES: Final = ["llm:call", "rulebook:write", "tenant:act"]
"""The pipeline's scopes in the committed ``identity_dev_clients.toml``."""


# ---------------------------------------------------------------- the two apps


@pytest.fixture
def identity() -> Iterator[TestClient]:
    """Identity in token mode with the fake provider. Its lifespan creates the dev service
    clients, all with ``DEV_CLIENT_SECRET``."""
    with TestClient(build_identity(identity_settings(auth_mode="token"))) as client:
        yield client


def profile_settings(**keys: Any) -> ProfileSettings:
    return ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="memory",
        auth_mode="token",
        **keys,
    )


@pytest.fixture
def profile(identity: TestClient) -> Iterator[TestClient]:
    """Profile in token mode, trusting the key set identity publishes (``CW_AUTH_JWKS_JSON``)."""
    published = identity.get(JWKS)
    assert published.status_code == 200, published.text
    with TestClient(build_profile(profile_settings(auth_jwks_json=published.text))) as client:
        yield client


# ---------------------------------------------------------------- helpers


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def segment(token: str, index: int) -> dict[str, Any]:
    """A JWT's header (0) or claims (1), decoded without checking the signature."""
    part = token.split(".")[index]
    decoded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return decoded


def provider_token(identity: TestClient, phone: str, aal: str = "aal1") -> str:
    issued = identity.post(DEV_TOKENS, json={"phone": phone, "aal": aal})
    assert issued.status_code == 200, issued.text
    token: str = issued.json()["provider_token"]
    return token


def sign_up(
    identity: TestClient, phone: str, name: str, *, kind: str = "business", aal: str = "aal1"
) -> dict[str, Any]:
    """The tenant, the first user and their session, as ``POST /tenants`` answers them."""
    created = identity.post(
        TENANTS,
        json={"kind": kind, "name": name, "provider_token": provider_token(identity, phone, aal)},
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def sign_in(identity: TestClient, phone: str, aal: str = "aal1") -> dict[str, Any]:
    """The session ``POST /sessions`` answers for a fresh provider token."""
    exchanged = identity.post(
        SESSIONS, json={"provider_token": provider_token(identity, phone, aal)}
    )
    assert exchanged.status_code == 200, exchanged.text
    body: dict[str, Any] = exchanged.json()
    return body


def pipeline_auth(identity: TestClient, client_id: str = "pipeline") -> BearerAuth:
    """The auth ``service_auth_from`` gives a dev client, its token fetched from the identity
    app in this process."""
    source = ServiceTokenSource(
        str(identity.base_url), client_id, SecretStr(DEV_CLIENT_SECRET), client=identity
    )
    return BearerAuth(source)


def profile_changers(profile: TestClient) -> list[UserId | None]:
    app = profile.app
    assert isinstance(app, FastAPI)
    store: MemoryStore = app.state.wiring.unit_of_work
    return [event.changed_by for event in store.events if isinstance(event, ProfileUpdated)]


# ---------------------------------------------------------------- a person


@pytest.mark.parametrize(
    ("kind", "aal", "role", "mfa"),
    [
        ("business", "aal1", "owner", False),
        ("ca_firm", "aal2", "ca_admin", True),
    ],
)
def test_a_person_signs_up_signs_in_and_registers_a_gstin_with_the_token(
    identity: TestClient, profile: TestClient, kind: str, aal: str, role: str, mfa: bool
) -> None:
    unknown = identity.post(
        SESSIONS, json={"provider_token": provider_token(identity, OWNER_PHONE)}
    )
    assert (unknown.status_code, problem(unknown)) == (404, "identity-user-not-provisioned")
    created = sign_up(identity, OWNER_PHONE, "Acme Traders", kind=kind, aal=aal)
    tenant, user = created["tenant"], created["user"]
    session = sign_in(identity, OWNER_PHONE, aal)
    assert (session["tenant_id"], session["user_id"], session["roles"], session["mfa"]) == (
        tenant["id"],
        user["id"],
        [role],
        mfa,
    )

    token = session["access_token"]
    header, claims = segment(token, 0), segment(token, 1)
    published = [key["kid"] for key in identity.get(JWKS).json()["keys"]]
    assert header["alg"] == ALGORITHM == "ES256"
    assert header["kid"] in published
    assert set(claims) == CANONICAL_CLAIMS
    assert (claims["kind"], claims["sub"], claims["tid"]) == ("user", user["id"], tenant["id"])
    assert (claims["roles"], claims["scp"], claims["sv"], claims["mfa"]) == ([role], [], 0, mfa)
    assert claims["exp"] - claims["iat"] == session["expires_in"] == ACCESS_TOKEN_TTL_SECONDS

    me = identity.get(ME, headers=bearer(token))
    assert me.status_code == 200, me.text
    assert (me.json()["tenant"], me.json()["roles"]) == (tenant, [role])
    assert (me.json()["session_version"], me.json()["mfa"]) == (0, mfa)

    registered = profile.post(REGISTRATIONS, json=REGISTRATION, headers=bearer(token))
    assert registered.status_code == 201, registered.text
    node = registered.json()["id"]
    snapshot = profile.get(f"{NODES}/{node}/snapshot", headers=bearer(token))
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["tenant_id"] == tenant["id"]
    changed = profile.put(
        f"{NODES}/{node}/attributes",
        json={
            "changes": [{"key": "registration_type", "value": "regular"}],
            "changed_by": str(uuid4()),
        },
        headers=bearer(token),
    )
    assert changed.status_code == 200, changed.text
    assert profile_changers(profile)[-1] == UserId(UUID(user["id"]))

    without = profile.post(REGISTRATIONS, json=REGISTRATION, headers={"x-tenant-id": tenant["id"]})
    assert (without.status_code, problem(without)) == (401, "auth-token-required")
    assert without.headers["www-authenticate"] == "Bearer"


def test_a_token_reaches_the_tenant_it_names_and_no_other(
    identity: TestClient, profile: TestClient
) -> None:
    acme = sign_up(identity, OWNER_PHONE, "Acme Traders")
    bharat = sign_up(identity, OTHER_PHONE, "Bharat Stores")
    as_acme = bearer(acme["session"]["access_token"])
    as_bharat = bearer(bharat["session"]["access_token"])
    acme_node = profile.post(REGISTRATIONS, json=REGISTRATION, headers=as_acme).json()["id"]
    bharat_node = profile.post(REGISTRATIONS, json=OTHER_REGISTRATION, headers=as_bharat)
    assert bharat_node.status_code == 201, bharat_node.text

    assert profile.get(f"{NODES}/{acme_node}", headers=as_acme).status_code == 200
    hidden = profile.get(f"{NODES}/{acme_node}", headers=as_bharat)
    assert (hidden.status_code, problem(hidden)) == (404, "profile-node-not-found")
    claimed = profile.get(
        f"{NODES}/{acme_node}", headers={**as_bharat, "x-tenant-id": acme["tenant"]["id"]}
    )
    assert (claimed.status_code, problem(claimed)) == (403, "auth-tenant-mismatch")
    written = profile.post(
        REGISTRATIONS,
        json=OTHER_REGISTRATION,
        headers={**as_acme, "x-tenant-id": bharat["tenant"]["id"]},
    )
    assert (written.status_code, problem(written)) == (403, "auth-tenant-mismatch")
    assert identity.get(ME, headers=as_bharat).json()["tenant"]["id"] == bharat["tenant"]["id"]


def test_profile_fetches_identitys_keys_by_url(identity: TestClient) -> None:
    settings = profile_settings(auth_jwks_url=f"{identity.base_url}{JWKS}")
    app = build_profile(settings)
    # The authenticator create_app builds from these settings, with the key fetch sent to the
    # identity app in this process rather than over the network.
    app.state.authenticator = Authenticator(
        "token", TokenVerifier.from_settings(settings, client=identity)
    )
    acme = sign_up(identity, OWNER_PHONE, "Acme Traders")
    with TestClient(app) as profile:
        registered = profile.post(
            REGISTRATIONS, json=REGISTRATION, headers=bearer(acme["session"]["access_token"])
        )
        assert registered.status_code == 201, registered.text
        forged = profile.post(REGISTRATIONS, json=REGISTRATION, headers=bearer("not-a-token"))
        assert (forged.status_code, problem(forged)) == (401, "auth-token-invalid")


# ---------------------------------------------------------------- a service


def test_a_service_client_acts_for_a_tenant_with_a_token_from_identity(
    identity: TestClient, profile: TestClient
) -> None:
    acme = sign_up(identity, OWNER_PHONE, "Acme Traders")
    as_acme = {"x-tenant-id": acme["tenant"]["id"]}
    pipeline = pipeline_auth(identity)
    registered = profile.post(REGISTRATIONS, json=REGISTRATION, headers=as_acme, auth=pipeline)
    assert registered.status_code == 201, registered.text

    token = pipeline.source.token()
    claims = segment(token, 1)
    assert (claims["kind"], claims["sub"], claims["scp"], claims["roles"]) == (
        "service",
        "pipeline",
        PIPELINE_SCOPES,
        [],
    )
    assert "tid" not in claims
    unnamed = profile.post(REGISTRATIONS, json=REGISTRATION, headers=bearer(token))
    assert (unnamed.status_code, problem(unnamed)) == (401, "tenant-required")
    assert profile_changers(profile) == []

    # A client without tenant:act may not act for a tenant. Every committed dev client holds it
    # now, so this one comes from an identity with one dev client of its own, signing with the
    # same keys.
    lone = identity_settings(auth_mode="token", identity_dev_clients="reader=llm:call")
    with TestClient(build_identity(lone)) as other:
        reader = pipeline_auth(other, "reader").source.token()
    refused = profile.post(REGISTRATIONS, json=REGISTRATION, headers={**as_acme, **bearer(reader)})
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")

    wrong = ServiceTokenSource(
        str(identity.base_url),
        "pipeline",
        SecretStr(secrets.token_urlsafe(32)),
        client=identity,
    )
    with pytest.raises(ServiceTokenUnavailableError, match="identity-service-client-invalid"):
        wrong.token()


# ---------------------------------------------------------------- revocation


def test_revocation_is_immediate_at_identity_and_ends_with_the_token_at_profile(
    identity: TestClient, profile: TestClient
) -> None:
    acme = sign_up(identity, OWNER_PHONE, "Acme Traders")
    owner = bearer(acme["session"]["access_token"])
    invited = identity.post(
        USERS,
        json={"phone": STAFF_PHONE, "roles": ["staff"], "display_name": "Ravi"},
        headers=owner,
    )
    assert invited.status_code == 201, invited.text
    staff_session = sign_in(identity, STAFF_PHONE)
    as_staff = bearer(staff_session["access_token"])
    node = profile.post(REGISTRATIONS, json=REGISTRATION, headers=as_staff).json()["id"]

    disabled = identity.post(f"{USERS}/{invited.json()['id']}/disable", headers=owner)
    assert disabled.status_code == 200, disabled.text
    revoked = identity.get(ME, headers=as_staff)
    assert (revoked.status_code, problem(revoked)) == (401, "identity-session-revoked")
    signed_out = identity.post(
        SESSIONS, json={"provider_token": provider_token(identity, STAFF_PHONE)}
    )
    assert (signed_out.status_code, problem(signed_out)) == (403, "identity-user-disabled")

    # Profile checks the signature, the audience and the expiry, not the session version: the
    # token it already accepted keeps working until it expires, at most the access token's
    # lifetime after it was issued.
    assert profile.get(f"{NODES}/{node}", headers=as_staff).status_code == 200
    assert staff_session["expires_in"] == ACCESS_TOKEN_TTL_SECONDS
