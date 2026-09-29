"""The profile routes in header, dual and token mode: where the tenant comes from, who may call,
and who is recorded as having changed a value."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.ids import UserId
from profile_service.domain.events import ProfileUpdated
from profile_service.infrastructure.memory import MemoryStore
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import OTHER_TENANT, TENANT
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ISSUER = TestIssuer()
REGISTRATIONS = "/v1/profile/registrations"
BUSINESSES = "/v1/businesses"
AS_TENANT = {"x-tenant-id": str(TENANT)}
AS_OTHER = {"x-tenant-id": str(OTHER_TENANT)}
REGISTRATION = {"gstin": "29ABCDE1234F1Z5", "name": "Acme Bengaluru", "entity_name": "Acme"}
OWNER_ID = UserId.new()
OWNER = bearer(ISSUER.user(TENANT, [Role.OWNER], user_id=OWNER_ID))
STAFF_OF_OTHER = bearer(ISSUER.user(OTHER_TENANT, [Role.STAFF]))
ANALYST = bearer(ISSUER.user(TENANT, [Role.ANALYST], mfa=True))
PIPELINE_ACTING = bearer(ISSUER.service("pipeline", [Scope.TENANT_ACT]))
PIPELINE_ALONE = bearer(ISSUER.service("pipeline", [Scope.RULEBOOK_WRITE]))


def app_in(mode: AuthMode) -> FastAPI:
    return build_app(
        ProfileSettings(
            _env_file=None,
            service_name="profile",
            profile_store="memory",
            **ISSUER.settings_overrides(mode),
        )
    )


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


def register(client: TestClient, headers: dict[str, str]) -> Any:
    return client.post(REGISTRATIONS, json=REGISTRATION, headers=headers)


def events_of(client: TestClient) -> list[ProfileUpdated]:
    app = client.app
    assert isinstance(app, FastAPI)
    store: MemoryStore = app.state.wiring.unit_of_work
    return [event for event in store.events if isinstance(event, ProfileUpdated)]


# ---------------------------------------------------------------- header mode


def test_header_mode_reads_the_tenant_header_and_ignores_a_bearer(header_mode: TestClient) -> None:
    created = register(header_mode, {**AS_TENANT, **STAFF_OF_OTHER})
    assert created.status_code == 201, created.text
    node = created.json()["id"]
    assert header_mode.get(f"/v1/profile/nodes/{node}", headers=AS_TENANT).status_code == 200
    assert header_mode.get(f"/v1/profile/nodes/{node}", headers=AS_OTHER).status_code == 404
    missing = register(header_mode, OWNER)
    assert (missing.status_code, problem(missing)) == (401, "tenant-required")


def test_header_mode_takes_changed_by_from_the_body(header_mode: TestClient) -> None:
    node = register(header_mode, AS_TENANT).json()["id"]
    named = UserId.new()
    changed = header_mode.put(
        f"/v1/profile/nodes/{node}/attributes",
        json={
            "changes": [{"key": "registration_type", "value": "regular"}],
            "changed_by": str(named),
        },
        headers=AS_TENANT,
    )
    assert changed.status_code == 200, changed.text
    assert events_of(header_mode)[-1].changed_by == named


# ---------------------------------------------------------------- dual mode


def test_dual_mode_without_a_bearer_serves_the_header_as_before(dual_mode: TestClient) -> None:
    assert register(dual_mode, AS_TENANT).status_code == 201
    missing = register(dual_mode, {})
    assert (missing.status_code, problem(missing)) == (401, "tenant-required")


def test_dual_mode_takes_the_tenant_from_a_bearer_over_the_header(dual_mode: TestClient) -> None:
    created = register(dual_mode, OWNER)
    assert created.status_code == 201, created.text
    node = created.json()["id"]
    assert dual_mode.get(f"/v1/profile/nodes/{node}", headers=AS_TENANT).status_code == 200
    same = dual_mode.get(f"/v1/profile/nodes/{node}", headers={**OWNER, **AS_TENANT})
    assert same.status_code == 200
    other = dual_mode.get(f"/v1/profile/nodes/{node}", headers={**OWNER, **AS_OTHER})
    assert (other.status_code, problem(other)) == (403, "auth-tenant-mismatch")
    theirs = dual_mode.get(f"/v1/profile/nodes/{node}", headers={**STAFF_OF_OTHER, **AS_TENANT})
    assert (theirs.status_code, problem(theirs)) == (403, "auth-tenant-mismatch")
    assert dual_mode.get(f"/v1/profile/nodes/{node}", headers=STAFF_OF_OTHER).status_code == 404


def test_dual_mode_refuses_a_bad_bearer_whatever_the_header(dual_mode: TestClient) -> None:
    refused = register(dual_mode, {**AS_TENANT, **bearer("not-a-token")})
    assert (refused.status_code, problem(refused)) == (401, "auth-token-invalid")
    assert refused.headers["www-authenticate"].startswith("Bearer")
    forbidden = register(dual_mode, {**AS_TENANT, **ANALYST})
    assert (forbidden.status_code, problem(forbidden)) == (403, "auth-forbidden")


# ---------------------------------------------------------------- token mode


def test_token_mode_needs_a_bearer(token_mode: TestClient) -> None:
    refused = register(token_mode, AS_TENANT)
    assert (refused.status_code, problem(refused)) == (401, "auth-token-required")
    assert refused.headers["www-authenticate"] == "Bearer"
    listed = token_mode.get(BUSINESSES, headers=AS_TENANT)
    assert (listed.status_code, problem(listed)) == (401, "auth-token-required")


def test_token_mode_serves_a_member_of_the_tenant(token_mode: TestClient) -> None:
    created = register(token_mode, OWNER)
    assert created.status_code == 201, created.text
    node = created.json()["id"]
    assert token_mode.get(f"/v1/profile/nodes/{node}", headers=OWNER).status_code == 200
    assert token_mode.get(f"/v1/profile/nodes/{node}", headers=STAFF_OF_OTHER).status_code == 404
    other = token_mode.get(f"/v1/profile/nodes/{node}", headers={**OWNER, **AS_OTHER})
    assert (other.status_code, problem(other)) == (403, "auth-tenant-mismatch")


def test_token_mode_refuses_a_role_outside_the_tenant_members(token_mode: TestClient) -> None:
    refused = register(token_mode, ANALYST)
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")


def test_token_mode_lets_a_service_act_for_a_tenant_only_with_tenant_act(
    token_mode: TestClient,
) -> None:
    acting = register(token_mode, {**PIPELINE_ACTING, **AS_TENANT})
    assert acting.status_code == 201, acting.text
    alone = register(token_mode, {**PIPELINE_ALONE, **AS_TENANT})
    assert (alone.status_code, problem(alone)) == (403, "auth-forbidden")
    unnamed = register(token_mode, PIPELINE_ACTING)
    assert (unnamed.status_code, problem(unnamed)) == (401, "tenant-required")


def test_token_mode_records_the_signed_in_user_as_the_changer(token_mode: TestClient) -> None:
    node = register(token_mode, OWNER).json()["id"]
    changed = token_mode.put(
        f"/v1/profile/nodes/{node}/attributes",
        json={
            "changes": [{"key": "registration_type", "value": "regular"}],
            "changed_by": str(UserId.new()),
        },
        headers=OWNER,
    )
    assert changed.status_code == 200, changed.text
    assert events_of(token_mode)[-1].changed_by == OWNER_ID
    by_service = token_mode.put(
        f"/v1/profile/nodes/{node}/attributes",
        json={
            "changes": [{"key": "registration_type", "value": "composition"}],
            "changed_by": str(UserId.new()),
        },
        headers={**PIPELINE_ACTING, **AS_TENANT},
    )
    assert by_service.status_code == 200, by_service.text
    assert events_of(token_mode)[-1].changed_by is None


def test_token_mode_serves_the_business_api_to_a_member(token_mode: TestClient) -> None:
    created = token_mode.post(
        BUSINESSES,
        json={"name": "Acme Holdings", "pan": "AAAAA1111A"},
        headers={**OWNER, "Idempotency-Key": "auth-mode-business-01"},
    )
    assert created.status_code == 201, created.text
    business = created.json()["business"]["id"]
    renamed = token_mode.patch(f"{BUSINESSES}/{business}", json={"name": "Acme"}, headers=OWNER)
    assert renamed.status_code == 200, renamed.text
    listed = token_mode.get(BUSINESSES, headers=OWNER).json()["items"]
    assert [item["name"] for item in listed] == ["Acme"]
    assert token_mode.get(BUSINESSES, headers=STAFF_OF_OTHER).json()["items"] == []


def test_the_ontology_needs_no_token_in_any_mode(token_mode: TestClient) -> None:
    assert token_mode.get("/v1/ontology").status_code == 200
