"""CW_LLM_RESIDENCY: india_only refuses every call to a real model before it is made, the fake
provider keeps answering, and GET /models reports the policy on every route."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.llm import CompletionRequest
from llm_gateway.domain.embeddings import EmbeddingRequest
from llm_gateway.domain.errors import ResidencyUnavailableError
from llm_gateway.domain.features import CallStatus, Feature
from llm_gateway.domain.residency import ResidencyPolicy
from llm_gateway.domain.routing import DEFAULT_ROUTES
from llm_gateway.infrastructure.ledger.memory import MemoryLedger
from llm_gateway.infrastructure.providers.fake import FakeProvider
from llm_gateway.infrastructure.providers.residency import ResidencyBlockedProvider
from llm_gateway.infrastructure.providers.vercel import VercelGatewayProvider
from llm_gateway.wiring import GatewayWiring

AppFactory = Callable[..., FastAPI]

COMPLETIONS = "/v1/llm-gateway/completions"
EMBEDDINGS = "/v1/llm-gateway/embeddings"
MODELS = "/v1/llm-gateway/models"
PROBLEM = "urn:compliancewatch:problem:llm-residency-unavailable"
QA = {"feature": "qa", "prompt": "smoke.echo@1", "user": "Example question about GSTR-3B"}
REAL = {
    "llm_provider": "vercel",
    "ai_gateway_api_key": "test-key-not-a-secret",
    # The discard port on this machine: nothing there answers a call that slipped through.
    "ai_gateway_base_url": "http://127.0.0.1:9/v1",
}


@pytest.fixture
def no_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails the test the moment the real provider is asked for anything."""

    def refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("the Vercel provider was called")

    monkeypatch.setattr(VercelGatewayProvider, "complete", refuse)
    monkeypatch.setattr(VercelGatewayProvider, "embed", refuse)


def wiring_of(app: FastAPI) -> GatewayWiring:
    wiring: GatewayWiring = app.state.gateway
    return wiring


def ledger_of(app: FastAPI) -> MemoryLedger:
    ledger = wiring_of(app).ledger
    assert isinstance(ledger, MemoryLedger)
    return ledger


def test_only_global_allows_real_models() -> None:
    assert ResidencyPolicy.GLOBAL.real_models_allowed is True
    assert ResidencyPolicy.INDIA_ONLY.real_models_allowed is False
    assert [policy.value for policy in ResidencyPolicy] == ["global", "india_only"]


class Recorder:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, req: CompletionRequest) -> Any:
        self.calls += 1

    def embed(self, req: EmbeddingRequest) -> Any:
        self.calls += 1


def test_the_blocked_provider_refuses_both_calls_and_never_calls_the_one_it_wraps() -> None:
    wrapped = Recorder()
    blocked = ResidencyBlockedProvider(wrapped, name="vercel")
    completion = CompletionRequest(
        feature="qa", prompt_version="smoke.echo@1", system="", user="hi", model="example/model-a"
    )
    with pytest.raises(ResidencyUnavailableError) as refused:
        blocked.complete(completion)
    assert (refused.value.model, refused.value.provider) == ("example/model-a", "vercel")
    assert refused.value.detail == (
        "CW_LLM_RESIDENCY=india_only keeps text in India, and 'example/model-a' on 'vercel' runs "
        "outside it: no routed model runs inference in India"
    )
    with pytest.raises(ResidencyUnavailableError, match="'example/model-b' on 'vercel'"):
        blocked.embed(
            EmbeddingRequest(feature="retrieval", inputs=("hi",), model="example/model-b")
        )
    assert wrapped.calls == 0
    assert blocked.provider is wrapped


def test_india_only_wires_the_real_provider_behind_the_guard(make_app: AppFactory) -> None:
    wiring = wiring_of(make_app(llm_residency="india_only", **REAL))
    assert wiring.residency is ResidencyPolicy.INDIA_ONLY
    blocked = wiring.providers["vercel"]
    assert isinstance(blocked, ResidencyBlockedProvider)
    assert isinstance(blocked.provider, VercelGatewayProvider)
    assert wiring.embedders["vercel"] is blocked
    assert isinstance(wiring.providers["fake"], FakeProvider)
    assert wiring.embedders["fake"] is wiring.providers["fake"]


def test_global_wires_the_real_provider_as_it_is(make_app: AppFactory) -> None:
    wiring = wiring_of(make_app(**REAL))
    assert wiring.residency is ResidencyPolicy.GLOBAL
    assert isinstance(wiring.providers["vercel"], VercelGatewayProvider)
    assert wiring.embedders["vercel"] is wiring.providers["vercel"]


@pytest.mark.usefixtures("no_model_call")
def test_india_only_refuses_a_real_completion_with_a_503_before_any_call(
    make_app: AppFactory,
) -> None:
    app = make_app(llm_residency="india_only", **REAL)
    primary = DEFAULT_ROUTES[Feature.QA].primary
    with TestClient(app) as client:
        answers = [client.post(COMPLETIONS, json=QA) for _ in range(5)]
    for response in answers:
        assert response.status_code == 503
        assert "retry-after" not in response.headers
        problem = response.json()
        assert problem["type"] == PROBLEM
        assert problem["title"] == "LLM unavailable under the residency policy"
        assert f"{primary!r} on 'vercel'" in problem["detail"]
    entries = ledger_of(app).entries()
    assert len(entries) == 5, "one row per refusal: the fallback model was never tried"
    for entry in entries:
        assert entry.status is CallStatus.ERROR
        assert entry.error_type == "llm-residency-unavailable"
        assert (entry.model_served, entry.provider) == (primary, "vercel")
        assert entry.cost_inr == Decimal(0)


@pytest.mark.usefixtures("no_model_call")
def test_india_only_refuses_a_real_embedding_with_a_503(make_app: AppFactory) -> None:
    app = make_app(llm_residency="india_only", **REAL)
    with TestClient(app) as client:
        response = client.post(EMBEDDINGS, json={"feature": "retrieval", "inputs": ["Section 7."]})
    assert response.status_code == 503
    assert response.json()["type"] == PROBLEM
    [entry] = ledger_of(app).entries()
    assert entry.error_type == "llm-residency-unavailable"
    assert entry.model_served == DEFAULT_ROUTES[Feature.RETRIEVAL].primary


@pytest.mark.usefixtures("no_model_call")
def test_a_fake_model_still_answers_under_india_only(make_app: AppFactory) -> None:
    app = make_app(llm_residency="india_only", **REAL)
    with TestClient(app) as client:
        smoke = client.post(COMPLETIONS, json={**QA, "feature": "smoke"})
        named = client.post(COMPLETIONS, json={**QA, "model": "fake/echo"})
    for response in (smoke, named):
        assert response.status_code == 200
        assert response.json()["provider"] == "fake"
        assert response.json()["model_served"] == "fake/echo"


def test_india_only_with_the_fake_provider_answers_every_route(make_app: AppFactory) -> None:
    app = make_app(llm_residency="india_only")
    with TestClient(app) as client:
        completion = client.post(COMPLETIONS, json=QA)
        embedding = client.post(EMBEDDINGS, json={"feature": "retrieval", "inputs": ["Section 7."]})
    assert completion.status_code == 200
    assert completion.json()["provider"] == "fake"
    assert embedding.status_code == 200
    assert embedding.json()["model_served"] == "fake/hash-ngram-512"


@pytest.mark.parametrize(
    ("overrides", "residency"),
    [
        ({}, {"policy": "global", "real_models_allowed": True}),
        ({"llm_residency": "india_only"}, {"policy": "india_only", "real_models_allowed": False}),
        (
            {"llm_residency": "india_only", **REAL},
            {"policy": "india_only", "real_models_allowed": False},
        ),
    ],
)
def test_models_reports_the_policy_on_every_route(
    make_app: AppFactory, overrides: dict[str, Any], residency: dict[str, Any]
) -> None:
    with TestClient(make_app(**overrides)) as client:
        routes = client.get(MODELS).json()
    assert [route["feature"] for route in routes] == [feature.value for feature in Feature]
    assert all(route["residency"] == residency for route in routes)
