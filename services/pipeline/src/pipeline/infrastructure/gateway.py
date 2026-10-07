"""The llm-gateway as an ``LLMProvider`` and an ``Embedder``: every model call the pipeline
makes goes through it.

Once ``CW_SERVICE_CLIENT_SECRET`` is set every call carries the pipeline's own access token
(``auth``, from ``py_common.auth.service_auth_from``); a gateway in ``token`` mode takes model
calls only from a service with the llm:call scope, and a named tenant (``x-tenant-id``) also needs
tenant:act. A token the identity service could not issue is a ``GatewayError``, which the
activities retry like any other failed call.

A call the gateway refuses because a monthly budget is used up (a 429 whose problem type is
``BUDGET_PROBLEM``) is a ``ModelBudgetExhaustedError`` with the ``Retry-After`` the gateway sent,
which the rule extraction waits out instead of failing. A call it refuses under its residency
policy (a 503 whose problem type is ``RESIDENCY_PROBLEM``) is a ``ModelResidencyRefusedError``,
which no activity retries, since the same call gets the same answer; any other refusal is a
``GatewayError``.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import httpx2

from domain_kernel.errors import PROBLEM_TYPE_PREFIX
from domain_kernel.llm import CompletionRequest, CompletionResponse
from pipeline.domain.embedding import EmbeddingBatch
from pipeline.domain.errors import ModelBudgetExhaustedError, ModelResidencyRefusedError
from py_common.auth import ServiceTokenUnavailableError

COMPLETIONS_PATH = "/v1/llm-gateway/completions"
EMBEDDINGS_PATH = "/v1/llm-gateway/embeddings"
RETRIEVAL = "retrieval"
BUDGET_PROBLEM = PROBLEM_TYPE_PREFIX + "llm-budget-exceeded"
"""The gateway's problem type for a monthly budget used up (its ``BudgetExceededError``)."""
RESIDENCY_PROBLEM = PROBLEM_TYPE_PREFIX + "llm-residency-unavailable"
"""The gateway's problem type for a call its residency policy refuses
(its ``ResidencyUnavailableError``)."""


class GatewayError(RuntimeError):
    """The gateway refused or failed the call; the body is the problem detail."""


def _problem(response: httpx2.Response, status: int, problem_type: str) -> dict[str, Any] | None:
    """The response's problem when it has ``status`` and is of ``problem_type``."""
    if response.status_code != status:
        return None
    try:
        problem = response.json()
    except ValueError:
        return None
    if not isinstance(problem, dict) or problem.get("type") != problem_type:
        return None
    return problem


def budget_exhausted(response: httpx2.Response) -> ModelBudgetExhaustedError | None:
    """The refusal as ``ModelBudgetExhaustedError`` when it is the gateway's budget problem
    (a 429 of type ``BUDGET_PROBLEM``), with its ``Retry-After`` in seconds when it sent one."""
    problem = _problem(response, 429, BUDGET_PROBLEM)
    if problem is None:
        return None
    retry_after: float | None = None
    header = response.headers.get("retry-after", "").strip()
    if header.isdigit():
        retry_after = float(header)
    detail = str(problem.get("detail") or problem.get("title") or "budget exceeded")
    return ModelBudgetExhaustedError(
        f"the llm-gateway's budget is used up: {detail[:300]}", retry_after_seconds=retry_after
    )


def residency_refused(response: httpx2.Response) -> ModelResidencyRefusedError | None:
    """The refusal as ``ModelResidencyRefusedError`` when it is the gateway's residency problem
    (a 503 of type ``RESIDENCY_PROBLEM``)."""
    problem = _problem(response, 503, RESIDENCY_PROBLEM)
    if problem is None:
        return None
    detail = str(problem.get("detail") or problem.get("title") or "residency policy")
    return ModelResidencyRefusedError(
        f"the llm-gateway refuses the call under its residency policy: {detail[:300]}"
    )


def _post(
    client: httpx2.Client,
    path: str,
    body: Mapping[str, object],
    *,
    tenant_id: str | None,
    auth: httpx2.Auth | None,
) -> Any:
    """POST ``body`` and return the JSON of a 200; a budget used up is a
    ``ModelBudgetExhaustedError``, a residency refusal a ``ModelResidencyRefusedError``, anything
    else a ``GatewayError``."""
    headers = {"x-tenant-id": tenant_id} if tenant_id else {}
    try:
        response = client.post(
            path,
            json=dict(body),
            headers=headers,
            auth=httpx2.USE_CLIENT_DEFAULT if auth is None else auth,
        )
    except ServiceTokenUnavailableError as exc:
        raise GatewayError(f"no service token for the gateway: {exc}") from exc
    if response.status_code != 200:
        budget = budget_exhausted(response)
        if budget is not None:
            raise budget
        residency = residency_refused(response)
        if residency is not None:
            raise residency
        raise GatewayError(f"{response.status_code}: {response.text[:500]}")
    return response.json()


class GatewayProvider:
    """``base_url`` is ``CW_LLM_GATEWAY_URL`` and ``auth`` the service's token auth (None sends no
    bearer). Pass ``client`` to talk to an in-process app or a mock transport; ``auth`` applies
    to it too."""

    def __init__(
        self,
        base_url: str = "http://localhost:8008",
        *,
        client: httpx2.Client | None = None,
        tenant_id: str | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._base_url = "" if client is not None else base_url
        self._tenant_id = tenant_id
        self._auth = auth

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        body: dict[str, object] = {
            "feature": req.feature,
            "prompt": req.prompt_version,
            "system": req.system,
            "user": req.user,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "metadata": dict(req.metadata),
        }
        if req.model is not None:
            body["model"] = req.model
        if req.json_schema is not None:
            body["json_schema"] = _plain(req.json_schema)
        data = _post(
            self._client, COMPLETIONS_PATH, body, tenant_id=self._tenant_id, auth=self._auth
        )
        return CompletionResponse(
            text=str(data["text"]),
            model=str(data["model_served"]),
            input_tokens=int(data["input_tokens"]),
            output_tokens=int(data["output_tokens"]),
            cached=bool(data.get("cached", False)),
            trace_id=str(data.get("trace_id", "")),
        )

    def close(self) -> None:
        self._client.close()


class GatewayEmbedder:
    """The gateway's embeddings route for the retrieval feature. The answer is read as sent;
    whether it fits the rulebook (length, count, model) is the embedding stage's check. ``auth``
    is the service's token auth, as for ``GatewayProvider``."""

    def __init__(
        self,
        base_url: str = "http://localhost:8008",
        *,
        client: httpx2.Client | None = None,
        tenant_id: str | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._tenant_id = tenant_id
        self._auth = auth

    def embed(
        self,
        inputs: Sequence[str],
        *,
        model: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> EmbeddingBatch:
        body: dict[str, object] = {"feature": RETRIEVAL, "inputs": list(inputs)}
        if model is not None:
            body["model"] = model
        if metadata:
            body["metadata"] = dict(metadata)
        data = _post(
            self._client, EMBEDDINGS_PATH, body, tenant_id=self._tenant_id, auth=self._auth
        )
        return EmbeddingBatch(
            model=str(data["model_served"]),
            dims=int(data["dims"]),
            vectors=tuple(tuple(float(x) for x in vector) for vector in data["vectors"]),
            input_tokens=int(data.get("input_tokens", 0)),
            trace_id=str(data.get("trace_id", "")),
        )

    def close(self) -> None:
        self._client.close()


def _plain(value: object) -> object:
    """Mapping proxies and tuples from the kernel's frozen schema back to JSON types."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    return value
