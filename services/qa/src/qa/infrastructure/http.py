"""JSON over HTTP to the services answers are built from.

A 404 is ``None``: the thing does not exist, and the caller decides what that means. Anything
else that is not a success is ``DependencyUnavailableError`` with the service, the status and
the start of the body: a transport error, a 5xx, a refusal, or an answer that is not JSON or
not the shape the reader expects. Retrying is the caller's choice; a question fails fast.
Tests pass their own ``httpx2.Client`` (a ``MockTransport`` or a FastAPI ``TestClient``).
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

import httpx2

from qa.domain.errors import DependencyUnavailableError

DETAIL_CHARS: Final = 300

type Params = Mapping[str, str | int]


class JsonHttp:
    def __init__(self, client: httpx2.Client, service: str) -> None:
        self._client = client
        self.service = service

    def get(
        self,
        path: str,
        *,
        params: Params | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        return self._send("GET", path, params=params, headers=headers)

    def post(
        self, path: str, body: Mapping[str, object], *, headers: Mapping[str, str] | None = None
    ) -> Any:
        return self._send("POST", path, body=body, headers=headers)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Params | None = None,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method,
                path,
                params=dict(params or {}),
                json=None if body is None else dict(body),
                headers=dict(headers or {}),
            )
        except httpx2.TransportError as exc:
            raise DependencyUnavailableError(f"{self.service} unreachable: {exc}") from exc
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
    """Turn an answer of the wrong shape into ``DependencyUnavailableError``."""
    try:
        yield
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DependencyUnavailableError(f"{service} answered an unexpected shape: {exc}") from exc


def http_client(
    base_url: str, timeout_seconds: float, client: httpx2.Client | None
) -> httpx2.Client:
    """``client`` when given, else one for ``base_url`` with the timeout."""
    return client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
