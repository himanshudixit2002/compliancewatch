"""Access tokens: the identity service issues them and every service verifies them.

A token is an ES256 JWT whose header names its key (``kid``) and whose claims are:

- ``iss`` and ``aud``: the identity service's issuer and the platform audience;
- ``sub``: the user id, or the service client id;
- ``kind``: ``user`` or ``service``;
- ``tid``: the user's tenant (users only);
- ``roles`` (users) and ``scp`` (services): lists of ``Role`` and ``Scope`` values;
- ``sv``: the user's session version when the token was issued;
- ``mfa``: whether the person signed in with a second factor;
- ``iat``, ``exp`` and ``jti``: issued at, expiry (seconds since the epoch) and a unique id.

The verifier accepts ES256 only, so ``none`` and HS256 tokens are refused whatever key they name.
Keys come from a ``KeySource``: ``JwksUrlSource`` fetches the identity service's JWKS and caches it
for an hour, and ``StaticKeySource`` holds a fixed key set (an inline JWKS, or the identity
service's own keys in its process). A token naming a key the cache does not hold makes the URL
source fetch once more, so a new key is picked up as soon as it signs.
"""

import json
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Protocol, Self

import httpx2
import jwt
from jwt import PyJWK

from domain_kernel.access import Principal, PrincipalKind, Role, Scope
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from py_common.auth.errors import AuthKeysUnavailableError, AuthTokenInvalidError
from py_common.auth.keys import ALGORITHM, KeySet, is_signing_curve
from py_common.logging import get_logger
from py_common.settings import Settings

REQUIRED_CLAIMS: Final = ("iss", "aud", "sub", "kind", "iat", "exp", "jti")
JWKS_CACHE_SECONDS: Final = 3600.0
"""How long a fetched key set is used before it is fetched again."""
UNKNOWN_KID_REFETCH_SECONDS: Final = 30.0
"""The least time between two fetches caused by tokens naming unknown keys, so tokens with made-up
key ids cannot turn every request into a fetch."""
FAILED_FETCH_RETRY_SECONDS: Final = 30.0
"""After a failed fetch, cached keys are used this long before the next attempt."""

log = get_logger(__name__)


# ---------------------------------------------------------------- issuing


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_at: datetime
    jti: str


class TokenIssuer:
    """Signs access tokens with the key set's first key. The identity service owns the only
    issuer; tests use one through ``py_common.auth.testing.TestIssuer``."""

    def __init__(
        self,
        keys: KeySet,
        *,
        issuer: str,
        audience: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience
        self._clock = clock

    @property
    def keys(self) -> KeySet:
        return self._keys

    def issue(self, principal: Principal, ttl: timedelta) -> IssuedToken:
        """A token naming ``principal`` that expires ``ttl`` from now."""
        if not principal.is_authenticated:
            raise InvariantViolationError("tokens are issued to users and services only")
        if ttl <= timedelta(0):
            raise InvariantViolationError("a token's time to live must be positive")
        issued_at = self._clock().astimezone(UTC).replace(microsecond=0)
        expires_at = issued_at + ttl
        jti = uuid.uuid4().hex
        claims = {
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": jti,
            **claims_of(principal),
        }
        key = self._keys.signing_key
        token = jwt.encode(claims, key.private_key, algorithm=ALGORITHM, headers={"kid": key.kid})
        return IssuedToken(token=token, expires_at=expires_at, jti=jti)


def claims_of(principal: Principal) -> dict[str, Any]:
    """The claims that name ``principal``: ``sub``, ``kind``, ``tid``, ``roles``, ``scp``,
    ``sv`` and ``mfa``. Lists are sorted so equal principals give equal claims."""
    claims: dict[str, Any] = {
        "sub": principal.subject,
        "kind": principal.kind.value,
        "roles": sorted(role.value for role in principal.roles),
        "scp": sorted(scope.value for scope in principal.scopes),
        "sv": principal.session_version,
        "mfa": principal.mfa,
    }
    if principal.tenant_id is not None:
        claims["tid"] = str(principal.tenant_id)
    return claims


def principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    """The principal verified claims name. Role and scope values this code does not know are
    left out, so a token from a newer identity service grants nothing unexpected; anything else
    malformed makes the token invalid."""
    try:
        kind = PrincipalKind(claims["kind"])
        if kind is PrincipalKind.ANONYMOUS:
            raise ValueError("tokens name users and services only")
        tenant = claims.get("tid")
        return Principal(
            kind,
            subject=claims["sub"],
            tenant_id=None if tenant is None else TenantId.parse(_text(tenant, "tid")),
            roles=_known(Role, claims.get("roles", []), "roles"),
            scopes=_known(Scope, claims.get("scp", []), "scp"),
            mfa=claims.get("mfa", False),
            session_version=claims.get("sv", 0),
        )
    except (KeyError, TypeError, ValueError) as exc:
        # InvariantViolationError is a ValueError: a claim the principal refuses lands here too.
        raise AuthTokenInvalidError(f"access token claims are malformed: {exc}") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"claim {name} must be a string")
    return value


def _known[E: StrEnum](kind: type[E], values: object, name: str) -> frozenset[E]:
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise TypeError(f"claim {name} must be a list of strings")
    known = {member.value: member for member in kind}
    return frozenset(known[value] for value in values if value in known)


# ---------------------------------------------------------------- key sources


class KeySource(Protocol):
    """Where a verifier finds the public key a token names."""

    def key_for(self, kid: str) -> PyJWK | None:
        """The key with this id, or None when the source does not hold it. Raises
        ``AuthKeysUnavailableError`` when no keys can be had at all."""
        ...


def parse_jwks(document: object) -> dict[str, PyJWK]:
    """The usable keys of a JWKS document by ``kid``. Keys without a ``kid`` and keys pyjwt
    cannot load are skipped; a document without a ``keys`` list is a ValueError."""
    if not isinstance(document, Mapping) or not isinstance(document.get("keys"), list):
        raise ValueError('a JWKS document is an object with a "keys" list')
    keys: dict[str, PyJWK] = {}
    for entry in document["keys"]:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("kid"), str):
            continue
        try:
            keys[entry["kid"]] = PyJWK(dict(entry))
        except jwt.PyJWTError:
            continue
    return keys


class StaticKeySource:
    """A fixed key set: an inline JWKS (``CW_AUTH_JWKS_JSON``) or a ``KeySet`` held in the same
    process, as the identity service holds its own."""

    def __init__(self, keys: Mapping[str, PyJWK]) -> None:
        self._keys = dict(keys)

    @classmethod
    def from_jwks(cls, document: str | Mapping[str, Any]) -> Self:
        parsed = json.loads(document) if isinstance(document, str) else document
        keys = parse_jwks(parsed)
        if not keys:
            raise ValueError("the inline JWKS holds no usable key")
        return cls(keys)

    @classmethod
    def from_key_set(cls, keys: KeySet) -> Self:
        return cls.from_jwks(keys.public_jwks())

    def key_for(self, kid: str) -> PyJWK | None:
        return self._keys.get(kid)


class JwksUrlSource:
    """The identity service's JWKS over HTTP, cached for ``cache_seconds``.

    A token naming a key the cache does not hold causes one more fetch, at most once every
    ``refetch_seconds``. When a fetch fails and keys are cached, the cached keys stay in use (so
    sessions survive an identity outage) and the next attempt waits ``retry_seconds``; with
    nothing cached the failure is ``AuthKeysUnavailableError``. Verification runs in worker
    threads, so the cache is guarded by a lock. ``client`` lets tests pass an
    ``httpx2.MockTransport``.
    """

    def __init__(
        self,
        url: str,
        *,
        client: httpx2.Client | None = None,
        cache_seconds: float = JWKS_CACHE_SECONDS,
        refetch_seconds: float = UNKNOWN_KID_REFETCH_SECONDS,
        retry_seconds: float = FAILED_FETCH_RETRY_SECONDS,
        timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._client = client
        self._cache_seconds = cache_seconds
        self._refetch_seconds = refetch_seconds
        self._retry_seconds = retry_seconds
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: dict[str, PyJWK] | None = None
        self._next_fetch = 0.0
        self._last_unknown_fetch: float | None = None

    @property
    def url(self) -> str:
        return self._url

    def key_for(self, kid: str) -> PyJWK | None:
        with self._lock:
            now = self._clock()
            if self._keys is None or now >= self._next_fetch:
                self._refresh(now)
            keys = self._keys or {}
            if kid in keys:
                return keys[kid]
            last = self._last_unknown_fetch
            if last is not None and now - last < self._refetch_seconds:
                return None
            self._last_unknown_fetch = now
            self._refresh(now)
            return (self._keys or {}).get(kid)

    def _refresh(self, now: float) -> None:
        try:
            keys = self._fetch()
        except (httpx2.HTTPError, ValueError) as exc:
            if self._keys is None:
                raise AuthKeysUnavailableError(
                    f"the signing keys at {self._url} could not be fetched"
                ) from exc
            log.warning("jwks_fetch_failed", url=self._url, error=type(exc).__name__)
            self._next_fetch = now + self._retry_seconds
            return
        self._keys = keys
        self._next_fetch = now + self._cache_seconds

    def _fetch(self) -> dict[str, PyJWK]:
        if self._client is None:
            self._client = httpx2.Client(timeout=self._timeout_seconds)
        response = self._client.get(self._url, headers={"accept": "application/json"})
        response.raise_for_status()
        return parse_jwks(response.json())


# ---------------------------------------------------------------- verifying


class TokenVerifier:
    """Verifies access tokens and returns the principal they name."""

    def __init__(
        self,
        keys: KeySource,
        *,
        issuer: str,
        audience: str,
        leeway: timedelta = timedelta(seconds=30),
    ) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway

    @classmethod
    def from_settings(cls, settings: Settings, *, client: httpx2.Client | None = None) -> Self:
        """The verifier the ``CW_AUTH_*`` settings describe: keys from ``auth_jwks_json`` when
        it is set, from ``auth_jwks_url`` otherwise."""
        source: KeySource
        if settings.auth_jwks_json is not None:
            source = StaticKeySource.from_jwks(settings.auth_jwks_json.get_secret_value())
        else:
            source = JwksUrlSource(settings.auth_jwks_url, client=client)
        return cls(
            source,
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            leeway=timedelta(seconds=settings.auth_leeway_seconds),
        )

    def verify(self, token: str) -> Principal:
        """The principal ``token`` names; ``AuthTokenInvalidError`` when it fails any check, and
        ``AuthKeysUnavailableError`` when no key can be had to check it with."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthTokenInvalidError("the access token is not a well-formed JWT") from exc
        if header.get("alg") != ALGORITHM:
            raise AuthTokenInvalidError(f"access tokens are signed with {ALGORITHM} only")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthTokenInvalidError("the access token names no signing key")
        key = self._keys.key_for(kid)
        if key is None or not is_signing_curve(key.key):
            raise AuthTokenInvalidError("the access token is signed by an unknown key")
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": list(REQUIRED_CLAIMS), "strict_aud": True},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthTokenInvalidError("the access token has expired") from exc
        except jwt.PyJWTError as exc:
            raise AuthTokenInvalidError("the access token failed verification") from exc
        return principal_from_claims(claims)
