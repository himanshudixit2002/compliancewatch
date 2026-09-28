from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from obligation.main import build_app
from obligation.settings import ObligationSettings


def obligation_settings(**overrides: Any) -> ObligationSettings:
    """Settings that ignore the repo ``.env``; the memory store, so no Postgres is needed."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "obligation",
        "obligation_store": "memory",
    }
    values.update(overrides)
    return ObligationSettings(**values)


@pytest.fixture
def app() -> FastAPI:
    return build_app(obligation_settings())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
