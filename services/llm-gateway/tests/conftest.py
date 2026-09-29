import os
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import settings

from domain_kernel.protocols import LLMProvider
from llm_gateway.main import build_app
from llm_gateway.settings import GatewaySettings
from llm_gateway.wiring import GatewayWiring

AppFactory = Callable[..., FastAPI]


def gateway_settings(**overrides: Any) -> GatewaySettings:
    """Settings that ignore the repo ``.env``; explicit values win over the environment."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "llm-gateway",
        "llm_provider": "fake",
        "llm_ledger": "memory",
        "llm_routes": {},
        "llm_tenant_monthly_budget_inr": Decimal("1500"),
        "llm_feature_monthly_budget_inr": Decimal("20000"),
        "langfuse_host": None,
        "langfuse_public_key": None,
        "langfuse_secret_key": None,
    }
    values.update(overrides)
    return GatewaySettings(**values)


@pytest.fixture
def make_app() -> AppFactory:
    def factory(*, completion_provider: LLMProvider | None = None, **overrides: Any) -> FastAPI:
        return build_app(gateway_settings(**overrides), completion_provider=completion_provider)

    return factory


@pytest.fixture
def app(make_app: AppFactory) -> FastAPI:
    return make_app()


@pytest.fixture
def wiring(app: FastAPI) -> GatewayWiring:
    gateway: GatewayWiring = app.state.gateway
    return gateway


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# ---- hypothesis ----------------------------------------------------------------------------
# ``ci`` (the default) is deterministic and skips the example database; ``dev`` runs fewer
# examples. Select with ``HYPOTHESIS_PROFILE=dev``.

settings.register_profile(
    "ci", derandomize=True, database=None, max_examples=200, deadline=None, print_blob=True
)
settings.register_profile("dev", database=None, max_examples=50, deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
