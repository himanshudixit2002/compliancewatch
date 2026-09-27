"""POST /v1/llm-gateway/completions through the wired app with the fake provider."""

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.ids import TenantId
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.domain.routing import DEFAULT_ROUTES
from llm_gateway.infrastructure.ledger.memory import MemoryLedger
from llm_gateway.infrastructure.providers.fake import FakeProvider
from llm_gateway.wiring import GatewayWiring

AppFactory = Callable[..., FastAPI]

URL = "/v1/llm-gateway/completions"
PREFIX = "urn:compliancewatch:problem:"
PROBLEM = "application/problem+json"
LONG_TEXT = "The registered person shall furnish the return in FORM GSTR-3B. " * 63
"""4,032 characters: enough tokens on fake/echo for a cost above the smallest budget."""


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"feature": "smoke", "prompt": "smoke.echo@1", "user": "hello"}
    body.update(overrides)
    return body


def _entries(wiring: GatewayWiring) -> Sequence[LedgerEntry]:
    assert isinstance(wiring.ledger, MemoryLedger)
    return wiring.ledger.entries()


def _fake(wiring: GatewayWiring) -> FakeProvider:
    provider = wiring.providers["fake"]
    assert isinstance(provider, FakeProvider)
    return provider


def test_happy_path_then_cache_hit(client: TestClient, wiring: GatewayWiring) -> None:
    first = client.post(URL, json=_body())
    assert first.status_code == 200
    body = first.json()
    assert body["text"] == "fake:hello"
    assert body["model_requested"] == "fake/echo"
    assert body["model_served"] == "fake/echo"
    assert body["provider"] == "fake"
    assert body["cached"] is False
    assert body["cost_source"] == "estimate"
    assert body["cost_usd"] == "0.000001"
    assert body["cost_inr"] == "0.0001"
    assert body["input_tokens"] == 2
    assert body["output_tokens"] == 3
    assert body["generation_id"].startswith("fake-")
    assert body["pii_masked"] == {"gstin": 0, "pan": 0, "aadhaar": 0, "phone": 0, "email": 0}

    second = client.post(URL, json=_body())
    assert second.status_code == 200
    hit = second.json()
    assert hit["cached"] is True
    assert hit["cost_source"] == "cache"
    assert hit["cost_usd"] == "0.000000"
    assert hit["cost_inr"] == "0.0000"
    assert hit["latency_ms"] == 0
    assert hit["text"] == body["text"]
    assert hit["trace_id"] != body["trace_id"]

    rows = _entries(wiring)
    assert [row.cached for row in rows] == [False, True]
    assert [row.cost_source for row in rows] == [CostSource.ESTIMATE, CostSource.CACHE]
    assert [str(row.id) for row in rows] == [body["trace_id"], hit["trace_id"]]
    assert _fake(wiring).calls == 1


def test_correlation_id_is_the_request_id(client: TestClient, wiring: GatewayWiring) -> None:
    response = client.post(URL, json=_body(), headers={"x-request-id": "req-77"})
    assert response.status_code == 200
    assert response.json()["correlation_id"] == "req-77"
    assert response.headers["x-request-id"] == "req-77"
    assert _entries(wiring)[0].correlation_id == "req-77"


def test_a_minted_correlation_id_is_returned_when_none_is_sent(client: TestClient) -> None:
    response = client.post(URL, json=_body())
    assert response.json()["correlation_id"] == response.headers["x-request-id"]
    assert len(response.json()["correlation_id"]) == 32


def test_an_unusable_request_id_is_replaced_and_the_call_served(
    client: TestClient, wiring: GatewayWiring
) -> None:
    offered = "r" * 70
    response = client.post(URL, json=_body(), headers={"x-request-id": offered})
    assert response.status_code == 200
    minted = response.headers["x-request-id"]
    assert minted != offered
    assert len(minted) == 32
    int(minted, 16)
    assert response.json()["correlation_id"] == minted
    assert _entries(wiring)[0].correlation_id == minted


def test_tenant_header_reaches_the_ledger(client: TestClient, wiring: GatewayWiring) -> None:
    tenant = uuid4()
    response = client.post(URL, json=_body(), headers={"x-tenant-id": str(tenant)})
    assert response.status_code == 200
    assert _entries(wiring)[0].tenant_id == TenantId(tenant)


def test_no_tenant_header_is_a_regulatory_call(client: TestClient, wiring: GatewayWiring) -> None:
    assert client.post(URL, json=_body()).status_code == 200
    assert _entries(wiring)[0].tenant_id is None


def test_tenant_header_must_be_a_uuid(client: TestClient, wiring: GatewayWiring) -> None:
    response = client.post(URL, json=_body(), headers={"x-tenant-id": "not-a-uuid"})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    problem = response.json()
    assert problem["type"] == PREFIX + "request-invalid"
    assert problem["errors"][0]["loc"] == ["header", "x-tenant-id"]
    assert "input" not in problem["errors"][0]
    assert _entries(wiring) == ()


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"feature": "smoke", "prompt": "smoke.echo@1"}, ["body", "user"]),
        (_body(user=""), ["body", "user"]),
        (_body(feature="billing"), ["body", "feature"]),
        (_body(prompt="smoke.echo"), ["body", "prompt"]),
        (_body(prompt="Smoke.Echo@1"), ["body", "prompt"]),
        (_body(prompt="smoke@1"), ["body", "prompt"]),
        (_body(temperature=2.5), ["body", "temperature"]),
        (_body(max_tokens=0), ["body", "max_tokens"]),
        (_body(metadata={"doc": 7}), ["body", "metadata", "doc"]),
        (_body(provider="fake"), ["body", "provider"]),
    ],
)
def test_body_validation_is_a_422_problem(
    client: TestClient, wiring: GatewayWiring, body: dict[str, Any], loc: list[str]
) -> None:
    response = client.post(URL, json=body)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    problem = response.json()
    assert problem["type"] == PREFIX + "request-invalid"
    assert problem["errors"][0]["loc"] == loc
    assert _entries(wiring) == ()


def test_unregistered_prompt_is_refused_before_any_call(
    client: TestClient, wiring: GatewayWiring
) -> None:
    response = client.post(URL, json=_body(prompt="smoke.missing@3"))
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    problem = response.json()
    assert problem["type"] == PREFIX + "llm-prompt-unregistered"
    assert problem["title"] == "LLM prompt not registered"
    assert problem["detail"] == "prompt 'smoke.missing@3' is not registered"
    assert problem["instance"] == URL
    assert _entries(wiring) == ()
    assert _fake(wiring).calls == 0


def test_unregistered_prompts_can_be_allowed_by_settings(make_app: AppFactory) -> None:
    with TestClient(make_app(llm_allow_unregistered_prompts=True)) as client:
        response = client.post(URL, json=_body(prompt="smoke.missing@3"))
    assert response.status_code == 200
    assert response.json()["text"] == "fake:hello"


def test_version_zero_prompt_on_a_real_route_is_served_by_the_fake(
    client: TestClient, wiring: GatewayWiring
) -> None:
    body = _body(feature="extraction", prompt="extraction.rule_candidate@0", user="clause text")
    response = client.post(URL, json=body)
    assert response.status_code == 200
    served = response.json()
    assert served["model_requested"] == DEFAULT_ROUTES[Feature.EXTRACTION].primary
    assert served["model_served"] == DEFAULT_ROUTES[Feature.EXTRACTION].primary
    assert served["provider"] == "fake"
    assert served["cost_source"] == "estimate"
    assert _entries(wiring)[0].feature is Feature.EXTRACTION


def test_budget_exceeded_is_429_with_retry_after(make_app: AppFactory) -> None:
    app = make_app(llm_tenant_monthly_budget_inr=Decimal("0.0001"))
    headers = {"x-tenant-id": str(uuid4())}
    with TestClient(app) as client:
        first = client.post(URL, json=_body(user=LONG_TEXT), headers=headers)
        assert first.status_code == 200
        assert Decimal(first.json()["cost_inr"]) > Decimal("0.0001")

        second = client.post(URL, json=_body(user=LONG_TEXT), headers=headers)
    assert second.status_code == 429
    assert second.headers["content-type"].startswith(PROBLEM)
    assert int(second.headers["retry-after"]) >= 1
    problem = second.json()
    assert problem["type"] == PREFIX + "llm-budget-exceeded"
    assert problem["title"] == "LLM budget exceeded"
    assert "tenant budget" in problem["detail"]
    wiring: GatewayWiring = app.state.gateway
    assert len(_entries(wiring)) == 1


def test_regulatory_call_ignores_the_tenant_budget(make_app: AppFactory) -> None:
    app = make_app(llm_tenant_monthly_budget_inr=Decimal("0.0001"))
    with TestClient(app) as client:
        assert client.post(URL, json=_body(user=LONG_TEXT)).status_code == 200
        assert client.post(URL, json=_body(user=LONG_TEXT + "!")).status_code == 200


def test_provider_unavailable_is_503_with_an_error_row(
    client: TestClient, wiring: GatewayWiring
) -> None:
    _fake(wiring).fail_next(1)
    response = client.post(URL, json=_body())
    assert response.status_code == 503
    assert response.headers["content-type"].startswith(PROBLEM)
    problem = response.json()
    assert problem["type"] == PREFIX + "llm-provider-unavailable"
    assert problem["detail"] == "fake provider: injected failure"
    rows = _entries(wiring)
    assert len(rows) == 1
    assert rows[0].status is CallStatus.ERROR
    assert rows[0].error_type == "llm-provider-unavailable"
    assert rows[0].cost_inr == Decimal("0.0000")

    recovered = client.post(URL, json=_body())
    assert recovered.status_code == 200
    assert recovered.json()["cached"] is False


def test_pii_is_masked_before_the_provider_sees_it(
    client: TestClient, wiring: GatewayWiring
) -> None:
    user = "Call 9876543210, mail ops@example.com, GSTIN 27AAPFU0939F1ZV, PAN AAPFU0939F"
    response = client.post(URL, json=_body(user=user))
    assert response.status_code == 200
    body = response.json()
    assert body["pii_masked"] == {"gstin": 1, "pan": 1, "aadhaar": 0, "phone": 1, "email": 1}
    assert body["text"] == "fake:Call [PHONE], mail [EMAIL], GSTIN [GSTIN], PAN [PAN]"
    assert "9876543210" not in body["text"]


def test_model_override_names_the_served_model(client: TestClient, wiring: GatewayWiring) -> None:
    response = client.post(URL, json=_body(model="fake/other"))
    assert response.status_code == 200
    assert response.json()["model_requested"] == "fake/other"
    assert response.json()["model_served"] == "fake/other"
    assert _entries(wiring)[0].model_served == "fake/other"


@pytest.mark.parametrize("model", ["not a model id", "gpt-4", "Fake/Echo", "fake/" + "m" * 130])
def test_malformed_model_override_is_a_422_problem(
    client: TestClient, wiring: GatewayWiring, model: str
) -> None:
    response = client.post(URL, json=_body(model=model))
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    problem = response.json()
    assert problem["type"] == PREFIX + "request-invalid"
    assert problem["errors"][0]["loc"] == ["body", "model"]
    assert _entries(wiring) == ()
    assert _fake(wiring).calls == 0


def test_json_schema_and_metadata_are_passed_through(client: TestClient) -> None:
    schema = {
        "type": "object",
        "required": ["title", "score"],
        "properties": {"title": {"type": "string"}, "score": {"type": "number"}},
    }
    response = client.post(URL, json=_body(json_schema=schema, metadata={"document": "doc-9"}))
    assert response.status_code == 200
    assert response.json()["text"] == '{"title":"placeholder","score":0.0}'


def test_sampled_calls_are_never_cached(client: TestClient, wiring: GatewayWiring) -> None:
    for _ in range(2):
        response = client.post(URL, json=_body(temperature=0.7))
        assert response.status_code == 200
        assert response.json()["cached"] is False
    assert _fake(wiring).calls == 2


def test_system_prompt_counts_towards_input_tokens(client: TestClient) -> None:
    response = client.post(URL, json=_body(system="You echo."))
    assert response.status_code == 200
    assert response.json()["input_tokens"] == 4
