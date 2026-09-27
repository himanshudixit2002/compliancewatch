from collections.abc import Awaitable, Callable

import pytest
from fastapi.testclient import TestClient

from py_common.app import create_app


async def _failing() -> bool:
    return False


async def _raising() -> bool:
    raise RuntimeError("boom")


async def _ok() -> bool:
    return True


def test_health_reports_service_and_version() -> None:
    app = create_app(service_name="t", version="1.2.3")
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "t", "version": "1.2.3"}


def test_ready_without_checks_is_ready() -> None:
    app = create_app(service_name="t", version="0")
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {}}


def test_ready_with_passing_check() -> None:
    app = create_app(service_name="t", version="0", readiness_checks=[("db", _ok)])
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"db": True}}


@pytest.mark.parametrize("check", [_failing, _raising])
def test_ready_reports_503_when_a_check_fails(check: Callable[[], Awaitable[bool]]) -> None:
    app = create_app(service_name="t", version="0", readiness_checks=[("db", check)])
    with TestClient(app) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"db": False}}
