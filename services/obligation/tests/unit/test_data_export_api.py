"""``GET /v1/obligation/data-export`` in header and token mode: who may export a tenant's data,
where the tenant comes from, and the shape of the answer."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.ids import TenantId, UserId
from obligation.application.export import SECTIONS
from obligation.infrastructure.memory import MemoryStore
from obligation.main import build_app
from obligation.settings import ObligationSettings
from obligation.testing import OTHER_TENANT, TENANT, TenantRecords, tenant_records
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ISSUER = TestIssuer()
ROUTE = "/v1/obligation/data-export"
AS_TENANT = {"x-tenant-id": str(TENANT)}
AS_OTHER = {"x-tenant-id": str(OTHER_TENANT)}
MADE = datetime(2000, 1, 5, 4, 30, tzinfo=UTC)
OWNER_ID = UserId(UUID(int=0x0E1))
OWNER = bearer(ISSUER.user(TENANT, [Role.OWNER], user_id=OWNER_ID))
CA_ADMIN = bearer(ISSUER.user(TENANT, [Role.CA_ADMIN], mfa=True))
STAFF = bearer(ISSUER.user(TENANT, [Role.STAFF]))
COMPLIANCE_LEAD = bearer(ISSUER.user(TENANT, [Role.COMPLIANCE_LEAD]))
IDENTITY_ACTING = bearer(ISSUER.service("identity", [Scope.TENANT_ACT]))
IDENTITY_UNBOUND = bearer(ISSUER.service("worker", [Scope.DATA_EXPORT, Scope.TENANT_ACT]))
"""data:export and tenant:act, but no tenant in the token: refused."""


def exporting(tenant: TenantId, audience: str = "obligation") -> dict[str, str]:
    """Identity's export token for ``tenant``, addressed to ``audience``."""
    return bearer(
        ISSUER.service("identity", [Scope.DATA_EXPORT], acts_for=tenant, audience=audience)
    )


OURS = tenant_records(TENANT, MADE, closed_by=OWNER_ID)
THEIRS = tenant_records(OTHER_TENANT, MADE)


def app_in(mode: AuthMode) -> FastAPI:
    app = build_app(
        ObligationSettings(
            _env_file=None,
            service_name="obligation",
            obligation_store="memory",
            **ISSUER.settings_overrides(mode),
        )
    )
    store = app.state.wiring.unit_of_work
    assert isinstance(store, MemoryStore)
    for records in (OURS, THEIRS):
        keep(store, records)
    return app


def keep(store: MemoryStore, records: TenantRecords) -> None:
    with store(records.obligation.tenant_id) as uow:
        uow.obligations.add(records.obligation)
        for change in records.changes:
            uow.history.append(change)
        uow.comments.add(records.comment)


@pytest.fixture
def header_mode() -> Iterator[TestClient]:
    with TestClient(app_in("header")) as client:
        yield client


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    with TestClient(app_in("token")) as client:
        yield client


def problem(response: Any) -> tuple[int, str]:
    kind: str = response.json()["type"]
    return response.status_code, kind.rsplit(":", 1)[-1]


def exported(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def obligation_ids(body: dict[str, Any]) -> list[str]:
    return [row["id"] for row in body["sections"]["obligations"]]


def test_header_mode_exports_the_tenant_the_header_names(header_mode: TestClient) -> None:
    body = exported(header_mode.get(ROUTE, headers=AS_TENANT))

    assert set(body) == {"service", "tenant_id", "generated_at", "sections"}
    assert (body["service"], body["tenant_id"]) == ("obligation", str(TENANT))
    assert datetime.fromisoformat(body["generated_at"]).tzinfo is not None
    assert list(body["sections"]) == list(SECTIONS)
    assert obligation_ids(body) == [str(OURS.obligation.id.value)]
    assert [row["kind"] for row in body["sections"]["changes"]] == ["created", "closed"]
    assert [row["body"] for row in body["sections"]["comments"]] == [OURS.comment.body]
    assert str(OTHER_TENANT) not in str(body["sections"])

    theirs = exported(header_mode.get(ROUTE, headers=AS_OTHER))
    assert obligation_ids(theirs) == [str(THEIRS.obligation.id.value)]


def test_no_tenant_is_a_401(header_mode: TestClient, token_mode: TestClient) -> None:
    assert problem(header_mode.get(ROUTE)) == (401, "obligation-tenant-required")
    assert problem(token_mode.get(ROUTE, headers=IDENTITY_ACTING)) == (
        401,
        "obligation-tenant-required",
    )


@pytest.mark.parametrize("caller", [OWNER, CA_ADMIN], ids=["owner", "ca_admin"])
def test_a_tenant_admin_exports_their_own_tenant(
    token_mode: TestClient, caller: dict[str, str]
) -> None:
    body = exported(token_mode.get(ROUTE, headers=caller))
    assert body["tenant_id"] == str(TENANT)
    assert obligation_ids(body) == [str(OURS.obligation.id.value)]
    same = exported(token_mode.get(ROUTE, headers={**caller, **AS_TENANT}))
    assert obligation_ids(same) == obligation_ids(body)


@pytest.mark.parametrize("caller", [STAFF, COMPLIANCE_LEAD], ids=["staff", "compliance_lead"])
def test_other_members_are_refused(token_mode: TestClient, caller: dict[str, str]) -> None:
    assert problem(token_mode.get(ROUTE, headers=caller))[0] == 403


def test_an_owner_naming_another_tenant_is_refused(token_mode: TestClient) -> None:
    assert problem(token_mode.get(ROUTE, headers={**OWNER, **AS_OTHER})) == (
        403,
        "auth-tenant-mismatch",
    )


def test_identity_s_bound_token_exports_the_tenant_it_names(token_mode: TestClient) -> None:
    body = exported(token_mode.get(ROUTE, headers={**exporting(OTHER_TENANT), **AS_OTHER}))
    assert body["tenant_id"] == str(OTHER_TENANT)
    assert obligation_ids(body) == [str(THEIRS.obligation.id.value)]


def test_a_token_bound_to_one_tenant_is_refused_for_another(token_mode: TestClient) -> None:
    replayed = token_mode.get(ROUTE, headers={**exporting(TENANT), **AS_OTHER})
    assert problem(replayed) == (403, "auth-tenant-mismatch")


def test_a_token_addressed_to_another_service_is_refused(token_mode: TestClient) -> None:
    elsewhere = token_mode.get(ROUTE, headers={**exporting(TENANT, "profile"), **AS_TENANT})
    assert problem(elsewhere) == (403, "auth-forbidden")


@pytest.mark.parametrize(
    "caller", [IDENTITY_ACTING, IDENTITY_UNBOUND], ids=["no-data-export", "no-tenant-in-token"]
)
def test_a_service_without_a_bound_export_token_is_refused(
    token_mode: TestClient, caller: dict[str, str]
) -> None:
    assert problem(token_mode.get(ROUTE, headers={**caller, **AS_TENANT}))[0] == 403
