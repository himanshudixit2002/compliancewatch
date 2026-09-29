import sys
import types

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient

from py_common.app import create_app, module_app
from py_common.request_context import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    correlation_id_of,
)


def test_request_id_is_minted_when_absent() -> None:
    app = create_app(service_name="t", version="0")
    with TestClient(app) as client:
        response = client.get("/health")
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


@pytest.mark.parametrize("offered", ["req-123", "a" * 64, "trace.01_x-Y", "7"])
def test_a_well_formed_request_id_is_echoed(offered: str) -> None:
    app = create_app(service_name="t", version="0")
    with TestClient(app) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: offered})
    assert response.headers[REQUEST_ID_HEADER] == offered


@pytest.mark.parametrize("offered", ["r" * 70, "has spaces", "slash/id", "semi;colon", ""])
def test_an_unusable_request_id_is_replaced_with_a_minted_one(offered: str) -> None:
    router = APIRouter()

    @router.get("/whoami")
    async def whoami(request: Request) -> dict[str, str | None]:
        return {"correlation_id": correlation_id_of(request)}

    app = create_app(service_name="t", version="0", routers=[router])
    with TestClient(app) as client:
        response = client.get("/whoami", headers={REQUEST_ID_HEADER: offered})
    minted = response.headers[REQUEST_ID_HEADER]
    assert minted != offered
    assert len(minted) == 32
    int(minted, 16)
    assert response.json() == {"correlation_id": minted}


def test_custom_routers_are_mounted() -> None:
    router = APIRouter(prefix="/v1/demo")

    @router.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "pong"}

    app = create_app(service_name="t", version="0", routers=[router])
    with TestClient(app) as client:
        assert client.get("/v1/demo/ping").json() == {"status": "pong"}


def test_an_outer_correlation_id_is_reused_and_the_header_sent_once() -> None:
    router = APIRouter()

    @router.get("/whoami")
    async def whoami(request: Request) -> dict[str, str | None]:
        return {"correlation_id": correlation_id_of(request)}

    inner = create_app(service_name="t", version="0", routers=[router])
    outer = RequestContextMiddleware(inner)
    with TestClient(outer) as client:
        response = client.get("/whoami", headers={REQUEST_ID_HEADER: "outer-42"})
        minted = client.get("/whoami")
    assert response.headers.get_list(REQUEST_ID_HEADER) == ["outer-42"]
    assert response.json() == {"correlation_id": "outer-42"}
    (only,) = minted.headers.get_list(REQUEST_ID_HEADER)
    assert minted.json() == {"correlation_id": only}


def test_the_readiness_checks_are_kept_on_the_app() -> None:
    async def store() -> bool:
        return True

    app = create_app(service_name="t", version="0", readiness_checks=[("store", store)])
    assert app.state.readiness_checks == (("store", store),)
    assert create_app(service_name="t", version="0").state.readiness_checks == ()


def test_module_app_builds_the_app_once_on_first_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = types.ModuleType("cw_lazy_main")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    built: list[FastAPI] = []

    def build_app() -> FastAPI:
        app = create_app(service_name="lazy", version="0")
        built.append(app)
        return app

    build_app.__module__ = module.__name__

    def module_getattr(name: str) -> FastAPI:
        return module_app(name, build_app)

    module.__getattr__ = module_getattr  # type: ignore[method-assign]
    assert built == [], "importing the module builds nothing"
    first = module.app
    assert module.app is first
    assert built == [first]
    assert vars(module)["app"] is first
    with pytest.raises(AttributeError, match="has no attribute 'other'"):
        _ = module.other
    assert not hasattr(module, "application")
