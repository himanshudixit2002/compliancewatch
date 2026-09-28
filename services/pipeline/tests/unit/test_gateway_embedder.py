"""The gateway's embeddings route as the pipeline's ``Embedder``: the request and the answer."""

import json

import httpx2
import pytest

from pipeline.infrastructure.gateway import GatewayEmbedder, GatewayError

ANSWER = {
    "model_requested": "voyage/voyage-3.5-lite",
    "model_served": "voyage/voyage-3.5-lite",
    "provider": "voyage",
    "dims": 2,
    "vectors": [[0.6, 0.8], [1, 0]],
    "input_tokens": 12,
    "cost_usd": "0.000001",
    "cost_inr": "0.0001",
    "cost_source": "gateway",
    "latency_ms": 40,
    "trace_id": "t1",
    "generation_id": "g1",
    "correlation_id": "c1",
    "pii_masked": {},
}


def embedder(
    handler: httpx2.MockTransport | None = None, tenant_id: str | None = None
) -> tuple[GatewayEmbedder, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=ANSWER)

    transport = handler or httpx2.MockTransport(answer)
    client = httpx2.Client(base_url="http://gateway.test", transport=transport)
    return GatewayEmbedder(client=client, tenant_id=tenant_id), seen


def test_it_posts_the_retrieval_feature_and_reads_the_served_model() -> None:
    gateway, seen = embedder(tenant_id="00000000-0000-0000-0000-000000000001")
    batch = gateway.embed(
        ["first", "second"], model="voyage/voyage-3.5-lite", metadata={"document_id": "d"}
    )
    gateway.close()
    assert batch.model == "voyage/voyage-3.5-lite"
    assert batch.dims == 2
    assert batch.vectors == ((0.6, 0.8), (1.0, 0.0))
    assert (batch.input_tokens, batch.trace_id) == (12, "t1")
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", "/v1/llm-gateway/embeddings")
    assert request.headers["x-tenant-id"].endswith("0001")
    assert json.loads(request.content) == {
        "feature": "retrieval",
        "inputs": ["first", "second"],
        "model": "voyage/voyage-3.5-lite",
        "metadata": {"document_id": "d"},
    }


def test_without_an_override_the_route_decides() -> None:
    gateway, seen = embedder()
    gateway.embed(["only"])
    assert json.loads(seen[0].content) == {"feature": "retrieval", "inputs": ["only"]}
    assert "x-tenant-id" not in seen[0].headers


def test_a_refusal_is_raised_with_the_problem_body() -> None:
    refusing = httpx2.MockTransport(
        lambda _: httpx2.Response(502, json={"title": "LLM embedding dimensions mismatch"})
    )
    gateway, _ = embedder(refusing)
    with pytest.raises(GatewayError, match=r"502.*dimensions mismatch"):
        gateway.embed(["x"])
