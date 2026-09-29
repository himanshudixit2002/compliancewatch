"""The Supabase adapter against a JWKS and an admin API served by ``httpx2.MockTransport``.

The signing keys are generated at run time and the tokens carry the claims a Supabase project
issues (audience ``authenticated``, issuer ``<url>/auth/v1``, ``aal``, ``phone`` without its
plus). Nothing here reaches a real project: these are synthetic tokens and recorded shapes, and the
first real check is a manual step once the project exists.
"""

import json
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from pydantic import SecretStr

from domain_kernel.events import utc_now
from identity.domain.errors import (
    ProviderAccountExistsError,
    ProviderTokenInvalidError,
    ProviderUnavailableError,
)
from identity.domain.provider import AAL1, AAL2
from identity.infrastructure.providers.supabase import SupabaseIdentityProvider

URL = "https://project-ref.supabase.test"
ISSUER = URL + "/auth/v1"
JWKS = URL + "/auth/v1/.well-known/jwks.json"
ADMIN = URL + "/auth/v1/admin/users"
ROLE_KEY = "test-service-role-value"
LEGACY_SECRET = secrets.token_hex(24)
"""The legacy HS256 secret of a test project, made at run time."""
SUBJECT = "5f2b7c1e-8a44-4f7e-9d61-0c3b2a1f9e88"
KID = "supabase-key-1"

Handler = Callable[[httpx2.Request], httpx2.Response]


class Project:
    """A Supabase project as MockTransport serves it: the JWKS and the admin users API."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.requests: list[httpx2.Request] = []
        self.jwks_status = 200
        self.admin: Handler = lambda request: httpx2.Response(500)

    def jwks(self) -> dict[str, Any]:
        ec_jwk = ECAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        rsa_jwk = RSAAlgorithm.to_jwk(self.rsa_key.public_key(), as_dict=True)
        return {
            "keys": [
                {**ec_jwk, "kid": KID, "alg": "ES256", "use": "sig"},
                {**rsa_jwk, "kid": "rsa-key", "alg": "RS256", "use": "sig"},
            ]
        }

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if str(request.url) == JWKS:
            return httpx2.Response(self.jwks_status, json=self.jwks())
        return self.admin(request)

    def token(self, *, algorithm: str = "ES256", kid: str = KID, **overrides: Any) -> str:
        now = int(utc_now().timestamp())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": "authenticated",
            "sub": SUBJECT,
            "role": "authenticated",
            "email": "",
            "phone": "919876543210",
            "aal": AAL1,
            "amr": [{"method": "otp", "timestamp": now}],
            "session_id": "0c6f1d9e-3b2a-4c1d-8e7f-6a5b4c3d2e1f",
            "is_anonymous": False,
            "iat": now,
            "exp": now + 3600,
        }
        claims.update(overrides)
        claims = {name: value for name, value in claims.items() if value is not None}
        key: Any = self.rsa_key if algorithm == "RS256" else self.key
        return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


@pytest.fixture
def project() -> Project:
    return Project()


def provider(project: Project, **overrides: Any) -> SupabaseIdentityProvider:
    values: dict[str, Any] = {"client": httpx2.Client(transport=httpx2.MockTransport(project))}
    values.update(overrides)
    return SupabaseIdentityProvider(URL, SecretStr(ROLE_KEY), **values)


# ---------------------------------------------------------------- sign-in tokens


def test_a_supabase_token_verifies_against_the_projects_jwks(project: Project) -> None:
    supabase = provider(project)
    assert (supabase.name, supabase.issuer) == ("supabase", ISSUER)
    identity = supabase.verify(project.token())
    assert identity.subject == SUBJECT
    assert (identity.phone, identity.aal, identity.mfa) == ("919876543210", AAL1, False)
    assert identity.contact.phone == "+919876543210"
    assert identity.issued_at is not None
    stepped_up = supabase.verify(project.token(aal=AAL2, email="Owner@Acme.Example", phone=""))
    assert stepped_up.mfa
    assert stepped_up.contact.email == "owner@acme.example"
    assert supabase.verify(project.token(algorithm="RS256", kid="rsa-key")).subject == SUBJECT
    assert supabase.verify(project.token(aal="aal3")).aal == AAL1
    jwks_fetches = [r for r in project.requests if str(r.url) == JWKS]
    assert len(jwks_fetches) == 1, "the keys are cached"


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "anon"},
        {"iss": "https://other.supabase.test/auth/v1"},
        {"exp": int(utc_now().timestamp()) - 3600},
        {"sub": None},
        {"iat": None},
        {"is_anonymous": True},
        {"kid": "unknown-key"},
        {"kid": ""},
        {"algorithm": "RS256"},
    ],
)
def test_a_token_that_fails_a_check_is_refused(project: Project, overrides: dict[str, Any]) -> None:
    with pytest.raises(ProviderTokenInvalidError):
        provider(project).verify(project.token(**overrides))


def test_a_malformed_or_foreign_token_is_refused(project: Project) -> None:
    supabase = provider(project)
    now = int(utc_now().timestamp())
    claims = {"iss": ISSUER, "aud": "authenticated", "sub": SUBJECT, "iat": now, "exp": now + 60}
    unsigned = jwt.encode(claims, key="", algorithm="none")
    other_key = ec.generate_private_key(ec.SECP256R1())
    forged = jwt.encode(claims, other_key, algorithm="ES256", headers={"kid": KID})
    for token in ("not-a-jwt", unsigned, forged, project.token(sub=12)):
        with pytest.raises(ProviderTokenInvalidError):
            supabase.verify(token)


def test_legacy_hs256_tokens_need_the_jwt_secret(project: Project) -> None:
    now = int(utc_now().timestamp())
    claims = {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": SUBJECT,
        "email": "owner@acme.example",
        "iat": now,
        "exp": now + 60,
    }
    legacy = jwt.encode(claims, LEGACY_SECRET, algorithm="HS256")
    with pytest.raises(ProviderTokenInvalidError, match="CW_SUPABASE_JWT_SECRET"):
        provider(project).verify(legacy)
    accepting = provider(project, jwt_secret=SecretStr(LEGACY_SECRET))
    assert accepting.verify(legacy).contact.email == "owner@acme.example"
    wrong = jwt.encode(claims, LEGACY_SECRET + "-other", algorithm="HS256")
    with pytest.raises(ProviderTokenInvalidError):
        accepting.verify(wrong)


def test_unreachable_keys_fail_sign_in_closed(project: Project) -> None:
    project.jwks_status = 503
    with pytest.raises(ProviderUnavailableError, match="fails closed"):
        provider(project).verify(project.token())

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    offline = SupabaseIdentityProvider(
        URL, SecretStr(ROLE_KEY), client=httpx2.Client(transport=httpx2.MockTransport(refuse))
    )
    with pytest.raises(ProviderUnavailableError):
        offline.verify(project.token())


# ---------------------------------------------------------------- the admin API


def admin_headers_of(request: httpx2.Request) -> tuple[str, str]:
    return request.headers["apikey"], request.headers["authorization"]


def test_provision_creates_a_confirmed_account_and_answers_its_id(project: Project) -> None:
    def create(request: httpx2.Request) -> httpx2.Response:
        assert (request.method, str(request.url)) == ("POST", ADMIN)
        assert admin_headers_of(request) == (ROLE_KEY, f"Bearer {ROLE_KEY}")
        body = json.loads(request.content)
        assert body == {
            "email": "staff@acme.example",
            "email_confirm": True,
            "phone": "919876543210",
            "phone_confirm": True,
            "user_metadata": {"display_name": "Ravi"},
        }
        return httpx2.Response(200, json={"id": SUBJECT, "aud": "authenticated"})

    project.admin = create
    subject = provider(project).provision(
        email="Staff@Acme.Example", phone="+91 98765 43210", display_name=" Ravi "
    )
    assert subject == SUBJECT


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx2.Response(422, json={"msg": "already been registered"}), ProviderAccountExistsError),
        (httpx2.Response(409, json={}), ProviderAccountExistsError),
        (httpx2.Response(401, json={"msg": "invalid key"}), ProviderUnavailableError),
        (httpx2.Response(502), ProviderUnavailableError),
        (httpx2.Response(200, json={"id": "not-a-uuid"}), ProviderUnavailableError),
        (httpx2.Response(200, content=b"<html>"), ProviderUnavailableError),
        (httpx2.Response(200, json=["list"]), ProviderUnavailableError),
    ],
)
def test_provision_maps_what_supabase_answers(
    project: Project, response: httpx2.Response, error: type[Exception]
) -> None:
    project.admin = lambda request: response
    with pytest.raises(error):
        provider(project).provision(email="staff@acme.example")


def test_lookup_reads_an_account_and_none_when_it_is_gone(project: Project) -> None:
    def read(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "GET"
        assert admin_headers_of(request) == (ROLE_KEY, f"Bearer {ROLE_KEY}")
        if str(request.url) == f"{ADMIN}/{SUBJECT}":
            return httpx2.Response(
                200, json={"id": SUBJECT, "email": "owner@acme.example", "phone": ""}
            )
        return httpx2.Response(404, json={"msg": "User not found"})

    project.admin = read
    supabase = provider(project)
    found = supabase.lookup(SUBJECT)
    assert found is not None
    assert (found.subject, found.email) == (SUBJECT, "owner@acme.example")
    assert supabase.lookup("0b7f4c5e-1d2a-4e3f-8a9b-7c6d5e4f3a2b") is None
    assert supabase.lookup("../admin") is None
    assert all(str(r.url) != f"{ADMIN}/../admin" for r in project.requests)


def test_delete_removes_an_account_and_a_missing_one_is_fine(project: Project) -> None:
    deleted: list[str] = []

    def remove(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "DELETE"
        assert admin_headers_of(request) == (ROLE_KEY, f"Bearer {ROLE_KEY}")
        deleted.append(str(request.url))
        return httpx2.Response(200 if len(deleted) == 1 else 404, json={})

    project.admin = remove
    supabase = provider(project)
    supabase.delete(SUBJECT)
    supabase.delete(SUBJECT)
    supabase.delete("not-a-uuid")
    assert deleted == [f"{ADMIN}/{SUBJECT}", f"{ADMIN}/{SUBJECT}"]
    project.admin = lambda request: httpx2.Response(500)
    with pytest.raises(ProviderUnavailableError, match="500"):
        supabase.delete(SUBJECT)


def test_transport_errors_are_the_provider_being_unavailable(project: Project) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    project.admin = refuse
    with pytest.raises(ProviderUnavailableError, match="ReadTimeout"):
        provider(project).lookup(SUBJECT)


def test_the_adapter_needs_a_project_url_and_the_service_role_key() -> None:
    with pytest.raises(ValueError, match="URL"):
        SupabaseIdentityProvider("project-ref.supabase.test", SecretStr(ROLE_KEY))
    with pytest.raises(ValueError, match="service-role"):
        SupabaseIdentityProvider(URL, SecretStr(""))


def test_a_token_within_the_leeway_is_accepted(project: Project) -> None:
    just_expired = int((utc_now() - timedelta(seconds=10)).timestamp())
    assert provider(project).verify(project.token(exp=just_expired)).subject == SUBJECT
