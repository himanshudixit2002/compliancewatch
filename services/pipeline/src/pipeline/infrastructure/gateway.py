"""The llm-gateway as an ``LLMProvider`` and an ``Embedder``: every model call the pipeline
makes goes through it."""

from collections.abc import Mapping, Sequence

import httpx2

from domain_kernel.llm import CompletionRequest, CompletionResponse
from pipeline.domain.embedding import EmbeddingBatch

COMPLETIONS_PATH = "/v1/llm-gateway/completions"
EMBEDDINGS_PATH = "/v1/llm-gateway/embeddings"
RETRIEVAL = "retrieval"


class GatewayError(RuntimeError):
    """The gateway refused or failed the call; the body is the problem detail."""


class GatewayProvider:
    def __init__(
        self,
        base_url: str = "http://localhost:8008",
        *,
        client: httpx2.Client | None = None,
        tenant_id: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._base_url = "" if client is not None else base_url
        self._tenant_id = tenant_id

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
        headers = {"x-tenant-id": self._tenant_id} if self._tenant_id else {}
        response = self._client.post(COMPLETIONS_PATH, json=body, headers=headers)
        if response.status_code != 200:
            raise GatewayError(f"{response.status_code}: {response.text[:500]}")
        data = response.json()
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
    whether it fits the rulebook (length, count, model) is the embedding stage's check."""

    def __init__(
        self,
        base_url: str = "http://localhost:8008",
        *,
        client: httpx2.Client | None = None,
        tenant_id: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._tenant_id = tenant_id

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
        headers = {"x-tenant-id": self._tenant_id} if self._tenant_id else {}
        response = self._client.post(EMBEDDINGS_PATH, json=body, headers=headers)
        if response.status_code != 200:
            raise GatewayError(f"{response.status_code}: {response.text[:500]}")
        data = response.json()
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
