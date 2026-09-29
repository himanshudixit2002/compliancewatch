"""The llm-gateway as an ``LLMProvider`` and an ``Embedder``: every model call the qa service
makes goes through it (ADR-008).

The tenant travels per request (``x-tenant-id`` from ``CompletionRequest.tenant_id``), so the
gateway's ledger and budget see who asked. A completion that fails is ``GatewayError``; the
planner falls back on it and the answerer turns it into ``DependencyUnavailableError``. An
embedding that fails, or that does not have the rulebook's ``EMBEDDING_DIMS`` components, is
``DependencyUnavailableError``, and hybrid search then runs on full text alone. A call the
gateway refuses because a budget is used up (429) is ``ModelBudgetExceededError``: a completion
refused so ends the question, an embedding refused so leaves search to full text.
"""

from collections.abc import Mapping
from typing import Final

import httpx2

from domain_kernel.ids import TenantId
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.vectors import EMBEDDING_DIMS
from qa.domain.errors import DependencyUnavailableError, GatewayError
from qa.domain.records import QueryEmbedding
from qa.infrastructure.http import JsonHttp, budget_exceeded, http_client, reading

COMPLETIONS_PATH: Final = "/v1/llm-gateway/completions"
EMBEDDINGS_PATH: Final = "/v1/llm-gateway/embeddings"
RETRIEVAL: Final = "retrieval"
SERVICE: Final = "llm-gateway"


class GatewayProvider:
    def __init__(
        self,
        base_url: str = "http://localhost:8008",
        *,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._client = http_client(base_url, timeout_seconds, client)

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
        headers = _tenant(req.tenant_id)
        try:
            response = self._client.post(COMPLETIONS_PATH, json=body, headers=headers)
        except httpx2.TransportError as exc:
            raise GatewayError(f"unreachable: {exc}") from exc
        if response.status_code == 429:
            raise budget_exceeded(SERVICE, response)
        if response.status_code != 200:
            raise GatewayError(f"{response.status_code}: {response.text[:500]}")
        try:
            data = response.json()
            return CompletionResponse(
                text=str(data["text"]),
                model=str(data["model_served"]),
                input_tokens=int(data["input_tokens"]),
                output_tokens=int(data["output_tokens"]),
                cached=bool(data.get("cached", False)),
                trace_id=str(data.get("trace_id", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GatewayError(f"unexpected completion: {exc}") from exc

    def close(self) -> None:
        self._client.close()


class HttpEmbedder:
    """The question's vector from the retrieval feature; the route picks the model."""

    def __init__(
        self,
        base_url: str = "http://localhost:8008",
        *,
        client: httpx2.Client | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._http = JsonHttp(http_client(base_url, timeout_seconds, client), SERVICE)

    def embed(
        self, text: str, *, tenant: TenantId | None, metadata: Mapping[str, str]
    ) -> QueryEmbedding:
        body: dict[str, object] = {"feature": RETRIEVAL, "inputs": [text]}
        if metadata:
            body["metadata"] = dict(metadata)
        data = self._http.post(EMBEDDINGS_PATH, body, headers=_tenant(tenant))
        if data is None:
            raise DependencyUnavailableError(f"{SERVICE} has no embeddings route")
        with reading(SERVICE):
            dims = int(data["dims"])
            (vector,) = data["vectors"]
            embedding = QueryEmbedding(str(data["model_served"]), tuple(float(x) for x in vector))
        if dims != EMBEDDING_DIMS or len(embedding.vector) != EMBEDDING_DIMS:
            raise DependencyUnavailableError(
                f"{SERVICE} served {dims} dimensions; the rulebook stores {EMBEDDING_DIMS}"
            )
        return embedding

    def close(self) -> None:
        self._http.close()


def _tenant(tenant: TenantId | None) -> dict[str, str]:
    return {} if tenant is None else {"x-tenant-id": str(tenant)}


def _plain(value: object) -> object:
    """Mapping proxies and tuples from the kernel's frozen schema back to JSON types."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(v) for v in value]
    return value
