"""The obligation read route in header, dual and token mode: where the tenant comes from and who
may read."""

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from obligation.application.materialise import MaterialiseRequest
from obligation.main import build_app
from obligation.settings import ObligationSettings
from obligation.testing import BUSINESS, DECISION, OTHER_TENANT, TENANT, rule
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ISSUER = TestIssuer()
ROUTE = "/v1/obligation/obligations"
QUERY = {"business_id": str(BUSINESS)}
AS_TENANT = {"x-tenant-id": str(TENANT)}
AS_OTHER = {"x-tenant-id": str(OTHER_TENANT)}
OWNER = bearer(ISSUER.user(TENANT, [Role.OWNER]))
COMPLIANCE_LEAD = bearer(ISSUER.user(TENANT, [Role.COMPLIANCE_LEAD]))
STAFF_OF_OTHER = bearer(ISSUER.user(OTHER_TENANT, [Role.STAFF]))
ANALYST = bearer(ISSUER.user(TENANT, [Role.ANALYST], mfa=True))
QA_ACTING = bearer(ISSUER.service("qa", [Scope.LLM_CALL, Scope.TENANT_ACT]))
QA_ALONE = bearer(ISSUER.service("qa", [Scope.LLM_CALL]))


def app_in(mode: AuthMode) -> FastAPI:
    app = build_app(
        ObligationSettings(
            _env_file=None,
            service_name="obligation",
            obligation_store="memory",
            **ISSUER.settings_overrides(mode),
        )
    )
    app.state.wiring.materialise.run(
        MaterialiseRequest(TENANT, BUSINESS, DECISION, rule(), date(2026, 9, 28))
    )
    return app


def client_in(mode: AuthMode) -> Iterator[TestClient]:
    with TestClient(app_in(mode)) as client:
        yield client


@pytest.fixture
def header_mode() -> Iterator[TestClient]:
    yield from client_in("header")


@pytest.fixture
def dual_mode() -> Iterator[TestClient]:
    yield from client_in("dual")


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    yield from client_in("token")


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def read(client: TestClient, headers: dict[str, str]) -> Any:
    return client.get(ROUTE, params=QUERY, headers=headers)


def periods(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["period_label"] for item in response.json()]


# ---------------------------------------------------------------- header mode


def test_header_mode_reads_the_tenant_header_and_ignores_a_bearer(header_mode: TestClient) -> None:
    assert periods(read(header_mode, {**AS_TENANT, **STAFF_OF_OTHER})) == ["2026-09", "2026-10"]
    assert periods(read(header_mode, AS_OTHER)) == []
    missing = read(header_mode, OWNER)
    assert (missing.status_code, problem(missing)) == (401, "obligation-tenant-required")


# ---------------------------------------------------------------- dual mode


def test_dual_mode_without_a_bearer_serves_the_header_as_before(dual_mode: TestClient) -> None:
    assert periods(read(dual_mode, AS_TENANT)) == ["2026-09", "2026-10"]
    missing = read(dual_mode, {})
    assert (missing.status_code, problem(missing)) == (401, "obligation-tenant-required")


def test_dual_mode_takes_the_tenant_from_a_bearer(dual_mode: TestClient) -> None:
    assert periods(read(dual_mode, OWNER)) == ["2026-09", "2026-10"]
    assert periods(read(dual_mode, STAFF_OF_OTHER)) == []
    mismatch = read(dual_mode, {**STAFF_OF_OTHER, **AS_TENANT})
    assert (mismatch.status_code, problem(mismatch)) == (403, "auth-tenant-mismatch")
    bad = read(dual_mode, {"Authorization": "Bearer not-a-token", **AS_TENANT})
    assert (bad.status_code, problem(bad)) == (401, "auth-token-invalid")


# ---------------------------------------------------------------- token mode


def test_token_mode_needs_a_bearer(token_mode: TestClient) -> None:
    missing = read(token_mode, AS_TENANT)
    assert (missing.status_code, problem(missing)) == (401, "auth-token-required")
    assert missing.headers["www-authenticate"].startswith("Bearer")


def test_token_mode_serves_a_member_the_obligations_of_their_own_tenant(
    token_mode: TestClient,
) -> None:
    assert periods(read(token_mode, OWNER)) == ["2026-09", "2026-10"]
    assert periods(read(token_mode, {**COMPLIANCE_LEAD, **AS_TENANT})) == ["2026-09", "2026-10"]
    assert periods(read(token_mode, STAFF_OF_OTHER)) == []


def test_token_mode_refuses_another_tenant_and_other_roles(token_mode: TestClient) -> None:
    mismatch = read(token_mode, {**STAFF_OF_OTHER, **AS_TENANT})
    assert (mismatch.status_code, problem(mismatch)) == (403, "auth-tenant-mismatch")
    analyst = read(token_mode, ANALYST)
    assert (analyst.status_code, problem(analyst)) == (403, "auth-forbidden")


def test_token_mode_lets_a_service_read_for_the_tenant_it_names_with_tenant_act(
    token_mode: TestClient,
) -> None:
    assert periods(read(token_mode, {**QA_ACTING, **AS_TENANT})) == ["2026-09", "2026-10"]
    assert periods(read(token_mode, {**QA_ACTING, **AS_OTHER})) == []
    without_scope = read(token_mode, {**QA_ALONE, **AS_TENANT})
    assert (without_scope.status_code, problem(without_scope)) == (403, "auth-forbidden")
    no_tenant = read(token_mode, QA_ACTING)
    assert (no_tenant.status_code, problem(no_tenant)) == (401, "obligation-tenant-required")
