from fastapi import APIRouter
from fastapi.testclient import TestClient

from py_common.app import REQUEST_ID_HEADER, create_app


def test_request_id_is_minted_when_absent() -> None:
    app = create_app(service_name="t", version="0")
    with TestClient(app) as client:
        response = client.get("/health")
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_request_id_is_echoed_when_present() -> None:
    app = create_app(service_name="t", version="0")
    with TestClient(app) as client:
        response = client.get("/health", headers={REQUEST_ID_HEADER: "req-123"})
    assert response.headers[REQUEST_ID_HEADER] == "req-123"


def test_custom_routers_are_mounted() -> None:
    router = APIRouter(prefix="/v1/demo")

    @router.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "pong"}

    app = create_app(service_name="t", version="0", routers=[router])
    with TestClient(app) as client:
        assert client.get("/v1/demo/ping").json() == {"status": "pong"}
