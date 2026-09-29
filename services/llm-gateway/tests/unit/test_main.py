"""The composition root: what ``build_app`` logs once the app exists, and its provider seam."""

import json
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.llm import CompletionRequest, CompletionResponse
from llm_gateway.domain.features import Feature
from llm_gateway.domain.routing import DEFAULT_ROUTES
from llm_gateway.infrastructure.ledger.memory import MemoryLedger
from llm_gateway.wiring import GatewayWiring

AppFactory = Callable[..., FastAPI]
SCRIPTED = '{"answer":"scripted"}'


def test_gateway_wired_is_logged_as_json_with_the_service_field(
    make_app: AppFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    make_app(log_json=True, log_level="INFO")
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if "gateway_wired" in line
    ]
    [line] = lines
    assert line["event"] == "gateway_wired"
    assert line["service"] == "llm-gateway"
    assert line["level"] == "info"
    assert (line["provider"], line["ledger"], line["cache"], line["langfuse"]) == (
        "fake",
        "memory",
        True,
        False,
    )
    assert (line["prompts"], line["routes"], line["providers"]) == (5, 6, 2)


def test_gateway_wired_reports_a_disabled_cache(
    make_app: AppFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    make_app(log_json=True, log_level="INFO", llm_cache_ttl_seconds=0)
    [line] = [json.loads(s) for s in capsys.readouterr().out.splitlines() if "gateway_wired" in s]
    assert line["cache"] is False


class Scripted:
    """Answers every completion with the same text, as the eval harness's scripted provider does."""

    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        self.requests.append(req)
        return CompletionResponse(SCRIPTED, req.model or "scripted/model", 3, 4)


def test_a_completion_provider_serves_every_completion_route_but_not_embeddings(
    make_app: AppFactory,
) -> None:
    scripted = Scripted()
    app = make_app(completion_provider=scripted)
    calls = [("smoke", "smoke.echo@1"), ("extraction", "extraction.rule_candidate@1")]
    with TestClient(app) as client:
        for feature, prompt in calls:
            body = {"feature": feature, "prompt": prompt, "user": "Section 7."}
            response = client.post("/v1/llm-gateway/completions", json=body)
            assert response.status_code == 200
            assert response.json()["text"] == SCRIPTED
        embedded = client.post(
            "/v1/llm-gateway/embeddings", json={"feature": "retrieval", "inputs": ["Section 7."]}
        )
    assert embedded.status_code == 200
    assert embedded.json()["model_served"] == "fake/hash-ngram-512"
    assert [req.model for req in scripted.requests] == [
        "fake/echo",
        DEFAULT_ROUTES[Feature.EXTRACTION].primary,
    ]
    wiring: GatewayWiring = app.state.gateway
    assert set(wiring.providers) == {"fake", "vercel"}
    assert all(provider is scripted for provider in wiring.providers.values())
    assert isinstance(wiring.ledger, MemoryLedger)
    assert [row.feature for row in wiring.ledger.entries()] == [
        Feature.SMOKE,
        Feature.EXTRACTION,
        Feature.RETRIEVAL,
    ]
