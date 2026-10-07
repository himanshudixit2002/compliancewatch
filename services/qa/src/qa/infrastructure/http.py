"""JSON over HTTP to the services answers are built from.

A 404 is ``None``: the thing does not exist, and the caller decides what that means. A 429 is
the llm-gateway refusing a model call because a budget is used up (no other upstream answers
429): ``ModelBudgetExceededError``, with its ``Retry-After``. A 503 of the gateway's problem type
``llm-residency-unavailable`` is its residency policy refusing the call:
``ModelResidencyRefusedError``, which ends the question. Anything else that is not a success is
``DependencyUnavailableError`` with the service, the status and the start of the body: a
transport error, a 5xx, a refusal, or an answer that is not JSON or not the shape the reader
expects. Retrying is the caller's choice; a question fails fast.
Tests pass their own ``httpx2.Client`` (a ``MockTransport`` or a FastAPI ``TestClient``).

Every request carries the qa service's own access token once ``CW_SERVICE_CLIENT_SECRET`` is set
(``auth``, from ``py_common.auth.service_auth_from``, applied per request so an injected client
is left as it is). A token the identity service could not issue is
``DependencyUnavailableError`` too: without it the other services would refuse the call.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

import httpx2

from domain_kernel.errors import PROBLEM_TYPE_PREFIX
from py_common.auth import ServiceTokenUnavailableError
from qa.domain.errors import (
    DependencyUnavailableError,
    ModelBudgetExceededError,
    ModelResidencyRefusedError,
)

DETAIL_CHARS: Final = 300
RESIDENCY_PROBLEM: Final = PROBLEM_TYPE_PREFIX + "llm-residency-unavailable"
"""The llm-gateway's problem type for a call its residency policy refuses."""

type Params = Mapping[str, str | int]


class JsonHttp:
    """JSON calls to ``service`` over ``client``, with ``auth`` (None sends no token)."""

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
                auth=httpx2.USE_CLIENT_DEFAULT if self._auth is None else self._auth,
            )
        except httpx2.TransportError as exc:
            raise DependencyUnavailableError(f"{self.service} unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise DependencyUnavailableError(f"no service token for {self.service}: {exc}") from exc
        if response.status_code == 404:
            return None
        if response.status_code == 429:
            raise budget_exceeded(self.service, response)
        refused = residency_refused(self.service, response)
        if refused is not None:
            raise refused
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


def budget_exceeded(service: str, response: httpx2.Response) -> ModelBudgetExceededError:
    return ModelBudgetExceededError(
        f"{service} answered 429: {response.text[:DETAIL_CHARS]}",
        retry_after=response.headers.get("retry-after"),
    )


def residency_refused(service: str, response: httpx2.Response) -> ModelResidencyRefusedError | None:
    """The refusal as ``ModelResidencyRefusedError`` when it is the gateway's residency problem
    (a 503 of type ``RESIDENCY_PROBLEM``)."""
    if response.status_code != 503:
        return None
    try:
        problem = response.json()
    except ValueError:
        return None
    if not isinstance(problem, dict) or problem.get("type") != RESIDENCY_PROBLEM:
        return None
    detail = str(problem.get("detail") or problem.get("title") or "")
    return ModelResidencyRefusedError(
        f"{service} refuses the call under its residency policy: {detail[:DETAIL_CHARS]}"
    )


def http_client(
    base_url: str, timeout_seconds: float, client: httpx2.Client | None
) -> httpx2.Client:
    """``client`` when given, else one for ``base_url`` with the timeout."""
    return client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
