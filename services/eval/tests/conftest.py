from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eval_service.main import build_app
from eval_service.testing import ScriptedRunner, eval_settings
from eval_service.wiring import Wiring


@pytest.fixture
def runner() -> ScriptedRunner:
    return ScriptedRunner()


@pytest.fixture
def app(runner: ScriptedRunner) -> FastAPI:
    return build_app(eval_settings(), runner=runner)


@pytest.fixture
def wiring(app: FastAPI) -> Wiring:
    wired: Wiring = app.state.wiring
    return wired


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
