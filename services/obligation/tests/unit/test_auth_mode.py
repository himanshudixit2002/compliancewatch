"""The obligation routes in header, dual and token mode: where the tenant comes from, who may
read and who may change an obligation, and when an assignee is checked with the identity
service."""

from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.ids import ObligationId, UserId
from obligation.application.materialise import MaterialiseRequest
from obligation.infrastructure.memory import MemoryStore
from obligation.main import build_app
from obligation.settings import ObligationSettings
from obligation.testing import (
    BUSINESS,
    DECISION,
    OTHER_TENANT,
    TENANT,
    FakeRuleVersionReader,
    FakeTenantMembers,
    rule,
)
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ISSUER = TestIssuer()
ROUTE = "/v1/obligation/obligations"
QUERY = {"business_id": str(BUSINESS)}
AS_TENANT = {"x-tenant-id": str(TENANT)}
AS_OTHER = {"x-tenant-id": str(OTHER_TENANT)}
OWNER_ID = UserId(UUID(int=0x0E1))
STAFF_ID = UserId(UUID(int=0x5AF))
OWNER = bearer(ISSUER.user(TENANT, [Role.OWNER], user_id=OWNER_ID))
COMPLIANCE_LEAD = bearer(ISSUER.user(TENANT, [Role.COMPLIANCE_LEAD]))
STAFF_OF_OTHER = bearer(ISSUER.user(OTHER_TENANT, [Role.STAFF]))
ANALYST = bearer(ISSUER.user(TENANT, [Role.ANALYST], mfa=True))
QA_ACTING = bearer(ISSUER.service("qa", [Scope.LLM_CALL, Scope.TENANT_ACT]))
QA_ALONE = bearer(ISSUER.service("qa", [Scope.LLM_CALL]))


THE_RULE = rule()


def app_in(mode: AuthMode, members: FakeTenantMembers | None = None) -> FastAPI:
    app = build_app(
        ObligationSettings(
            _env_file=None,
            service_name="obligation",
            obligation_store="memory",
            **ISSUER.settings_overrides(mode),
        ),
        rules=FakeRuleVersionReader([THE_RULE]),
        members=members or FakeTenantMembers([(TENANT, OWNER_ID), (TENANT, STAFF_ID)]),
    )
    app.state.wiring.materialise.run(
        MaterialiseRequest(TENANT, BUSINESS, DECISION, THE_RULE, date(2026, 9, 28))
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


# ---------------------------------------------------------------- tracking


def first_obligation(client: TestClient) -> ObligationId:
    store = client.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
    assert isinstance(store, MemoryStore)
    return min(store.obligations, key=lambda obligation_id: store.obligations[obligation_id].title)


def keyed(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def test_token_mode_lets_a_member_change_an_obligation_as_themselves(
    token_mode: TestClient,
) -> None:
    obligation = first_obligation(token_mode)
    route = f"{ROUTE}/{obligation}"
    started = token_mode.post(f"{route}/status", json={"action": "start"}, headers=keyed(OWNER))
    assert started.status_code == 200, started.text
    commented = token_mode.post(
        f"{route}/comments", json={"body": "Example comment (synthetic)"}, headers=keyed(OWNER)
    )
    assert (commented.json()["author_id"], commented.json()["author_label"]) == (
        str(OWNER_ID),
        "owner",
    )
    detail = token_mode.get(route, headers=OWNER).json()
    (change,) = [c for c in detail["history"] if c["kind"] == "started"]
    assert change["actor"] == str(OWNER_ID)
    store = token_mode.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
    assert {entry.actor.label for entry in store.audit} == {"owner"}
    assert {entry.actor.id for entry in store.audit} == {str(OWNER_ID)}


def test_token_mode_lets_a_service_read_an_obligation_but_never_change_one(
    token_mode: TestClient,
) -> None:
    route = f"{ROUTE}/{first_obligation(token_mode)}"
    read = token_mode.get(route, headers={**QA_ACTING, **AS_TENANT})
    assert read.status_code == 200, read.text
    for method, path, body in (
        ("post", f"{route}/status", {"action": "start"}),
        ("put", f"{route}/assignee", {"assignee_id": None}),
        ("post", f"{route}/comments", {"body": "Example comment (synthetic)"}),
    ):
        refused = token_mode.request(
            method, path, json=body, headers=keyed({**QA_ACTING, **AS_TENANT})
        )
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
        analyst = token_mode.request(method, path, json=body, headers=keyed(ANALYST))
        assert (analyst.status_code, problem(analyst)) == (403, "auth-forbidden")
        other = token_mode.request(method, path, json=body, headers=keyed(STAFF_OF_OTHER))
        assert (other.status_code, problem(other)) == (404, "obligation-not-found")
        anonymous = token_mode.request(method, path, json=body, headers=keyed(AS_TENANT))
        assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")


def test_token_mode_assigns_only_an_active_user_of_the_tenant() -> None:
    members = FakeTenantMembers([(TENANT, OWNER_ID), (TENANT, STAFF_ID)], disabled=[OWNER_ID])
    with TestClient(app_in("token", members)) as client:
        route = f"{ROUTE}/{first_obligation(client)}/assignee"
        assigned = client.put(route, json={"assignee_id": str(STAFF_ID)}, headers=keyed(OWNER))
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["assignee_id"] == str(STAFF_ID)
        stranger = UserId.new()
        for user in (stranger, OWNER_ID):
            refused = client.put(route, json={"assignee_id": str(user)}, headers=keyed(OWNER))
            assert (refused.status_code, problem(refused)) == (422, "obligation-assignee-unknown")
        members.down = True
        down = client.put(route, json={"assignee_id": str(OWNER_ID)}, headers=keyed(OWNER))
        assert (down.status_code, problem(down)) == (503, "identity-unavailable")
        unassigned = client.put(route, json={"assignee_id": None}, headers=keyed(OWNER))
        assert unassigned.json()["assignee_id"] is None
    assert members.asked == [
        (TENANT, STAFF_ID),
        (TENANT, stranger),
        (TENANT, OWNER_ID),
        (TENANT, OWNER_ID),
    ], "nobody is asked about to unassign"


def test_dual_mode_checks_the_assignee_of_a_signed_in_caller_only() -> None:
    members = FakeTenantMembers([(TENANT, STAFF_ID)])
    with TestClient(app_in("dual", members)) as client:
        route = f"{ROUTE}/{first_obligation(client)}/assignee"
        stranger = str(UserId.new())
        kept = client.put(route, json={"assignee_id": stranger}, headers=keyed(AS_TENANT))
        assert kept.json()["assignee_id"] == stranger
        assert members.asked == []
        refused = client.put(route, json={"assignee_id": stranger}, headers=keyed(OWNER))
        assert refused.status_code == 200, "the assignee it has needs no check"
        checked = client.put(route, json={"assignee_id": str(STAFF_ID)}, headers=keyed(OWNER))
        assert checked.json()["assignee_id"] == str(STAFF_ID)
        assert members.asked == [(TENANT, STAFF_ID)]
