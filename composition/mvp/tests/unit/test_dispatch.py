"""Who serves a request: the facade table, the first segment, the listener and the limit."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi import APIRouter, FastAPI
from starlette.types import Receive, Scope, Send

from cw_mvp.app import CombinedApp
from cw_mvp.dispatch import RouteTable, ServiceDispatcher, served_routes
from cw_mvp.exposure import ADMIN, PUBLIC

PUBLIC_SPEC = Path(__file__).resolve().parents[4] / "packages/contracts/openapi/public.v1.json"
PUBLIC_URL = "http://public:8000"
INTERNAL_URL = "http://internal:8080"


def _spec_owners() -> dict[str, str]:
    spec = json.loads(PUBLIC_SPEC.read_text("utf-8"))
    owners: dict[str, str] = {}
    for path, item in spec["paths"].items():
        for operation in item.values():
            if isinstance(operation, dict):
                owners[path] = operation["x-service"]
    return owners


def test_the_facade_table_is_the_x_service_map_of_the_public_api(memory_app: CombinedApp) -> None:
    table = memory_app.dispatcher.table
    assert table.facade() == _spec_owners()
    for path, service in _spec_owners().items():
        concrete = path.replace("{business_id}", "0b4f0a3e-6f0a-4b8e-9a51-2f7c0e1d3a55")
        assert table.owner(concrete) == service


def test_a_path_belongs_to_its_first_segment_outside_the_facade(memory_app: CombinedApp) -> None:
    table = memory_app.dispatcher.table
    assert table.owner("/v1/llm-gateway/ping") == "llm-gateway"
    assert table.owner("/v1/profile/nodes/x/snapshot") == "profile"
    assert table.owner("/v1/nowhere/ping") is None
    assert table.owner("/health") is None


def _app(*paths: str, methods: tuple[str, ...] = ("GET",)) -> FastAPI:
    app = FastAPI()
    router = APIRouter()
    for path in paths:

        async def endpoint() -> dict[str, str]:
            return {"ok": "yes"}

        router.add_api_route(path, endpoint, methods=list(methods))
    app.include_router(router)
    return app


def test_facade_paths_match_longest_template_first() -> None:
    apps = {
        "rulebook": _app("/v1/rulebook/ping", "/v1/changes", "/v1/changes/{change_id}"),
        "applicability-engine": _app("/v1/changes/{change_id}/impact"),
    }
    table = RouteTable.of(
        apps,
        {"rulebook": "/v1/rulebook", "applicability-engine": "/v1/applicability-engine"},
        exposure={},
        loopback={},
    )
    assert list(table.facade()) == [
        "/v1/changes/{change_id}/impact",
        "/v1/changes/{change_id}",
        "/v1/changes",
    ]
    assert table.owner("/v1/changes/42/impact") == "applicability-engine"
    assert table.owner("/v1/changes/42") == "rulebook"
    assert table.owner("/v1/changes") == "rulebook"


def test_a_route_is_the_first_of_its_service_by_method_and_path() -> None:
    apps = {"rulebook": _app("/v1/rulebook/entities/resolve", "/v1/rulebook/entities/{id}")}
    table = RouteTable.of(
        apps,
        {"rulebook": "/v1/rulebook"},
        exposure={"rulebook": {"GET /v1/rulebook/entities/resolve": PUBLIC}},
        loopback={"rulebook": ["GET /v1/rulebook/entities/{id}"]},
    )
    resolve = table.route("rulebook", "HEAD", "/v1/rulebook/entities/resolve")
    assert resolve is not None
    assert resolve.key == "GET /v1/rulebook/entities/resolve"
    assert resolve.exposure is PUBLIC
    assert not resolve.loopback
    other = table.route("rulebook", "GET", "/v1/rulebook/entities/42")
    assert other is not None
    assert other.exposure is None
    assert other.loopback
    assert table.route("rulebook", "POST", "/v1/rulebook/entities/42") is None
    assert table.route("nowhere", "GET", "/v1/rulebook/entities/42") is None
    assert len(table.entries()) == 2


def test_served_routes_skip_docs_probes_and_head() -> None:
    app = _app("/v1/x/ping", "/health", methods=("GET", "HEAD"))
    assert list(served_routes(app)) == [("GET", "/v1/x/ping")]


class Gauge:
    """A service app that counts the requests it is serving at once and holds them until
    ``release`` is set."""

    def __init__(self, reach: int = 1) -> None:
        self.current = 0
        self.most = 0
        self.reach = reach
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.current += 1
        self.most = max(self.most, self.current)
        if self.current >= self.reach:
            self.reached.set()
        await self.release.wait()
        self.current -= 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def _dispatcher(service: Any, *, limit: int, mode: str = "header") -> ServiceDispatcher:
    routes = _app("/v1/qa/ask", "/v1/qa/admin", methods=("POST",))
    table = RouteTable.of(
        {"qa": routes},
        {"qa": "/v1/qa"},
        exposure={"qa": {"POST /v1/qa/ask": PUBLIC, "POST /v1/qa/admin": ADMIN}},
        loopback={"qa": ["POST /v1/qa/ask"]},
    )
    return ServiceDispatcher(
        _app("/health"),
        {"qa": service},
        table,
        internal_port=8080,
        auth_mode=mode,  # type: ignore[arg-type]
        loopback_limit=limit,
    )


async def test_routes_that_call_other_services_run_at_most_limit_at_once() -> None:
    gauge = Gauge(reach=3)
    dispatcher = _dispatcher(gauge, limit=3)
    transport = httpx2.ASGITransport(app=dispatcher)
    async with httpx2.AsyncClient(transport=transport, base_url=PUBLIC_URL) as client:
        requests = [asyncio.create_task(client.post("/v1/qa/ask")) for _ in range(10)]
        await asyncio.wait_for(gauge.reached.wait(), timeout=5)
        # Give the other seven every chance to get in before looking.
        await asyncio.sleep(0.05)
        assert gauge.current == 3
        gauge.release.set()
        responses = await asyncio.gather(*requests)
    assert [response.status_code for response in responses] == [204] * 10
    assert gauge.most == 3


async def test_admin_routes_reach_the_public_listener_only_in_token_mode() -> None:
    gauge = Gauge()
    gauge.release.set()
    for mode, status in (("header", 404), ("dual", 404), ("token", 204)):
        transport = httpx2.ASGITransport(app=_dispatcher(gauge, limit=1, mode=mode))
        async with httpx2.AsyncClient(transport=transport, base_url=PUBLIC_URL) as client:
            assert (await client.post("/v1/qa/admin")).status_code == status
            assert (await client.post(INTERNAL_URL + "/v1/qa/admin")).status_code == 204


async def test_a_request_without_a_server_is_on_the_public_listener() -> None:
    dispatcher = _dispatcher(Gauge(), limit=1)
    assert not dispatcher.is_internal({"type": "http"})
    assert not dispatcher.is_internal({"type": "http", "server": ("public", None)})
    assert dispatcher.is_internal({"type": "http", "server": ("internal", 8080)})


def test_the_limit_is_at_least_one() -> None:
    with pytest.raises(ValueError, match="loopback_limit"):
        _dispatcher(Gauge(), limit=0)
