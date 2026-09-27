from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from profile_service.main import build_app
from profile_service.settings import ProfileSettings


def profile_settings(**overrides: Any) -> ProfileSettings:
    """Settings that ignore the repo ``.env``; the memory store by default."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "profile",
        "profile_store": "memory",
    }
    values.update(overrides)
    return ProfileSettings(**values)


@pytest.fixture
def app() -> FastAPI:
    return build_app(profile_settings())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
