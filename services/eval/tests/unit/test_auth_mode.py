"""The eval routes with access tokens: an admin starts a run, a regulatory role reads runs,
anyone else is refused."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.ids import TenantId
from eval_service.main import build_app
from eval_service.testing import ScriptedRunner, eval_settings
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ISSUER = TestIssuer()
RUNS = "/v1/eval/runs"
INTERNAL = TenantId.new()
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True))
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True))
OWNER = bearer(ISSUER.user(TenantId.new(), [Role.OWNER]))
SERVICE = bearer(ISSUER.service("pipeline", [Scope.LLM_CALL]))
BODY = {"suite": "relations"}


def client_in(mode: AuthMode) -> Iterator[TestClient]:
    settings = eval_settings(**ISSUER.settings_overrides(mode))
    with TestClient(build_app(settings, runner=ScriptedRunner())) as client:
        yield client


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    yield from client_in("token")


@pytest.fixture
def dual_mode() -> Iterator[TestClient]:
    yield from client_in("dual")


def problem(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["type"].rsplit(":", 1)[-1]


def test_token_mode_needs_a_bearer(token_mode: TestClient) -> None:
    assert problem(token_mode.get(RUNS)) == (401, "auth-token-required")
    assert problem(token_mode.post(RUNS, json=BODY)) == (401, "auth-token-required")


def test_an_admin_starts_and_reads_runs(token_mode: TestClient) -> None:
    started = token_mode.post(RUNS, json=BODY, headers=ADMIN)
    assert started.status_code == 201, started.text
    run_id = started.json()["run_id"]
    assert token_mode.get(f"{RUNS}/{run_id}", headers=ADMIN).status_code == 200


def test_an_analyst_reads_runs_but_does_not_start_one(token_mode: TestClient) -> None:
    run_id = token_mode.post(RUNS, json=BODY, headers=ADMIN).json()["run_id"]
    assert problem(token_mode.post(RUNS, json=BODY, headers=ANALYST)) == (403, "auth-forbidden")
    assert [run["run_id"] for run in token_mode.get(RUNS, headers=ANALYST).json()] == [run_id]
    assert token_mode.get(f"{RUNS}/{run_id}", headers=ANALYST).status_code == 200


@pytest.mark.parametrize("caller", [OWNER, SERVICE])
def test_a_tenant_member_or_a_service_is_refused(
    token_mode: TestClient, caller: dict[str, str]
) -> None:
    assert problem(token_mode.get(RUNS, headers=caller)) == (403, "auth-forbidden")
    assert problem(token_mode.post(RUNS, json=BODY, headers=caller)) == (403, "auth-forbidden")


def test_dual_mode_without_a_bearer_serves_as_before(dual_mode: TestClient) -> None:
    assert dual_mode.post(RUNS, json=BODY).status_code == 201
    assert problem(dual_mode.post(RUNS, json=BODY, headers=ANALYST)) == (403, "auth-forbidden")
