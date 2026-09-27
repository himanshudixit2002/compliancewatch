from fastapi.testclient import TestClient

from pipeline import __version__

SERVICE = "pipeline"


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": SERVICE, "version": __version__}


def test_ready(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ping(client: TestClient) -> None:
    response = client.get(f"/v1/{SERVICE}/ping")
    assert response.json() == {"service": SERVICE, "status": "pong"}


def test_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"x-request-id": "req-123"})
    assert response.headers["x-request-id"] == "req-123"
