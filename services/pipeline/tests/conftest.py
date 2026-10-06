from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pipeline.main import build_app
from pipeline.testing import pipeline_settings


@pytest.fixture
def app() -> FastAPI:
    """The app on memory stores: no test reaches a database or the repo's ``.env``."""
    return build_app(pipeline_settings())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
