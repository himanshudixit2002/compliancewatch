"""This service's own access token, for the calls it makes to other services.

A service holds a client id and secret at the identity service (``CW_SERVICE_CLIENT_ID`` and
``CW_SERVICE_CLIENT_SECRET``). ``ServiceTokenSource`` exchanges them at
``POST /v1/identity/service-tokens`` and keeps the token until a minute before it expires, so a
process asks identity for a token about every nine minutes, not once per call. When that refresh
fails, the token keeps being used until it really expires, and the next attempt waits a few
seconds; calls in between do not wait on identity, and without a valid token they fail at once.
``BearerAuth``
is the ``httpx2.Auth`` that puts the token on every request of a client; when the called
service refuses the token itself (a 401 whose ``WWW-Authenticate`` says ``invalid_token``, or
whose problem type is ``auth-token-invalid``: the token was signed by a key it no longer trusts,
say) the token is dropped and the request is sent once more with a fresh one. Any other 401, such
as a wrong shared secret or a missing tenant, goes back to the caller as it came.

Every outgoing client is built with ``auth=service_auth_from(settings)``, which is None, and so
sends no token, while no client secret is configured. Clients built from the same settings share
one token. The client id is ``CW_SERVICE_CLIENT_ID``, or the service's name when that is empty.

A process that hosts the identity service next to the services calling each other needs no
client secrets: ``IssuerTokenSource`` mints the service's token with identity's own
``TokenIssuer`` in the process, and ``service_auth_from(settings, token_source=...)`` puts it on
the service's clients. Any object with ``client_id``, ``token()`` and ``invalidate(token)``
(``TokenSource``) will do.
"""

import asyncio
import hmac
import re
import threading
import time
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final, Protocol

import httpx2
from pydantic import SecretStr

from domain_kernel.access import Principal, PrincipalKind
from py_common.auth.errors import ServiceTokenUnavailableError
from py_common.auth.tokens import TokenIssuer
from py_common.logging import get_logger
from py_common.settings import Settings

SERVICE_TOKENS_PATH: Final = "/v1/identity/service-tokens"
REFRESH_MARGIN_SECONDS: Final = 60.0
"""A cached token is replaced this long before it expires (at most half its lifetime)."""
FAILED_FETCH_RETRY_SECONDS: Final = 5.0
"""After a failed fetch, the next attempt waits this long."""

log = get_logger(__name__)


IN_PROCESS_TOKEN_TTL: Final = timedelta(minutes=10)
"""How long a token ``IssuerTokenSource`` mints lives, the identity service's default."""


class TokenSource(Protocol):
    """Where ``BearerAuth`` gets the token it sends."""

    @property
    def client_id(self) -> str: ...

    def token(self) -> str: ...

    def invalidate(self, token: str) -> None: ...


@dataclass(frozen=True, slots=True)
class _Cached:
    token: str
    refresh_at: float
    expires_at: float

    def valid_at(self, now: float) -> bool:
        return now < self.expires_at


class ServiceTokenSource:
    """Gets and caches this service's access token. Thread-safe: one fetch at a time, and
    callers waiting on it get the token it fetched. A failed fetch leaves the cached token in use
    while it is valid, and no fetch is tried again for ``retry_seconds``. ``client`` lets tests
    pass an ``httpx2.MockTransport``; it must not carry ``BearerAuth`` itself."""

    def __init__(
        self,
        identity_url: str,
        client_id: str,
        client_secret: SecretStr,
        *,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 10.0,
        retry_seconds: float = FAILED_FETCH_RETRY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not client_id.strip():
            raise ValueError("a service token source needs a client id")
        self._url = identity_url.rstrip("/") + SERVICE_TOKENS_PATH
        self._client_id = client_id
        self._secret = client_secret
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._retry_seconds = retry_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: _Cached | None = None
        self._retry_at = 0.0
        self._failure = ""

    @property
    def client_id(self) -> str:
        return self._client_id

    def token(self) -> str:
        """A token valid for at least the refresh margin, or, while identity cannot give a new
        one, the cached token until it expires. ``ServiceTokenUnavailableError`` when there is no
        valid token and identity cannot be reached or refuses the client (at once, without asking
        identity again, for ``retry_seconds`` after a failure)."""
        with self._lock:
            cached = self._cached
            now = self._clock()
            if cached is not None and now < cached.refresh_at:
                return cached.token
            if now < self._retry_at:
                if cached is not None and cached.valid_at(now):
                    return cached.token
                raise ServiceTokenUnavailableError(
                    f"{self._failure}; the next attempt is in {self._retry_at - now:.0f} s"
                )
            try:
                self._cached = self._fetch()
            except ServiceTokenUnavailableError as exc:
                failed_at = self._clock()
                self._retry_at = failed_at + self._retry_seconds
                self._failure = exc.detail
                if cached is None or not cached.valid_at(failed_at):
                    raise
                log.warning(
                    "service_token_refresh_failed",
                    client_id=self._client_id,
                    error=exc.detail,
                    expires_in_seconds=round(cached.expires_at - failed_at),
                )
                return cached.token
            self._retry_at = 0.0
            return self._cached.token

    def invalidate(self, token: str) -> None:
        """Drop ``token`` if it is the cached one, so the next call fetches a new token."""
        with self._lock:
            if self._cached is not None and hmac.compare_digest(self._cached.token, token):
                self._cached = None

    def _fetch(self) -> _Cached:
        if self._client is None:
            self._client = httpx2.Client(timeout=self._timeout_seconds)
        body = {"client_id": self._client_id, "client_secret": self._secret.get_secret_value()}
        requested_at = self._clock()
        try:
            response = self._client.post(self._url, json=body)
        except httpx2.HTTPError as exc:
            raise ServiceTokenUnavailableError(
                f"the identity service at {self._url} could not be reached for client "
                f"{self._client_id}: {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise ServiceTokenUnavailableError(
                f"the identity service refused a token for client {self._client_id}: "
                f"{response.status_code} {_problem_type(response)}".rstrip()
            )
        token, expires_in = _parse(response)
        margin = min(REFRESH_MARGIN_SECONDS, expires_in / 2)
        expires_at = requested_at + expires_in
        return _Cached(token=token, refresh_at=expires_at - margin, expires_at=expires_at)


class IssuerTokenSource:
    """Service tokens minted in the process with the identity service's own issuer, for a
    process that hosts identity next to the services that call each other. Each token names
    ``principal`` (a service with its scopes) and is kept until a minute before it expires, as
    ``ServiceTokenSource`` keeps the ones it fetches. Thread-safe."""

    def __init__(
        self,
        issuer: TokenIssuer,
        principal: Principal,
        *,
        ttl: timedelta = IN_PROCESS_TOKEN_TTL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if principal.kind is not PrincipalKind.SERVICE:
            raise ValueError("an in-process token source mints service tokens only")
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        self._issuer = issuer
        self._principal = principal
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: _Cached | None = None

    @property
    def client_id(self) -> str:
        return self._principal.subject

    @property
    def principal(self) -> Principal:
        return self._principal

    def token(self) -> str:
        with self._lock:
            now = self._clock()
            if self._cached is not None and now < self._cached.refresh_at:
                return self._cached.token
            issued = self._issuer.issue(self._principal, self._ttl)
            lifetime = self._ttl.total_seconds()
            margin = min(REFRESH_MARGIN_SECONDS, lifetime / 2)
            self._cached = _Cached(
                token=issued.token, refresh_at=now + lifetime - margin, expires_at=now + lifetime
            )
            return issued.token

    def invalidate(self, token: str) -> None:
        with self._lock:
            if self._cached is not None and self._cached.token == token:
                self._cached = None


def _problem_type(response: httpx2.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    kind = body.get("type") if isinstance(body, dict) else None
    return kind if isinstance(kind, str) else ""


def _parse(response: httpx2.Response) -> tuple[str, float]:
    try:
        body: Any = response.json()
    except ValueError as exc:
        raise ServiceTokenUnavailableError(
            "the identity service's token response is not JSON"
        ) from exc
    if not isinstance(body, dict):
        body = {}
    token = body.get("access_token")
    expires_in = body.get("expires_in")
    token_type = body.get("token_type", "Bearer")
    if (
        not isinstance(token, str)
        or not token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, int | float)
        or expires_in <= 0
        or not isinstance(token_type, str)
        or token_type.lower() != "bearer"
    ):
        raise ServiceTokenUnavailableError(
            "the identity service's token response lacks a bearer access_token and expires_in"
        )
    return token, float(expires_in)


_INVALID_TOKEN_CHALLENGE: Final = re.compile(r'\berror\s*=\s*"?invalid_token\b', re.IGNORECASE)
"""RFC 6750's error code for a bearer token that is expired, revoked or otherwise invalid."""
_INVALID_TOKEN_PROBLEM: Final = re.compile(r"(^|[:/])auth-token-invalid$")


def token_refused(response: httpx2.Response) -> bool:
    """Whether ``response`` refuses the bearer token itself, which a fresh token may cure: a 401
    with an RFC 6750 ``invalid_token`` challenge, or with the ``auth-token-invalid`` problem
    type. A 401 response's body must have been read."""
    if response.status_code != 401:
        return False
    challenges = response.headers.get_list("www-authenticate")
    if any(_INVALID_TOKEN_CHALLENGE.search(challenge) for challenge in challenges):
        return True
    kind = _problem_type(response)
    return _INVALID_TOKEN_PROBLEM.search(kind) is not None


class BearerAuth(httpx2.Auth):
    """Sends the source's token as ``Authorization: Bearer``, and retries once with a fresh
    token when the called service refuses the token (``token_refused``). The request body is
    read first so the retry can resend it; a 401's body is read to learn why."""

    requires_request_body = True

    def __init__(self, source: TokenSource) -> None:
        self.source = source

    def sync_auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        request.read()
        token = self.source.token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            response.read()
            if token_refused(response):
                self.source.invalidate(token)
                request.headers["Authorization"] = f"Bearer {self.source.token()}"
                yield request

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        await request.aread()
        # The source blocks on a lock and on identity; keep that off the event loop.
        token = await asyncio.to_thread(self.source.token)
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
            await response.aread()
            if token_refused(response):
                self.source.invalidate(token)
                fresh = await asyncio.to_thread(self.source.token)
                request.headers["Authorization"] = f"Bearer {fresh}"
                yield request


_shared: dict[tuple[str, str, str], ServiceTokenSource] = {}
_shared_lock = threading.Lock()


def service_client_id(settings: Settings) -> str:
    """The client this process's service tokens are for: ``CW_SERVICE_CLIENT_ID``, or the
    service's name when it is empty."""
    return settings.service_client_id.strip() or settings.service_name


def service_auth_from(
    settings: Settings,
    *,
    client: httpx2.Client | None = None,
    token_source: TokenSource | None = None,
) -> BearerAuth | None:
    """The auth for this process's outgoing clients: None (no token is sent) until
    ``CW_SERVICE_CLIENT_SECRET`` is set. Clients built from the same settings share one token
    source; ``client`` (for tests) gets a source of its own. A ``token_source`` of the caller's,
    such as an ``IssuerTokenSource`` in a process that hosts identity, is used whatever the
    settings say."""
    if token_source is not None:
        return BearerAuth(token_source)
    secret = settings.service_client_secret
    if secret is None or not secret.get_secret_value():
        return None
    client_id = service_client_id(settings)
    if client is not None:
        return BearerAuth(
            ServiceTokenSource(settings.identity_url, client_id, secret, client=client)
        )
    key = (settings.identity_url, client_id, secret.get_secret_value())
    with _shared_lock:
        source = _shared.get(key)
        if source is None:
            source = ServiceTokenSource(settings.identity_url, client_id, secret)
            _shared[key] = source
    return BearerAuth(source)
