from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from notification.main import build_app
from notification.testing import notification_settings


@pytest.fixture
def app() -> FastAPI:
    return build_app(notification_settings())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
