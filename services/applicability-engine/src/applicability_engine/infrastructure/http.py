"""JSON over HTTP to the services a decision is computed from.

A 404 is ``None``: the thing does not exist, and the use case decides what that means. Anything
else that is not a success is ``DependencyUnavailableError`` with the service, the status and
the start of the body: a transport error, a 5xx, a refusal, or an answer that is not JSON or not
the shape the reader expects (``reading``). Retrying is the caller's choice. Tests pass their
own ``httpx2.Client`` (a ``MockTransport`` or a FastAPI ``TestClient``).

Every request carries this service's own access token once ``CW_SERVICE_CLIENT_SECRET`` is set
(``auth``, from ``py_common.auth.service_auth_from``, applied per request so an injected client
is left as it is). A token the identity service could not issue is
``DependencyUnavailableError`` too: without it the other services would refuse the call.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

import httpx2

from applicability_engine.domain.errors import DependencyUnavailableError
from py_common.auth import ServiceTokenUnavailableError

DETAIL_CHARS: Final = 300

type Params = Mapping[str, str | int]


class JsonHttp:
    """JSON GETs to ``service`` over ``client``, with ``auth`` (None sends no token)."""

    def __init__(
        self, client: httpx2.Client, service: str, *, auth: httpx2.Auth | None = None
    ) -> None:
        self._client = client
        self.service = service
        self._auth = auth

    def get(
        self,
        path: str,
        *,
        params: Params | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        try:
            response = self._client.get(
                path,
                params=dict(params or {}),
                headers=dict(headers or {}),
                auth=httpx2.USE_CLIENT_DEFAULT if self._auth is None else self._auth,
            )
        except httpx2.TransportError as exc:
            raise DependencyUnavailableError(f"{self.service} unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise DependencyUnavailableError(f"no service token for {self.service}: {exc}") from exc
        if response.status_code == 404:
            return None
        if not 200 <= response.status_code < 300:
            raise DependencyUnavailableError(
                f"{self.service} answered {response.status_code}: {response.text[:DETAIL_CHARS]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise DependencyUnavailableError(f"{self.service} answered with no JSON") from exc

    def close(self) -> None:
        self._client.close()


@contextmanager
def reading(service: str) -> Iterator[None]:
    """Turn an answer of the wrong shape into ``DependencyUnavailableError``. The kernel's
    invariant errors are ValueErrors, so a malformed specification lands here too."""
    try:
        yield
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DependencyUnavailableError(f"{service} answered an unexpected shape: {exc}") from exc


def http_client(
    base_url: str, timeout_seconds: float, client: httpx2.Client | None
) -> httpx2.Client:
    """``client`` when given, else one for ``base_url`` with the timeout."""
    return client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
