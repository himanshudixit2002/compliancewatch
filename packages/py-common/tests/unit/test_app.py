import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from py_common.app import create_app
from py_common.request_context import REQUEST_ID_HEADER, correlation_id_of


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
