"""The Unleash provider against a real Unleash server and the real client. Needs Docker.

Unleash runs on its own Postgres on a private network. The test creates the flags through the
admin API under their registry names, the way an operator would, then reads them through
``flag_enabled`` and ``flag_value`` with a client token, as a service does with
``CW_FLAGS_PROVIDER=unleash``.
"""

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from openfeature import api
from pydantic import SecretStr
from structlog.testing import capture_logs
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from py_common.flags import (
    DOMAIN,
    UnleashFlagProvider,
    flag_enabled,
    flag_value,
    reset_flags,
)
from py_common.settings import Settings

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
UNLEASH_IMAGE = "unleashorg/unleash-server:8.2.0"
# Tokens the container is started with; they exist only inside the throwaway container.
ADMIN_TOKEN = "*:*.integration-test-admin"
CLIENT_TOKEN = "default:development.integration-test-client"
TENANT_A = "3f1c2a8e-0000-4000-8000-00000000000a"
TENANT_B = "3f1c2a8e-0000-4000-8000-00000000000b"
FEATURES = "/api/admin/projects/default/features"


def _admin(base: str, method: str, path: str, body: dict[str, Any] | None = None) -> None:
    response = httpx2.request(
        method, base + path, json=body, headers={"Authorization": ADMIN_TOKEN}, timeout=10
    )
    response.raise_for_status()


def _strategy(
    name: str,
    *,
    constraints: list[dict[str, Any]] | None = None,
    variants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": "flexibleRollout",
        "parameters": {"rollout": "100", "stickiness": "default", "groupId": name},
        "constraints": constraints or [],
        "variants": variants or [],
    }


def _create(base: str, name: str, strategy: dict[str, Any] | None, *, on: bool) -> None:
    _admin(base, "POST", FEATURES, {"name": name, "type": "release"})
    environment = f"{FEATURES}/{name}/environments/development"
    if strategy is not None:
        _admin(base, "POST", f"{environment}/strategies", strategy)
    if on:
        _admin(base, "POST", f"{environment}/on")


@pytest.fixture(scope="module")
def unleash_url() -> Iterator[str]:
    with (
        Network() as network,
        PostgresContainer(POSTGRES_IMAGE, username="unleash", password="unleash", dbname="unleash")
        .with_network(network)
        .with_network_aliases("db"),
        DockerContainer(UNLEASH_IMAGE)
        .with_network(network)
        .with_env("DATABASE_URL", "postgres://unleash:unleash@db:5432/unleash")
        .with_env("DATABASE_SSL", "false")
        .with_env("INIT_ADMIN_API_TOKENS", ADMIN_TOKEN)
        .with_env("INIT_BACKEND_API_TOKENS", CLIENT_TOKEN)
        .with_env("LOG_LEVEL", "warn")
        .with_exposed_ports(4242) as unleash,
    ):
        base = f"http://{unleash.get_container_host_ip()}:{unleash.get_exposed_port(4242)}"
        deadline = time.monotonic() + 120
        while True:
            try:
                if httpx2.get(base + "/health", timeout=2).status_code == 200:
                    break
            except httpx2.HTTPError:
                pass
            if time.monotonic() > deadline:
                pytest.fail(f"Unleash did not become healthy:\n{unleash.get_logs()}")
            time.sleep(1)
        # qa.kag is on for tenant A only; rulebook.publish exists but is off; profile.gstin_lookup
        # serves the static provider as a variant. pipeline.knowledge is not in Unleash at all.
        tenant_a = {"contextName": "userId", "operator": "IN", "values": [TENANT_A]}
        _create(base, "qa.kag", _strategy("qa.kag", constraints=[tenant_a]), on=True)
        _create(base, "rulebook.publish", None, on=False)
        static = {
            "name": "static",
            "weight": 1000,
            "weightType": "variable",
            "stickiness": "default",
            "payload": {"type": "string", "value": "static"},
        }
        lookup = _strategy("profile.gstin_lookup", variants=[static])
        _create(base, "profile.gstin_lookup", lookup, on=True)
        yield base + "/api"


@pytest.fixture
def unleash_flags(unleash_url: str, tmp_path: Path) -> Iterator[UnleashFlagProvider]:
    settings = Settings(
        service_name="py-common-test",
        flags_provider="unleash",
        unleash_url=unleash_url,
        unleash_api_token=SecretStr(CLIENT_TOKEN),
    )
    provider = UnleashFlagProvider.from_settings(settings, cache_directory=str(tmp_path))
    api.set_provider_and_wait(provider, DOMAIN)
    yield provider
    reset_flags()
    provider.shutdown()


@pytest.mark.usefixtures("unleash_flags")
def test_a_flag_on_for_one_tenant() -> None:
    assert flag_enabled("qa.kag", TENANT_A) is True
    assert flag_enabled("qa.kag", TENANT_B) is False
    assert flag_enabled("qa.kag") is False


@pytest.mark.usefixtures("unleash_flags")
def test_a_flag_that_is_off() -> None:
    assert flag_enabled("rulebook.publish", TENANT_A) is False


@pytest.mark.usefixtures("unleash_flags")
def test_a_flag_unleash_does_not_hold_answers_its_default() -> None:
    with capture_logs() as logs:
        assert flag_enabled("pipeline.knowledge") is False
    assert [entry["error_code"] for entry in logs] == ["FLAG_NOT_FOUND"]


@pytest.mark.usefixtures("unleash_flags")
def test_a_string_flag_from_a_variant() -> None:
    assert flag_value("profile.gstin_lookup", TENANT_B) == "static"
    assert flag_value("identity.billing_provider") == "none"
