from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicability_engine.main import build_app
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import MemoryProfiles, MemoryRulebook
from applicability_engine.wiring import Readers


def engine_settings(**overrides: Any) -> ApplicabilityEngineSettings:
    """Settings that ignore the repo ``.env``; the memory store, so no Postgres is needed."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "applicability-engine",
        "applicability_engine_store": "memory",
    }
    values.update(overrides)
    return ApplicabilityEngineSettings(**values)


@pytest.fixture
def profiles() -> MemoryProfiles:
    return MemoryProfiles()


@pytest.fixture
def rulebook() -> MemoryRulebook:
    return MemoryRulebook()


@pytest.fixture
def app(profiles: MemoryProfiles, rulebook: MemoryRulebook) -> FastAPI:
    return build_app(engine_settings(), readers=Readers(profiles=profiles, rulebook=rulebook))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
