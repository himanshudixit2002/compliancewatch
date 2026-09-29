"""The gateway routes in header, dual and token mode: model calls need a service with llm:call,
usage and the registries also take a regulatory role, and a tenant named in the header needs
tenant:act."""

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.ids import TenantId
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ISSUER = TestIssuer()
COMPLETIONS = "/v1/llm-gateway/completions"
EMBEDDINGS = "/v1/llm-gateway/embeddings"
USAGE = "/v1/llm-gateway/usage"
MODELS = "/v1/llm-gateway/models"
PROMPTS = "/v1/llm-gateway/prompts"
TENANT = TenantId.new()
INTERNAL = TenantId.new()
AS_TENANT = {"x-tenant-id": str(TENANT)}
QA = bearer(ISSUER.service("qa", [Scope.LLM_CALL, Scope.TENANT_ACT]))
PIPELINE = bearer(ISSUER.service("pipeline", [Scope.LLM_CALL]))
BOT = bearer(ISSUER.service("whatsapp-bot", [Scope.TENANT_ACT]))
OWNER = bearer(ISSUER.user(TENANT, [Role.OWNER]))
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True))
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True))


def client_in(make_app: Callable[..., FastAPI], mode: AuthMode) -> Iterator[TestClient]:
    with TestClient(make_app(**ISSUER.settings_overrides(mode))) as client:
        yield client


@pytest.fixture
def header_mode(make_app: Callable[..., FastAPI]) -> Iterator[TestClient]:
    yield from client_in(make_app, "header")


@pytest.fixture
def dual_mode(make_app: Callable[..., FastAPI]) -> Iterator[TestClient]:
    yield from client_in(make_app, "dual")


@pytest.fixture
def token_mode(make_app: Callable[..., FastAPI]) -> Iterator[TestClient]:
    yield from client_in(make_app, "token")


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def complete(client: TestClient, headers: dict[str, str], text: str = "hello") -> Any:
    body = {"feature": "smoke", "prompt": "smoke.echo@1", "user": text * 40}
    return client.post(COMPLETIONS, json=body, headers=headers)


def embed(client: TestClient, headers: dict[str, str]) -> Any:
    body = {"feature": "retrieval", "inputs": ["Section 7. Returns are monthly."]}
    return client.post(EMBEDDINGS, json=body, headers=headers)


# ---------------------------------------------------------------- header mode


def test_header_mode_serves_every_route_as_before(header_mode: TestClient) -> None:
    assert complete(header_mode, {}).status_code == 200
    assert complete(header_mode, {**AS_TENANT, **OWNER}).status_code == 200
    assert embed(header_mode, BOT).status_code == 200
    assert header_mode.get(USAGE, headers=AS_TENANT).status_code == 200
    assert header_mode.get(MODELS, headers=OWNER).status_code == 200
    assert header_mode.get(PROMPTS).status_code == 200


# ---------------------------------------------------------------- dual mode


def test_dual_mode_needs_llm_call_from_a_bearer(dual_mode: TestClient) -> None:
    assert complete(dual_mode, AS_TENANT).status_code == 200
    assert complete(dual_mode, PIPELINE).status_code == 200
    assert complete(dual_mode, {**QA, **AS_TENANT}).status_code == 200
    for caller in (OWNER, BOT):
        refused = complete(dual_mode, caller)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    bad = complete(dual_mode, bearer("not-a-token"))
    assert (bad.status_code, problem(bad)) == (401, "auth-token-invalid")


def test_dual_mode_names_a_tenant_only_with_tenant_act(dual_mode: TestClient) -> None:
    refused = complete(dual_mode, {**PIPELINE, **AS_TENANT})
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    refused = embed(dual_mode, {**PIPELINE, **AS_TENANT})
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    assert embed(dual_mode, PIPELINE).status_code == 200


# ---------------------------------------------------------------- token mode


def test_token_mode_needs_a_bearer_on_every_route(token_mode: TestClient) -> None:
    for response in (
        complete(token_mode, AS_TENANT),
        embed(token_mode, {}),
        token_mode.get(USAGE, headers=AS_TENANT),
        token_mode.get(MODELS),
        token_mode.get(PROMPTS),
    ):
        assert (response.status_code, problem(response)) == (401, "auth-token-required")
        assert response.headers["www-authenticate"] == "Bearer"
    assert token_mode.get("/v1/llm-gateway/ping").status_code == 200


def test_token_mode_attributes_a_service_call_to_the_tenant_it_names(
    token_mode: TestClient,
) -> None:
    called = complete(token_mode, {**QA, **AS_TENANT})
    assert called.status_code == 200, called.text
    spent = token_mode.get(USAGE, params={"tenant_id": str(TENANT)}, headers=ADMIN)
    assert spent.status_code == 200, spent.text
    assert Decimal(spent.json()["spent_inr"]) == Decimal(called.json()["cost_inr"]) > 0
    by_header = token_mode.get(USAGE, headers={**QA, **AS_TENANT})
    assert by_header.json()["key"] == str(TENANT)
    assert embed(token_mode, PIPELINE).status_code == 200


def test_token_mode_lets_an_operator_read_usage_and_the_registries(
    token_mode: TestClient,
) -> None:
    for caller in (ADMIN, ANALYST, PIPELINE):
        assert token_mode.get(MODELS, headers=caller).status_code == 200
        assert token_mode.get(PROMPTS, headers=caller).status_code == 200
    by_feature = token_mode.get(USAGE, params={"feature": "smoke"}, headers=ADMIN)
    assert by_feature.json()["scope"] == "feature", "an operator's own tenant is no default"
    refused = complete(token_mode, ADMIN)
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")


def test_token_mode_keeps_a_tenant_user_away_from_any_spend(token_mode: TestClient) -> None:
    assert complete(token_mode, {**QA, **AS_TENANT}).status_code == 200
    other = str(uuid4())
    for params in ({"tenant_id": other}, {"tenant_id": str(TENANT)}, {"feature": "smoke"}):
        refused = token_mode.get(USAGE, params=params, headers=OWNER)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    for path in (MODELS, PROMPTS):
        refused = token_mode.get(path, headers=OWNER)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    mismatch = token_mode.get(USAGE, headers={**ADMIN, **AS_TENANT})
    assert (mismatch.status_code, problem(mismatch)) == (403, "auth-tenant-mismatch")
