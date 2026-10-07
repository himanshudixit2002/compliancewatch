"""The combined app on memory stores and the fake model: probes, listeners, lifespans, logs and
the tokens the services share."""

import json
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from cw_mvp.app import CombinedApp, build_app, in_process_tokens, raise_thread_limit
from cw_mvp.registry import REGISTRY, ServiceEntry
from cw_mvp.testing import MEMORY_SERVICES, mvp_settings
from domain_kernel.access import Principal, Scope
from llm_gateway.infrastructure.tracing.log import LogTracer
from py_common.auth import IssuerTokenSource

INTERNAL = "http://internal:8080"
PUBLIC = "http://public:8000"
PROBLEM = "application/problem+json"
ROUTE_NOT_FOUND = "urn:compliancewatch:problem:route-not-found"
TENANT = {"x-tenant-id": "7d7b0f0e-2f7e-4a55-8c0e-1f9b8c1d2e3f"}
VERSION_ID = "3f1d9a52-1b7e-4a4c-9d8e-6c2b1a0f9e8d"


@pytest.fixture
def client(memory_app: CombinedApp) -> Iterator[TestClient]:
    with TestClient(memory_app, base_url=INTERNAL) as client:
        yield client


def _route_not_found(response: httpx2.Response) -> bool:
    return bool(
        response.status_code == 404
        and response.headers["content-type"] == PROBLEM
        and response.json()["type"] == ROUTE_NOT_FOUND
    )


def test_health_is_the_process_s(client: TestClient) -> None:
    for base in (INTERNAL, PUBLIC):
        response = client.get(base + "/health")
        assert response.status_code == 200
        assert response.json()["service"] == "compliancewatch-api"


def test_ready_lists_every_service_s_checks(client: TestClient, memory_app: CombinedApp) -> None:
    response = client.get(PUBLIC + "/ready")
    assert response.status_code == 200
    expected = {
        f"{service}.{name}"
        for service, app in memory_app.services.items()
        for name, _ in app.state.readiness_checks
    }
    assert set(response.json()["checks"]) == expected
    assert {"identity.store", "qa.prompts", "llm-gateway.provider"} <= expected


def test_every_service_answers_its_ping_on_the_internal_listener(client: TestClient) -> None:
    for entry in REGISTRY:
        response = client.get(f"/v1/{entry.name}/ping")
        assert response.status_code == 200, entry.name
        assert response.json()["service"] == entry.name


def test_the_public_listener_serves_only_public_routes(client: TestClient) -> None:
    denied = [
        ("GET", "/v1/llm-gateway/ping"),
        ("GET", "/v1/pipeline/ping"),
        ("POST", "/v1/identity/service-tokens"),
        ("POST", "/v1/notification/send"),
        ("POST", f"/v1/rulebook/rule-versions/{VERSION_ID}/publish"),
        ("POST", "/v1/rulebook/review/entities/decisions"),
        ("GET", "/v1/rulebook/review/entities"),
        ("GET", "/v1/rulebook/clauses/unembedded"),
        ("DELETE", "/v1/rulebook/rule-versions"),
        ("GET", "/v1/nowhere/ping"),
        ("GET", "/docs"),
        ("GET", "/openapi.json"),
    ]
    for method, path in denied:
        assert _route_not_found(client.request(method, PUBLIC + path)), (method, path)
    served = [
        ("GET", f"/v1/rulebook/rule-versions/{VERSION_ID}"),
        ("GET", "/v1/rulebook/relations"),
        ("POST", "/v1/rulebook/search"),
        ("GET", "/v1/businesses"),
        ("GET", "/v1/qa/ping"),
    ]
    for method, path in served:
        response = client.request(method, PUBLIC + path, headers=TENANT, json={})
        assert not _route_not_found(response), (method, path)


def test_the_internal_listener_serves_every_route_and_the_root_s_docs(client: TestClient) -> None:
    assert client.get("/v1/llm-gateway/ping").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    unknown = client.get("/v1/nowhere/ping")
    assert _route_not_found(unknown)
    publish = client.post(f"/v1/rulebook/rule-versions/{VERSION_ID}/publish", json={})
    assert not _route_not_found(publish)


def test_one_request_id_crosses_the_process(client: TestClient) -> None:
    fresh = client.get(PUBLIC + "/v1/qa/ping")
    assert len(fresh.headers.get_list("x-request-id")) == 1
    kept = client.get("/v1/profile/ping", headers={"x-request-id": "outer-id-1"})
    assert kept.headers.get_list("x-request-id") == ["outer-id-1"]
    denied = client.get(PUBLIC + "/v1/eval/ping", headers={"x-request-id": "outer-id-2"})
    assert denied.headers.get_list("x-request-id") == ["outer-id-2"]
    assert denied.json()["correlation_id"] == "outer-id-2"


def test_each_service_s_lifespan_is_entered_and_left_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushes: list[str] = []
    monkeypatch.setattr(LogTracer, "flush", lambda self: flushes.append("flush"))
    app = build_app(mvp_settings(log_level="WARNING"), service_overrides=MEMORY_SERVICES)
    events: Counter[str] = Counter()
    for name, service in app.services.items():
        service.router.lifespan_context = _counting(service.router.lifespan_context, name, events)
    with TestClient(app, base_url=INTERNAL) as client:
        assert client.get("/health").status_code == 200
        assert flushes == []
        assert all(events[f"enter {entry.name}"] == 1 for entry in REGISTRY)
    assert flushes == ["flush"]
    assert all(events[f"exit {entry.name}"] == 1 for entry in REGISTRY)


def _counting(
    lifespan: Callable[[Any], Any], name: str, events: Counter[str]
) -> Callable[[FastAPI], Any]:
    @asynccontextmanager
    async def counted(app: FastAPI) -> AsyncIterator[None]:
        events[f"enter {name}"] += 1
        async with lifespan(app):
            yield
        events[f"exit {name}"] += 1

    return counted


def test_log_lines_carry_the_service_that_handled_the_request(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = build_app(mvp_settings(log_level="INFO"), service_overrides=MEMORY_SERVICES)
    capsys.readouterr()
    with TestClient(app, base_url=INTERNAL) as client:
        response = client.post(
            "/v1/llm-gateway/embeddings",
            headers=TENANT,
            json={"feature": "retrieval", "inputs": ["when is GSTR-3B due"]},
        )
    assert response.status_code == 200
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line[:1] == "{"]
    calls = [line for line in lines if line["event"] == "llm.call.completed"]
    assert calls
    assert {line["service"] for line in calls} == {"llm-gateway"}
    started = [line for line in lines if line["event"] == "Application startup complete."]
    assert all(line["service"] == "compliancewatch-api" for line in started)


def _spying(
    registry: tuple[ServiceEntry[Any], ...], seen: dict[str, dict[str, Any]]
) -> tuple[ServiceEntry[Any], ...]:
    def spy(entry: ServiceEntry[Any]) -> Callable[..., FastAPI]:
        def build(settings: Any, **arguments: Any) -> FastAPI:
            seen[entry.name] = arguments
            return entry.build(settings, **arguments)

        return build

    return tuple(replace(entry, build=spy(entry)) for entry in registry)


def test_in_token_mode_services_share_identity_s_keys_and_mint_tokens_in_process() -> None:
    seen: dict[str, dict[str, Any]] = {}
    app = build_app(
        mvp_settings(log_level="WARNING", auth_mode="token"),
        service_overrides=MEMORY_SERVICES,
        registry=_spying(REGISTRY, seen),
    )
    authenticator = app.services["identity"].state.authenticator
    assert "authenticator" not in seen["identity"]
    for entry in REGISTRY[1:]:
        assert seen[entry.name]["authenticator"] is authenticator
        assert app.services[entry.name].state.authenticator is authenticator
    qa_tokens = seen["qa"]["token_source"]
    assert isinstance(qa_tokens, IssuerTokenSource)
    assert qa_tokens.principal == Principal.service("qa", {Scope.LLM_CALL, Scope.TENANT_ACT})
    notification = seen["notification"]["token_source"].principal
    assert notification == Principal.service(
        "notification", {Scope.TENANT_ACT, Scope.ERASURE_VERIFY}
    )
    engine = seen["applicability-engine"]["token_source"].principal
    assert engine == Principal.service(
        "applicability-engine", {Scope.TENANT_ACT, Scope.ERASURE_VERIFY}
    )
    assert authenticator.principal_for(qa_tokens.token()) == qa_tokens.principal

    node = f"/v1/profile/nodes/{uuid4()}"
    with TestClient(app, base_url=INTERNAL) as client:
        assert client.get(node, headers=TENANT).status_code == 401
        signed = {**TENANT, "authorization": f"Bearer {qa_tokens.token()}"}
        assert client.get(node, headers=signed).status_code == 404
        admin = client.post(PUBLIC + f"/v1/rulebook/rule-versions/{VERSION_ID}/publish", json={})
        assert admin.status_code == 401
        assert not _route_not_found(admin)


def test_in_header_mode_no_tokens_are_minted() -> None:
    seen: dict[str, dict[str, Any]] = {}
    build_app(
        mvp_settings(log_level="WARNING"),
        service_overrides=MEMORY_SERVICES,
        registry=_spying(REGISTRY, seen),
    )
    for caller in ("qa", "notification", "applicability-engine"):
        assert "token_source" not in seen[caller], caller


def test_scopes_come_from_the_setting_when_it_is_given(memory_app: CombinedApp) -> None:
    tokens = in_process_tokens(memory_app.services["identity"], "qa=llm:call")
    assert tokens("qa").client_id == "qa"
    source = tokens("qa")
    assert isinstance(source, IssuerTokenSource)
    assert source.principal.scopes == {Scope.LLM_CALL}
    other = tokens("pipeline")
    assert isinstance(other, IssuerTokenSource)
    assert other.principal.scopes == frozenset()


def test_the_registry_must_start_with_identity() -> None:
    reordered = (*REGISTRY[1:], REGISTRY[0])
    with pytest.raises(ValueError, match="identity must come first"):
        build_app(
            mvp_settings(log_level="WARNING"),
            service_overrides=MEMORY_SERVICES,
            registry=reordered,
        )


def test_overrides_must_name_registered_services() -> None:
    with pytest.raises(KeyError, match="nowhere"):
        build_app(mvp_settings(), service_overrides={"nowhere": {}})
    with pytest.raises(KeyError, match="nowhere"):
        build_app(mvp_settings(), build_overrides={"nowhere": {}})


async def test_the_thread_pool_is_raised_never_lowered() -> None:
    import anyio.to_thread

    limiter = anyio.to_thread.current_default_thread_limiter()
    before = int(limiter.total_tokens)
    try:
        raise_thread_limit(before + 10)
        assert limiter.total_tokens == before + 10
        raise_thread_limit(5)
        assert limiter.total_tokens == before + 10
    finally:
        limiter.total_tokens = before
