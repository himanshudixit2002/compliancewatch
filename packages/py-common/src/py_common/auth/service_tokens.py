"""This service's own access token, for the calls it makes to other services.

A service holds a client id and secret at the identity service (``CW_SERVICE_CLIENT_ID`` and
``CW_SERVICE_CLIENT_SECRET``). ``ServiceTokenSource`` exchanges them at
``POST /v1/identity/service-tokens`` and keeps the token until a minute before it expires, so a
process asks identity for a token about every nine minutes, not once per call. ``BearerAuth``
is the ``httpx2.Auth`` that puts the token on every request of a client; when the called
service answers 401 (the token was signed by a key it no longer trusts, say) the token is
dropped and the request is sent once more with a fresh one.

Every outgoing client is built with ``auth=service_auth_from(settings)``, which is None, and so
sends no token, while no client secret is configured. Clients built from the same settings share
one token.
"""

import asyncio
import threading
import time
from collections.abc import AsyncGenerator, Callable, Generator
from dataclasses import dataclass
from typing import Any, Final

import httpx2
from pydantic import SecretStr

from py_common.auth.errors import ServiceTokenUnavailableError
from py_common.settings import Settings

SERVICE_TOKENS_PATH: Final = "/v1/identity/service-tokens"
REFRESH_MARGIN_SECONDS: Final = 60.0
"""A cached token is replaced this long before it expires (at most half its lifetime)."""


@dataclass(frozen=True, slots=True)
class _Cached:
    token: str
    refresh_at: float


class ServiceTokenSource:
    """Gets and caches this service's access token. Thread-safe: one fetch at a time, and
    callers waiting on it get the token it fetched. ``client`` lets tests pass an
    ``httpx2.MockTransport``; it must not carry ``BearerAuth`` itself."""

    def __init__(
        self,
        identity_url: str,
        client_id: str,
        client_secret: SecretStr,
        *,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not client_id.strip():
            raise ValueError("a service token source needs a client id")
        self._url = identity_url.rstrip("/") + SERVICE_TOKENS_PATH
        self._client_id = client_id
        self._secret = client_secret
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: _Cached | None = None

    @property
    def client_id(self) -> str:
        return self._client_id

    def token(self) -> str:
        """A token valid for at least the refresh margin; ``ServiceTokenUnavailableError`` when
        identity cannot be reached or refuses the client."""
        with self._lock:
            cached = self._cached
            if cached is not None and self._clock() < cached.refresh_at:
                return cached.token
            self._cached = self._fetch()
            return self._cached.token

    def invalidate(self, token: str) -> None:
        """Drop ``token`` if it is the cached one, so the next call fetches a new token."""
        with self._lock:
            if self._cached is not None and self._cached.token == token:
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
        return _Cached(token=token, refresh_at=requested_at + expires_in - margin)


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


class BearerAuth(httpx2.Auth):
    """Sends the source's token as ``Authorization: Bearer``, and retries once with a fresh
    token when the answer is 401. The request body is read first so the retry can resend it."""

    requires_request_body = True

    def __init__(self, source: ServiceTokenSource) -> None:
        self.source = source

    def sync_auth_flow(
        self, request: httpx2.Request
    ) -> Generator[httpx2.Request, httpx2.Response, None]:
        request.read()
        token = self.source.token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == 401:
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
            self.source.invalidate(token)
            fresh = await asyncio.to_thread(self.source.token)
            request.headers["Authorization"] = f"Bearer {fresh}"
            yield request


_shared: dict[tuple[str, str, str], ServiceTokenSource] = {}
_shared_lock = threading.Lock()


def service_auth_from(
    settings: Settings, *, client: httpx2.Client | None = None
) -> BearerAuth | None:
    """The auth for this process's outgoing clients: None (no token is sent) until
    ``CW_SERVICE_CLIENT_SECRET`` is set. Clients built from the same settings share one token
    source; ``client`` (for tests) gets a source of its own."""
    secret = settings.service_client_secret
    if secret is None or not secret.get_secret_value():
        return None
    if client is not None:
        return BearerAuth(
            ServiceTokenSource(
                settings.identity_url, settings.service_client_id, secret, client=client
            )
        )
    key = (settings.identity_url, settings.service_client_id, secret.get_secret_value())
    with _shared_lock:
        source = _shared.get(key)
        if source is None:
            source = ServiceTokenSource(settings.identity_url, settings.service_client_id, secret)
            _shared[key] = source
    return BearerAuth(source)
