"""GET /models, GET /prompts, readiness, and what wiring does with settings."""

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_gateway.domain.errors import UnknownFeatureError
from llm_gateway.domain.features import Feature
from llm_gateway.domain.routing import DEFAULT_ROUTES
from llm_gateway.infrastructure.ledger.memory import MemoryLedger
from llm_gateway.wiring import GatewayWiring

AppFactory = Callable[..., FastAPI]

MODELS = "/v1/llm-gateway/models"
PROMPTS = "/v1/llm-gateway/prompts"
COMPLETIONS = "/v1/llm-gateway/completions"


def test_models_lists_every_feature_in_order(client: TestClient) -> None:
    response = client.get(MODELS)
    assert response.status_code == 200
    routes = response.json()
    assert [route["feature"] for route in routes] == [feature.value for feature in Feature]
    assert all(route["source"] == "default" for route in routes)
    for route in routes:
        default = DEFAULT_ROUTES[Feature(route["feature"])]
        assert route["primary"] == default.primary
        assert route["fallback"] == default.fallback
        assert route["timeout_seconds"] == default.timeout_seconds


def test_extraction_route_carries_the_gateway_filters(client: TestClient) -> None:
    extraction = client.get(MODELS).json()[0]
    assert extraction == {
        "feature": "extraction",
        "primary": "deepseek/deepseek-v4-pro-0813",
        "fallback": "zai/glm-5.3",
        "only": ["deepinfra", "parasail", "digitalocean", "morph", "togetherai"],
        "has": ["structured-output"],
        "sort": None,
        "reasoning_effort": "none",
        "timeout_seconds": 120.0,
        "source": "default",
    }


def test_smoke_route_is_the_fake_without_a_fallback(client: TestClient) -> None:
    [smoke] = [route for route in client.get(MODELS).json() if route["feature"] == "smoke"]
    assert smoke == {
        "feature": "smoke",
        "primary": "fake/echo",
        "fallback": None,
        "only": [],
        "has": [],
        "sort": None,
        "reasoning_effort": None,
        "timeout_seconds": 5.0,
        "source": "default",
    }


def test_route_override_is_applied_and_keeps_the_filters(make_app: AppFactory) -> None:
    app = make_app(llm_routes={"qa": "fake/echo", "judgement": "fake/echo,fake/other"})
    with TestClient(app) as client:
        routes = {route["feature"]: route for route in client.get(MODELS).json()}
    assert routes["qa"]["primary"] == "fake/echo"
    assert routes["qa"]["fallback"] is None
    assert routes["qa"]["source"] == "override"
    assert routes["qa"]["only"] == list(DEFAULT_ROUTES[Feature.QA].only)
    assert routes["qa"]["sort"] == "ttft"
    assert routes["judgement"]["primary"] == "fake/echo"
    assert routes["judgement"]["fallback"] == "fake/other"
    assert routes["judgement"]["source"] == "override"
    assert routes["extraction"]["source"] == "default"


def test_overridden_route_is_what_completions_use(make_app: AppFactory) -> None:
    app = make_app(llm_routes={"qa": "fake/answer"})
    with TestClient(app) as client:
        response = client.post(
            COMPLETIONS, json={"feature": "qa", "prompt": "smoke.echo@1", "user": "why?"}
        )
    assert response.status_code == 200
    assert response.json()["model_served"] == "fake/answer"
    assert response.json()["provider"] == "fake"


def test_unknown_feature_override_fails_at_startup(make_app: AppFactory) -> None:
    with pytest.raises(UnknownFeatureError, match="billing"):
        make_app(llm_routes={"billing": "fake/echo"})


def test_prompts_lists_the_registry_in_file_order(client: TestClient) -> None:
    response = client.get(PROMPTS)
    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "smoke.echo",
            "version": "1",
            "owner": "ai-platform",
            "eval_cases": 1,
            "sha256": None,
            "description": (
                "Deterministic echo served by the fake provider; used by tests and the smoke route."
            ),
        },
        {
            "name": "extraction.rule_candidate",
            "version": "1",
            "owner": "regulatory-intelligence",
            "eval_cases": 1,
            "sha256": "8c31ce19b6225847eb097ed785869bdb68e3208c8c006cc3f3c858d3565d75ce",
            "description": (
                "Rule candidate from one parsed document; text in "
                "services/pipeline/prompts/extraction.rule_candidate.v1.md, "
                "cases in evals/golden/extraction."
            ),
        },
        {
            "name": "extraction.rule_relations",
            "version": "1",
            "owner": "regulatory-intelligence",
            "eval_cases": 1,
            "sha256": "97c4b62619480a6e70e28234a120a2c04ecaf5bd6e2e20cdd7869e7d914f20e7",
            "description": (
                "Typed relations from one parsed document to the targets its mention grammar "
                "found; text in services/pipeline/prompts/extraction.rule_relations.v1.md, "
                "cases in evals/golden/relations."
            ),
        },
        {
            "name": "qa.plan",
            "version": "1",
            "owner": "ai-platform",
            "eval_cases": 53,
            "sha256": "cede3e9618ba5e2b379bd8cc8753ee9ffc969634cf7ec7fff85b71aa171897bd",
            "description": (
                "Plan of typed steps for one question, never an answer; text in "
                "services/qa/prompts/qa.plan.v1.md, cases in evals/golden/qa/kag."
            ),
        },
        {
            "name": "qa.answer",
            "version": "1",
            "owner": "ai-platform",
            "eval_cases": 53,
            "sha256": "f95588192eae2ef696919742bbbb5fd01524c51a2fed90ec2b2d86a1e1c82a68",
            "description": (
                "Answer from a labelled evidence bundle with verbatim quotes, or not covered; "
                "text in services/qa/prompts/qa.answer.v1.md, cases in evals/golden/qa/kag."
            ),
        },
    ]


def test_ready_names_the_checks(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"ledger": True, "prompt_registry": True, "provider": True}


def test_fake_provider_serves_both_provider_names(wiring: GatewayWiring) -> None:
    assert set(wiring.providers) == {"fake", "vercel"}
    assert wiring.providers["fake"] is wiring.providers["vercel"]
    assert isinstance(wiring.ledger, MemoryLedger)
    assert wiring.settings.llm_provider == "fake"


def test_a_zero_ttl_turns_the_cache_off(make_app: AppFactory) -> None:
    app = make_app(llm_cache_ttl_seconds=0)
    body = {"feature": "smoke", "prompt": "smoke.echo@1", "user": "hello"}
    with TestClient(app) as client:
        first = client.post(COMPLETIONS, json=body).json()
        second = client.post(COMPLETIONS, json=body).json()
    assert first["cached"] is False
    assert second["cached"] is False
    wiring: GatewayWiring = app.state.gateway
    assert isinstance(wiring.ledger, MemoryLedger)
    assert len(wiring.ledger.entries()) == 2


def test_lifespan_close_is_safe(make_app: AppFactory) -> None:
    app = make_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    wiring: GatewayWiring = app.state.gateway
    wiring.close()
