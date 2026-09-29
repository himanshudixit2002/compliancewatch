"""The gateway client: completions with the tenant per request, embeddings with the dims
check."""

import json
from uuid import UUID

import httpx2
import pytest

from domain_kernel.ids import TenantId
from domain_kernel.llm import CompletionRequest
from domain_kernel.vectors import EMBEDDING_DIMS
from qa.domain.errors import DependencyUnavailableError, GatewayError, ModelBudgetExceededError
from qa.infrastructure.gateway import GatewayProvider, HttpEmbedder

TENANT = TenantId(UUID(int=1))
COMPLETION = {
    "text": '{"as_of": null, "steps": []}',
    "model_requested": "fake/echo",
    "model_served": "fake/echo",
    "provider": "fake",
    "input_tokens": 12,
    "output_tokens": 7,
    "cached": False,
    "cost_usd": None,
    "cost_inr": "0",
    "cost_source": "fake",
    "latency_ms": 3,
    "trace_id": "t1",
    "generation_id": "g1",
    "correlation_id": "c1",
    "pii_masked": {},
}


def embedding(dims: int = EMBEDDING_DIMS, vectors: int = 1) -> dict[str, object]:
    return {
        "model_requested": None,
        "model_served": "fake/hash-ngram-512",
        "provider": "fake",
        "dims": dims,
        "vectors": [[0.1] * dims] * vectors,
        "input_tokens": 3,
        "cost_usd": None,
        "cost_inr": "0",
        "cost_source": "fake",
        "latency_ms": 1,
        "trace_id": "t",
        "generation_id": "g",
        "correlation_id": "c",
        "pii_masked": {},
    }


def recording(status: int, body: object) -> tuple[httpx2.Client, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(status, json=body)

    return httpx2.Client(base_url="http://gw.test", transport=httpx2.MockTransport(answer)), seen


def request(tenant: TenantId | None = TENANT) -> CompletionRequest:
    return CompletionRequest(
        feature="qa",
        prompt_version="qa.plan@1",
        system="Plan.",
        user="Question: when?",
        max_tokens=1500,
        json_schema={"type": "object", "properties": {"steps": {"enum": ("s1", None)}}},
        tenant_id=tenant,
        metadata={"question_id": "q1", "stage": "plan", "attempt": "1", "layer": "kag"},
    )


def test_a_completion_carries_the_tenant_the_schema_and_the_tags() -> None:
    client, seen = recording(200, COMPLETION)
    provider = GatewayProvider(client=client)
    response = provider.complete(request())
    provider.close()
    assert (response.text, response.model, response.input_tokens, response.trace_id) == (
        '{"as_of": null, "steps": []}',
        "fake/echo",
        12,
        "t1",
    )
    (sent,) = seen
    assert (sent.url.path, sent.headers["x-tenant-id"]) == (
        "/v1/llm-gateway/completions",
        str(TENANT),
    )
    assert json.loads(sent.content) == {
        "feature": "qa",
        "prompt": "qa.plan@1",
        "system": "Plan.",
        "user": "Question: when?",
        "temperature": 0.0,
        "max_tokens": 1500,
        "metadata": {"question_id": "q1", "stage": "plan", "attempt": "1", "layer": "kag"},
        "json_schema": {"type": "object", "properties": {"steps": {"enum": ["s1", None]}}},
    }


def test_a_model_override_is_sent_and_no_tenant_means_no_header() -> None:
    client, seen = recording(200, COMPLETION)
    req = CompletionRequest(
        feature="qa", prompt_version="qa.answer@1", system="", user="u", model="fake/echo"
    )
    GatewayProvider(client=client).complete(req)
    body = json.loads(seen[0].content)
    assert body["model"] == "fake/echo"
    assert "json_schema" not in body
    assert "x-tenant-id" not in seen[0].headers


@pytest.mark.parametrize(
    ("status", "body", "detail"),
    [
        (503, {"title": "LLM provider unavailable"}, "503: .*unavailable"),
        (200, {"text": "x"}, "unexpected completion"),
    ],
)
def test_a_failed_completion_is_a_gateway_error(status: int, body: object, detail: str) -> None:
    client, _ = recording(status, body)
    with pytest.raises(GatewayError, match=detail):
        GatewayProvider(client=client).complete(request())


def test_a_used_up_budget_is_not_an_outage() -> None:
    def refuse(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429, headers={"retry-after": "86400"}, json={"title": "LLM budget exceeded"}
        )

    client = httpx2.Client(base_url="http://gw.test", transport=httpx2.MockTransport(refuse))
    with pytest.raises(ModelBudgetExceededError, match="llm-gateway answered 429") as caught:
        GatewayProvider(client=client).complete(request())
    assert caught.value.problem_headers == {"Retry-After": "86400"}
    with pytest.raises(ModelBudgetExceededError):
        HttpEmbedder(client=client).embed("when?", tenant=TENANT, metadata={})


def test_an_unreachable_gateway_is_a_gateway_error() -> None:
    def refuse(req: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("timed out", request=req)

    client = httpx2.Client(base_url="http://gw.test", transport=httpx2.MockTransport(refuse))
    with pytest.raises(GatewayError, match="unreachable"):
        GatewayProvider(client=client).complete(request())


def test_the_question_is_embedded_for_retrieval() -> None:
    client, seen = recording(200, embedding())
    embedder = HttpEmbedder(client=client)
    found = embedder.embed("when?", tenant=TENANT, metadata={"question_id": "q1"})
    embedder.close()
    assert (found.model, len(found.vector)) == ("fake/hash-ngram-512", EMBEDDING_DIMS)
    assert json.loads(seen[0].content) == {
        "feature": "retrieval",
        "inputs": ["when?"],
        "metadata": {"question_id": "q1"},
    }
    assert seen[0].headers["x-tenant-id"] == str(TENANT)


@pytest.mark.parametrize(
    ("status", "body", "detail"),
    [
        (200, embedding(dims=4), "served 4 dimensions"),
        (200, embedding(vectors=2), "unexpected shape"),
        (502, {"title": "LLM embedding dimensions mismatch"}, "answered 502"),
        (404, {"title": "Not Found"}, "no embeddings route"),
    ],
)
def test_an_unusable_embedding_is_a_dependency_failure(
    status: int, body: object, detail: str
) -> None:
    client, seen = recording(status, body)
    with pytest.raises(DependencyUnavailableError, match=detail):
        HttpEmbedder(client=client).embed("when?", tenant=None, metadata={})
    assert "x-tenant-id" not in seen[0].headers
    assert "metadata" not in json.loads(seen[0].content)
