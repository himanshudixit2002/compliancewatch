import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from domain_kernel.access import ANONYMOUS, Principal, PrincipalKind, Role, Scope
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId, UserId
from py_common.auth import (
    ALGORITHM,
    AuthKeysUnavailableError,
    AuthTokenInvalidError,
    JwksUrlSource,
    KeySet,
    SigningKey,
    StaticKeySource,
    TokenIssuer,
    TokenVerifier,
    claims_of,
    generate_signing_key,
    load_signing_keys,
    principal_from_claims,
)
from py_common.auth.testing import TestIssuer, bearer
from py_common.auth.tokens import parse_jwks
from py_common.settings import Settings

_TENANT = TenantId(UUID("33333333-3333-4333-8333-333333333333"))
_USER = UserId(UUID("44444444-4444-4444-8444-444444444444"))
_ISSUER = "urn:compliancewatch:identity"
_AUDIENCE = "compliancewatch"
_JWKS_URL = "http://identity.test/v1/identity/.well-known/jwks.json"
_HMAC_KEY = "k" * 48
"""A symmetric key for the HS256 forgery tests; any value is refused."""


def _owner() -> Principal:
    return Principal.user(_USER, _TENANT, [Role.OWNER], mfa=True, session_version=4)


def _verifier(keys: KeySet, **overrides: Any) -> TokenVerifier:
    values: dict[str, Any] = {"issuer": _ISSUER, "audience": _AUDIENCE}
    values.update(overrides)
    return TokenVerifier(StaticKeySource.from_key_set(keys), **values)


def _issuer(keys: KeySet, clock: Callable[[], datetime] = utc_now) -> TokenIssuer:
    return TokenIssuer(keys, issuer=_ISSUER, audience=_AUDIENCE, clock=clock)


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(utc_now().timestamp())
    claims: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": str(_USER),
        "kind": "user",
        "tid": str(_TENANT),
        "roles": ["owner"],
        "scp": [],
        "sv": 0,
        "mfa": False,
        "iat": now,
        "exp": now + 600,
        "jti": "a1",
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


def _sign(keys: KeySet, claims: dict[str, Any], kid: str | None = None) -> str:
    key = keys.signing_key
    return jwt.encode(claims, key.private_key, algorithm=ALGORITHM, headers={"kid": kid or key.kid})


@pytest.fixture
def keys() -> KeySet:
    return KeySet((generate_signing_key("2026-09"),))


# ---------------------------------------------------------------- issue and verify


def test_a_user_token_round_trips(keys: KeySet) -> None:
    issued = _issuer(keys).issue(_owner(), timedelta(minutes=10))
    assert _verifier(keys).verify(issued.token) == _owner()
    header = jwt.get_unverified_header(issued.token)
    assert header["alg"] == "ES256"
    assert header["kid"] == "2026-09"
    claims = jwt.decode(issued.token, options={"verify_signature": False})
    assert set(claims) == {
        "iss",
        "aud",
        "sub",
        "kind",
        "tid",
        "roles",
        "scp",
        "sv",
        "mfa",
        "iat",
        "exp",
        "jti",
    }
    assert claims["jti"] == issued.jti
    assert claims["exp"] - claims["iat"] == 600
    assert claims["exp"] == int(issued.expires_at.timestamp())
    assert (claims["kind"], claims["tid"], claims["roles"]) == ("user", str(_TENANT), ["owner"])
    assert (claims["sv"], claims["mfa"], claims["scp"]) == (4, True, [])


def test_a_service_token_round_trips_without_a_tenant(keys: KeySet) -> None:
    service = Principal.service("pipeline", [Scope.RULEBOOK_WRITE, Scope.LLM_CALL])
    issued = _issuer(keys).issue(service, timedelta(minutes=10))
    assert _verifier(keys).verify(issued.token) == service
    claims = jwt.decode(issued.token, options={"verify_signature": False})
    assert "tid" not in claims
    assert claims["scp"] == ["llm:call", "rulebook:write"]
    assert claims["roles"] == []


def test_every_token_has_its_own_id(keys: KeySet) -> None:
    issuer = _issuer(keys)
    first = issuer.issue(_owner(), timedelta(minutes=1))
    second = issuer.issue(_owner(), timedelta(minutes=1))
    assert first.jti != second.jti
    assert issuer.keys is keys


def test_the_issuer_refuses_the_anonymous_principal_and_a_non_positive_ttl(
    keys: KeySet,
) -> None:
    with pytest.raises(InvariantViolationError, match="users and services only"):
        _issuer(keys).issue(ANONYMOUS, timedelta(minutes=1))
    with pytest.raises(InvariantViolationError, match="positive"):
        _issuer(keys).issue(_owner(), timedelta(0))


def test_claims_of_names_the_principal() -> None:
    assert claims_of(Principal.service("qa", [Scope.TENANT_ACT, Scope.LLM_CALL])) == {
        "sub": "qa",
        "kind": "service",
        "roles": [],
        "scp": ["llm:call", "tenant:act"],
        "sv": 0,
        "mfa": False,
    }


# ---------------------------------------------------------------- refusals


def test_an_expired_token_is_refused(keys: KeySet) -> None:
    an_hour_ago = utc_now() - timedelta(hours=1)
    token = _issuer(keys, clock=lambda: an_hour_ago).issue(_owner(), timedelta(minutes=10))
    with pytest.raises(AuthTokenInvalidError, match="expired"):
        _verifier(keys).verify(token.token)


def test_leeway_allows_for_clock_skew(keys: KeySet) -> None:
    just_expired = utc_now() - timedelta(minutes=10, seconds=10)
    token = _issuer(keys, clock=lambda: just_expired).issue(_owner(), timedelta(minutes=10))
    assert _verifier(keys, leeway=timedelta(seconds=30)).verify(token.token) == _owner()
    with pytest.raises(AuthTokenInvalidError, match="expired"):
        _verifier(keys, leeway=timedelta(0)).verify(token.token)


@pytest.mark.parametrize(
    ("overrides", "verifier_overrides"),
    [
        ({"aud": "someone-else"}, {}),
        ({"aud": [_AUDIENCE, "someone-else"]}, {}),
        ({"iss": "https://evil.example"}, {}),
        ({}, {"audience": "another-platform"}),
        ({}, {"issuer": "urn:another:identity"}),
    ],
)
def test_wrong_audience_or_issuer_is_refused(
    keys: KeySet, overrides: dict[str, Any], verifier_overrides: dict[str, Any]
) -> None:
    token = _sign(keys, _claims(**overrides))
    with pytest.raises(AuthTokenInvalidError, match="failed verification"):
        _verifier(keys, **verifier_overrides).verify(token)


def test_a_tampered_token_is_refused(keys: KeySet) -> None:
    token = _issuer(keys).issue(_owner(), timedelta(minutes=10)).token
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["roles"] = ["owner", "admin"]
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(AuthTokenInvalidError, match="failed verification"):
        _verifier(keys).verify(f"{header}.{forged}.{signature}")


def test_a_token_signed_by_another_key_with_the_same_kid_is_refused(keys: KeySet) -> None:
    impostor = KeySet((generate_signing_key(keys.signing_key.kid),))
    token = _issuer(impostor).issue(_owner(), timedelta(minutes=10)).token
    with pytest.raises(AuthTokenInvalidError, match="failed verification"):
        _verifier(keys).verify(token)


def test_alg_none_is_refused(keys: KeySet) -> None:
    token = jwt.encode(_claims(), "", algorithm="none", headers={"kid": keys.signing_key.kid})
    with pytest.raises(AuthTokenInvalidError, match="ES256 only"):
        _verifier(keys).verify(token)


def _hs256(claims: dict[str, Any], secret: bytes, kid: str) -> str:
    """An HS256 token built by hand: pyjwt refuses to sign with a PEM key as the secret."""

    def part(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    header = part(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode())
    payload = part(json.dumps(claims).encode())
    digest = hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{part(digest)}"


def test_hs256_is_refused_even_with_the_public_key_as_secret(keys: KeySet) -> None:
    kid = keys.signing_key.kid
    public_pem = keys.signing_key.private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    for secret in (_HMAC_KEY.encode(), public_pem):
        with pytest.raises(AuthTokenInvalidError, match="ES256 only"):
            _verifier(keys).verify(_hs256(_claims(), secret, kid))


def test_a_token_naming_an_unknown_or_no_key_is_refused(keys: KeySet) -> None:
    with pytest.raises(AuthTokenInvalidError, match="unknown key"):
        _verifier(keys).verify(_sign(keys, _claims(), kid="another"))
    unnamed = jwt.encode(_claims(), keys.signing_key.private_key, algorithm=ALGORITHM)
    with pytest.raises(AuthTokenInvalidError, match="names no signing key"):
        _verifier(keys).verify(unnamed)


def test_a_published_key_of_another_type_is_refused(keys: KeySet) -> None:
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key(), as_dict=True)
    source = StaticKeySource.from_jwks({"keys": [{**jwk, "kid": "rsa"}]})
    verifier = TokenVerifier(source, issuer=_ISSUER, audience=_AUDIENCE)
    with pytest.raises(AuthTokenInvalidError, match="unknown key"):
        verifier.verify(_sign(keys, _claims(), kid="rsa"))


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "eyJhbGciOiJFUzI1NiJ9.e30"])
def test_malformed_tokens_are_refused(keys: KeySet, token: str) -> None:
    with pytest.raises(AuthTokenInvalidError):
        _verifier(keys).verify(token)


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "kind", "iat", "exp", "jti"])
def test_every_required_claim_must_be_present(keys: KeySet, claim: str) -> None:
    claims = _claims()
    del claims[claim]
    with pytest.raises(AuthTokenInvalidError):
        _verifier(keys).verify(_sign(keys, claims))


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "anonymous"},
        {"kind": "robot"},
        {"tid": None},
        {"tid": "not-a-uuid"},
        {"tid": 7},
        {"sub": "not-a-uuid"},
        {"roles": "owner"},
        {"roles": [1]},
        {"scp": ["tenant:act"]},
        {"sv": "1"},
        {"mfa": "yes"},
        {"kind": "service", "sub": "pipeline"},
    ],
)
def test_malformed_claims_are_refused(keys: KeySet, overrides: dict[str, Any]) -> None:
    with pytest.raises(AuthTokenInvalidError, match="claims are malformed"):
        _verifier(keys).verify(_sign(keys, _claims(**overrides)))


def test_unknown_roles_and_scopes_grant_nothing() -> None:
    principal = principal_from_claims(_claims(roles=["owner", "partner"]))
    assert principal.roles == {Role.OWNER}
    service = principal_from_claims(
        _claims(kind="service", sub="bot", tid=None, roles=[], scp=["llm:call", "root:all"])
    )
    assert service.kind is PrincipalKind.SERVICE
    assert service.scopes == {Scope.LLM_CALL}


# ---------------------------------------------------------------- keys


def test_a_key_set_round_trips_through_its_json(keys: KeySet) -> None:
    second = generate_signing_key("2026-10")
    both = KeySet((keys.signing_key, second))
    loaded = load_signing_keys(both.dumps())
    assert [key.kid for key in loaded.keys] == ["2026-09", "2026-10"]
    assert loaded.signing_key.kid == "2026-09"
    assert loaded.public_jwks() == both.public_jwks()


def test_the_jwks_publishes_only_public_halves(keys: KeySet) -> None:
    both = KeySet((keys.signing_key, generate_signing_key("next")))
    jwks = both.public_jwks()
    assert [entry["kid"] for entry in jwks["keys"]] == ["2026-09", "next"]
    for entry in jwks["keys"]:
        assert set(entry) == {"kty", "crv", "x", "y", "kid", "use", "alg"}
        assert (entry["kty"], entry["crv"], entry["alg"], entry["use"]) == (
            "EC",
            "P-256",
            "ES256",
            "sig",
        )


def test_a_token_signed_by_the_second_published_key_verifies(keys: KeySet) -> None:
    older = generate_signing_key("2026-08")
    token = _issuer(KeySet((older,))).issue(_owner(), timedelta(minutes=5)).token
    assert _verifier(KeySet((keys.signing_key, older))).verify(token) == _owner()


def _pem(private_key: ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey) -> str:
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("not json", "JSON array"),
        ("[]", "non-empty JSON array"),
        ('{"kid": "a"}', "non-empty JSON array"),
        ('["a"]', "exactly kid and pem"),
        ('[{"kid": "a"}]', "exactly kid and pem"),
        ('[{"kid": "a", "pem": 1}]', "must be strings"),
        ('[{"kid": "a", "pem": "garbage"}]', "not an unencrypted PEM private key"),
    ],
)
def test_malformed_key_sets_are_refused(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_signing_keys(text)


def test_only_p256_keys_sign() -> None:
    rsa_pem = _pem(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    with pytest.raises(ValueError, match="not a P-256"):
        load_signing_keys(json.dumps([{"kid": "rsa", "pem": rsa_pem}]))
    p384_pem = _pem(ec.generate_private_key(ec.SECP384R1()))
    with pytest.raises(ValueError, match="not a P-256"):
        load_signing_keys(json.dumps([{"kid": "p384", "pem": p384_pem}]))


def test_kids_are_unique_and_well_formed(keys: KeySet) -> None:
    with pytest.raises(ValueError, match="unique"):
        KeySet((keys.signing_key, keys.signing_key))
    with pytest.raises(ValueError, match="at least one"):
        KeySet(())
    private_key = keys.signing_key.private_key
    for kid in ("", " a", "a" * 65):
        with pytest.raises(ValueError, match="kid"):
            SigningKey(kid, private_key)


# ---------------------------------------------------------------- key sources


def test_parse_jwks_skips_unusable_entries(keys: KeySet) -> None:
    good = keys.public_jwks()["keys"][0]
    document = {"keys": [good, {"kty": "EC"}, {**good, "kid": 5}, "x", {"kid": "bad", "kty": "?"}]}
    assert list(parse_jwks(document)) == ["2026-09"]
    with pytest.raises(ValueError, match="keys"):
        parse_jwks({"no": "keys"})
    with pytest.raises(ValueError, match="no usable key"):
        StaticKeySource.from_jwks('{"keys": []}')


def test_the_verifier_follows_the_settings(keys: KeySet) -> None:
    issuer = TestIssuer()
    settings = Settings(_env_file=None, **issuer.settings_overrides("token"))
    assert TokenVerifier.from_settings(settings).verify(issuer.user(_TENANT)).tenant_id == _TENANT
    served = Settings(_env_file=None, auth_mode="token")
    source_client = httpx2.Client(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=issuer.jwks()))
    )
    from_url = TokenVerifier.from_settings(served, client=source_client)
    assert from_url.verify(issuer.service("qa", [Scope.LLM_CALL])).subject == "qa"


class _Jwks:
    """A JWKS endpoint for MockTransport that counts fetches."""

    def __init__(self, keys: KeySet) -> None:
        self.keys = keys
        self.fetches = 0
        self.failure: Exception | None = None
        self.status = 200

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.fetches += 1
        assert str(request.url) == _JWKS_URL
        if self.failure is not None:
            raise self.failure
        return httpx2.Response(self.status, json=self.keys.public_jwks())


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _url_verifier(endpoint: _Jwks, clock: _Clock) -> TokenVerifier:
    client = httpx2.Client(transport=httpx2.MockTransport(endpoint))
    source = JwksUrlSource(_JWKS_URL, client=client, clock=clock)
    assert source.url == _JWKS_URL
    return TokenVerifier(source, issuer=_ISSUER, audience=_AUDIENCE)


def test_the_url_source_fetches_once_and_caches_for_an_hour(keys: KeySet) -> None:
    endpoint, clock = _Jwks(keys), _Clock()
    verifier = _url_verifier(endpoint, clock)
    token = _issuer(keys).issue(_owner(), timedelta(minutes=10)).token
    for _ in range(3):
        assert verifier.verify(token) == _owner()
    assert endpoint.fetches == 1
    clock.now += 3599
    verifier.verify(token)
    assert endpoint.fetches == 1
    clock.now += 2
    verifier.verify(token)
    assert endpoint.fetches == 2


def test_an_unknown_kid_triggers_one_refetch(keys: KeySet) -> None:
    endpoint, clock = _Jwks(keys), _Clock()
    verifier = _url_verifier(endpoint, clock)
    verifier.verify(_issuer(keys).issue(_owner(), timedelta(minutes=10)).token)
    assert endpoint.fetches == 1
    rotated = KeySet((generate_signing_key("2026-10"), keys.signing_key))
    endpoint.keys = rotated
    token = _issuer(rotated).issue(_owner(), timedelta(minutes=10)).token
    assert verifier.verify(token) == _owner()
    assert endpoint.fetches == 2
    stranger = KeySet((generate_signing_key("made-up"),))
    forged = _issuer(stranger).issue(_owner(), timedelta(minutes=10)).token
    with pytest.raises(AuthTokenInvalidError, match="unknown key"):
        verifier.verify(forged)
    assert endpoint.fetches == 2, "unknown keys refetch at most once every 30 seconds"
    clock.now += 31
    with pytest.raises(AuthTokenInvalidError, match="unknown key"):
        verifier.verify(forged)
    assert endpoint.fetches == 3
    with pytest.raises(AuthTokenInvalidError, match="unknown key"):
        verifier.verify(forged)
    assert endpoint.fetches == 3


@pytest.mark.parametrize(
    "failure",
    [httpx2.ConnectError("identity is down"), httpx2.ReadTimeout("too slow"), None],
)
def test_an_unreachable_key_source_raises_keys_unavailable(
    keys: KeySet, failure: Exception | None
) -> None:
    endpoint, clock = _Jwks(keys), _Clock()
    endpoint.failure = failure
    endpoint.status = 503
    verifier = _url_verifier(endpoint, clock)
    token = _issuer(keys).issue(_owner(), timedelta(minutes=10)).token
    with pytest.raises(AuthKeysUnavailableError, match="could not be fetched"):
        verifier.verify(token)


def test_with_nothing_cached_a_failed_fetch_is_not_repeated_for_every_request(
    keys: KeySet,
) -> None:
    endpoint, clock = _Jwks(keys), _Clock()
    endpoint.failure = httpx2.ConnectError("identity is down")
    verifier = _url_verifier(endpoint, clock)
    token = _issuer(keys).issue(_owner(), timedelta(minutes=10)).token
    with pytest.raises(AuthKeysUnavailableError, match="could not be fetched"):
        verifier.verify(token)
    assert endpoint.fetches == 1
    clock.now += 4
    for _ in range(3):
        with pytest.raises(AuthKeysUnavailableError, match="next attempt is in 1 s"):
            verifier.verify(token)
    assert endpoint.fetches == 1, "requests fail at once until the next attempt is due"
    clock.now += 1
    with pytest.raises(AuthKeysUnavailableError):
        verifier.verify(token)
    assert endpoint.fetches == 2
    clock.now += 5
    endpoint.failure = None
    assert verifier.verify(token) == _owner()
    assert endpoint.fetches == 3


def test_a_malformed_key_set_document_is_unavailable(keys: KeySet) -> None:
    client = httpx2.Client(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, content=b"<html>"))
    )
    verifier = TokenVerifier(
        JwksUrlSource(_JWKS_URL, client=client), issuer=_ISSUER, audience=_AUDIENCE
    )
    with pytest.raises(AuthKeysUnavailableError):
        verifier.verify(_issuer(keys).issue(_owner(), timedelta(minutes=10)).token)


def test_cached_keys_survive_an_identity_outage(keys: KeySet) -> None:
    endpoint, clock = _Jwks(keys), _Clock()
    verifier = _url_verifier(endpoint, clock)
    token = _issuer(keys).issue(_owner(), timedelta(minutes=10)).token
    verifier.verify(token)
    endpoint.failure = httpx2.ConnectError("identity is down")
    clock.now += 3601
    assert verifier.verify(token) == _owner()
    assert endpoint.fetches == 2
    clock.now += 10
    assert verifier.verify(token) == _owner()
    assert endpoint.fetches == 2, "a failed fetch waits 30 seconds before the next attempt"
    clock.now += 21
    endpoint.failure = None
    assert verifier.verify(token) == _owner()
    assert endpoint.fetches == 3


def test_the_default_client_is_made_on_first_fetch() -> None:
    source = JwksUrlSource("http://127.0.0.1:9/jwks.json", timeout_seconds=0.5)
    with pytest.raises(AuthKeysUnavailableError):
        source.key_for("any")


# ---------------------------------------------------------------- the test issuer


def test_the_test_issuer_signs_what_its_settings_verify() -> None:
    issuer = TestIssuer()
    verifier = issuer.verifier()
    token = issuer.user(_TENANT, [Role.CA_ADMIN], mfa=True, user_id=_USER, session_version=2)
    assert verifier.verify(token) == Principal.user(
        _USER, _TENANT, [Role.CA_ADMIN], mfa=True, session_version=2
    )
    assert verifier.verify(issuer.service("bot", [Scope.TENANT_ACT])).actor_label == "service:bot"
    assert json.loads(issuer.jwks_json()) == issuer.jwks()
    assert issuer.settings_overrides("dual")["auth_mode"] == "dual"
    assert bearer("t") == {"Authorization": "Bearer t"}
    other = TestIssuer()
    with pytest.raises(AuthTokenInvalidError):
        other.verifier().verify(token)
