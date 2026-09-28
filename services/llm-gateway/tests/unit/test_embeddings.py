"""POST /v1/llm-gateway/embeddings through the wired app with the fake provider."""

import math
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from domain_kernel.ids import TenantId
from llm_gateway.domain.features import CallStatus, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.infrastructure.ledger.memory import MemoryLedger
from llm_gateway.infrastructure.providers.fake import FakeProvider, hash_embedding
from llm_gateway.infrastructure.providers.vercel import VercelGatewayProvider
from llm_gateway.wiring import GatewayWiring

AppFactory = Callable[..., FastAPI]

URL = "/v1/llm-gateway/embeddings"
COMPLETIONS = "/v1/llm-gateway/completions"
PREFIX = "urn:compliancewatch:problem:"
PROBLEM = "application/problem+json"
CLAUSE = "x" * 8000
"""2,000 tokens: 0.0002 USD on the fake embedder at the table price, 0.0176 INR at 88."""


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"feature": "retrieval", "inputs": ["Section 7. Returns are monthly."]}
    body.update(overrides)
    return body


def _entries(wiring: GatewayWiring) -> Sequence[LedgerEntry]:
    assert isinstance(wiring.ledger, MemoryLedger)
    return wiring.ledger.entries()


def _fake(wiring: GatewayWiring) -> FakeProvider:
    provider = wiring.embedders["fake"]
    assert isinstance(provider, FakeProvider)
    return provider


def test_happy_path(client: TestClient, wiring: GatewayWiring) -> None:
    inputs = ["Section 7. Returns are monthly.", "Section 8. Refunds."]
    response = client.post(URL, json=_body(inputs=inputs), headers={"x-request-id": "req-5"})
    assert response.status_code == 200
    body = response.json()
    assert (body["model_requested"], body["model_served"], body["provider"]) == (
        "voyage/voyage-3.5-lite",
        "fake/hash-ngram-512",
        "fake",
    )
    assert body["dims"] == 512
    assert [len(vector) for vector in body["vectors"]] == [512, 512]
    assert body["vectors"] == [list(hash_embedding(text)) for text in inputs]
    assert math.isclose(math.fsum(c * c for c in body["vectors"][0]), 1.0)
    assert body["input_tokens"] == 13
    assert (body["cost_usd"], body["cost_inr"], body["cost_source"]) == (
        "0.000001",
        "0.0001",
        "estimate",
    )
    assert body["correlation_id"] == "req-5"
    assert body["generation_id"].startswith("fake-")
    assert body["pii_masked"] == {"gstin": 0, "pan": 0, "aadhaar": 0, "phone": 0, "email": 0}
    assert "cached" not in body
    assert "text" not in body

    [row] = _entries(wiring)
    assert str(row.id) == body["trace_id"]
    assert (row.feature, row.prompt_name, row.prompt_version) == (
        Feature.RETRIEVAL,
        "retrieval.embedding",
        "1",
    )
    assert (row.correlation_id, row.output_tokens, row.cached) == ("req-5", 0, False)


def test_identical_calls_are_not_cached(client: TestClient, wiring: GatewayWiring) -> None:
    first = client.post(URL, json=_body()).json()
    second = client.post(URL, json=_body()).json()
    assert first["vectors"] == second["vectors"]
    assert first["trace_id"] != second["trace_id"]
    assert _fake(wiring).calls == 2


def test_pii_is_masked_before_it_is_embedded(client: TestClient) -> None:
    response = client.post(URL, json=_body(inputs=["PAN AAPFU0939F", "mail ops@example.com"]))
    assert response.status_code == 200
    body = response.json()
    assert body["pii_masked"] == {"gstin": 0, "pan": 1, "aadhaar": 0, "phone": 0, "email": 1}
    assert body["vectors"] == [
        list(hash_embedding("PAN [PAN]")),
        list(hash_embedding("mail [EMAIL]")),
    ]


def test_tenant_header_reaches_the_ledger(client: TestClient, wiring: GatewayWiring) -> None:
    tenant = uuid4()
    assert client.post(URL, json=_body(), headers={"x-tenant-id": str(tenant)}).status_code == 200
    assert _entries(wiring)[0].tenant_id == TenantId(tenant)


def test_a_model_override_is_what_the_ledger_names(
    client: TestClient, wiring: GatewayWiring
) -> None:
    response = client.post(URL, json=_body(model="voyage/voyage-3.5"))
    assert response.status_code == 200
    assert response.json()["model_requested"] == "voyage/voyage-3.5"
    assert response.json()["model_served"] == "fake/hash-ngram-512"
    assert _entries(wiring)[0].model_requested == "voyage/voyage-3.5"


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"feature": "retrieval"}, ["body", "inputs"]),
        (_body(inputs=[]), ["body", "inputs"]),
        (_body(inputs=["a"] * 65), ["body", "inputs"]),
        (_body(inputs=["a", ""]), ["body", "inputs", 1]),
        (_body(inputs=["x" * 8001]), ["body", "inputs", 0]),
        (_body(inputs="one text"), ["body", "inputs"]),
        (_body(feature="qa"), ["body", "feature"]),
        (_body(feature="smoke"), ["body", "feature"]),
        (_body(model="Voyage/Lite"), ["body", "model"]),
        (_body(model="fake/" + "m" * 130), ["body", "model"]),
        (_body(metadata={"doc": 7}), ["body", "metadata", "doc"]),
        (_body(prompt="smoke.echo@1"), ["body", "prompt"]),
    ],
)
def test_body_validation_is_a_422_problem(
    client: TestClient, wiring: GatewayWiring, body: dict[str, Any], loc: list[str | int]
) -> None:
    response = client.post(URL, json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    problem = response.json()
    assert problem["type"] == PREFIX + "request-invalid"
    assert problem["errors"][0]["loc"] == loc
    assert _entries(wiring) == ()
    assert _fake(wiring).calls == 0


def test_the_largest_batch_is_served(client: TestClient) -> None:
    response = client.post(URL, json=_body(inputs=[CLAUSE] * 64))
    assert response.status_code == 200
    assert len(response.json()["vectors"]) == 64
    assert response.json()["input_tokens"] == 64 * 2000


def test_a_whitespace_input_is_refused_by_the_domain(
    client: TestClient, wiring: GatewayWiring
) -> None:
    response = client.post(URL, json=_body(inputs=["ok", "   "]))
    assert response.status_code == 422
    assert response.json()["type"] == PREFIX + "invariant-violation"
    assert "inputs[1] must not be blank" in response.json()["detail"]
    assert _entries(wiring) == ()


def test_a_completion_for_the_retrieval_feature_is_a_mismatch(
    client: TestClient, wiring: GatewayWiring
) -> None:
    body = {"feature": "retrieval", "prompt": "smoke.echo@1", "user": "hello"}
    response = client.post(COMPLETIONS, json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    problem = response.json()
    assert problem["type"] == PREFIX + "llm-feature-mismatch"
    assert problem["title"] == "LLM feature mismatch"
    assert problem["detail"] == "feature 'retrieval' is not served by completion calls"
    assert _entries(wiring) == ()


def test_budget_exceeded_is_429(make_app: AppFactory) -> None:
    app = make_app(llm_tenant_monthly_budget_inr=Decimal("0.0100"))
    headers = {"x-tenant-id": str(uuid4())}
    with TestClient(app) as client:
        first = client.post(URL, json=_body(inputs=[CLAUSE]), headers=headers)
        assert first.status_code == 200
        assert first.json()["cost_inr"] == "0.0176"
        second = client.post(URL, json=_body(), headers=headers)
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1
    assert second.json()["type"] == PREFIX + "llm-budget-exceeded"
    wiring: GatewayWiring = app.state.gateway
    assert len(_entries(wiring)) == 1


def test_provider_unavailable_is_503_with_an_error_row(
    client: TestClient, wiring: GatewayWiring
) -> None:
    _fake(wiring).fail_next(1)
    response = client.post(URL, json=_body())
    assert response.status_code == 503
    assert response.json()["type"] == PREFIX + "llm-provider-unavailable"
    [row] = _entries(wiring)
    assert (row.status, row.feature) == (CallStatus.ERROR, Feature.RETRIEVAL)
    assert client.post(URL, json=_body()).status_code == 200


def test_usage_reports_the_retrieval_feature(client: TestClient) -> None:
    spent = Decimal(client.post(URL, json=_body(inputs=[CLAUSE])).json()["cost_inr"])
    response = client.get("/v1/llm-gateway/usage", params={"feature": "retrieval"})
    assert response.status_code == 200
    assert (response.json()["scope"], response.json()["key"]) == ("feature", "retrieval")
    assert Decimal(response.json()["spent_inr"]) == spent


def test_models_lists_the_retrieval_route_without_a_fallback(client: TestClient) -> None:
    routes = client.get("/v1/llm-gateway/models").json()
    [retrieval] = [route for route in routes if route["feature"] == "retrieval"]
    assert retrieval == {
        "feature": "retrieval",
        "primary": "voyage/voyage-3.5-lite",
        "fallback": None,
        "only": [],
        "has": [],
        "sort": None,
        "reasoning_effort": None,
        "timeout_seconds": 15.0,
        "source": "default",
    }


def test_a_retrieval_fallback_override_stops_the_process(make_app: AppFactory) -> None:
    with pytest.raises(ValueError, match="the retrieval route takes no fallback"):
        make_app(llm_routes={"retrieval": "voyage/voyage-3.5-lite,voyage/voyage-3.5"})


def test_the_fake_serves_both_embedder_names(wiring: GatewayWiring) -> None:
    assert set(wiring.embedders) == {"fake", "vercel"}
    fake = _fake(wiring)
    assert wiring.embedders["vercel"] is fake
    assert wiring.providers["fake"] is fake


def test_the_vercel_adapter_serves_embeddings_with_the_dimensions_setting(
    make_app: AppFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[dict[str, Any]] = []
    original = VercelGatewayProvider.from_settings

    def capture(**kwargs: Any) -> VercelGatewayProvider:
        built.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(VercelGatewayProvider, "from_settings", capture)
    app = make_app(
        llm_provider="vercel",
        ai_gateway_api_key=SecretStr("placeholder"),
        llm_embedding_dimensions_param=False,
    )
    wiring: GatewayWiring = app.state.gateway
    [kwargs] = built
    assert kwargs["embedding_dimensions_param"] is False
    assert isinstance(wiring.embedders["vercel"], VercelGatewayProvider)
    assert wiring.embedders["vercel"] is wiring.providers["vercel"]
    assert isinstance(wiring.embedders["fake"], FakeProvider)
