"""The tenant's data export: the use case on the memory store, and the route in header and token
mode with who may call it."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ontology as ontology_package
from domain_kernel.access import Role, Scope
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Pan
from domain_kernel.ids import TenantId
from domain_kernel.ontology import Ontology
from profile_service.application.attributes import ConfirmFinancialYear, SetAttributes
from profile_service.application.export import SECTIONS, ExportTenantData
from profile_service.application.registration import RegisterNodes
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange, ValueState
from profile_service.infrastructure.memory import MemoryProfileRepository, MemoryStore
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import GSTIN_KARNATAKA, OTHER_TENANT, PAN, TENANT, clock
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

FY = FinancialYear(2000)
EXPORT = "/v1/profile/data-export"
OTHER_PAN = Pan("ZYXWV9876A")
ISSUER = TestIssuer()


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


def stocked(store: MemoryStore, ontology: Ontology, tenant: TenantId, name: str) -> None:
    """An entity with a registration, values on the entity (one not applicable, so a review
    task opens) and a financial-year confirmation task."""
    registered = RegisterNodes(store, clock=clock).registration(
        tenant, GSTIN_KARNATAKA, f"{name} Bengaluru", entity_name=name
    )
    entity_id = registered.node.parent_id
    assert entity_id is not None
    SetAttributes(store, ontology, clock=clock).run(
        tenant,
        entity_id,
        [
            AttributeChange("state_codes", ["29"]),
            AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE),
        ],
        source=ChangeSource.USER_INPUT,
    )
    ConfirmFinancialYear(store, ontology, clock=clock).run(tenant, FY)


def test_the_export_holds_the_asked_tenants_rows_only(ontology: Ontology) -> None:
    store = MemoryStore()
    stocked(store, ontology, TENANT, "Example Traders")
    stocked(store, ontology, OTHER_TENANT, "Example Other")
    others = [str(node.id) for node in store.nodes.values() if node.tenant_id == OTHER_TENANT]
    others += [str(task.id) for task in store.tasks.values() if task.tenant_id == OTHER_TENANT]
    generated = datetime(2000, 6, 1, 12, 0, tzinfo=UTC)

    export = ExportTenantData(store, clock=lambda: generated).run(TENANT)

    assert (export.service, export.tenant_id, export.generated_at) == (
        "profile",
        TENANT,
        generated,
    )
    assert tuple(export.sections) == SECTIONS
    nodes = export.sections["nodes"]
    assert sorted(node["key"] for node in nodes) == sorted([PAN.value, GSTIN_KARNATAKA.value])
    assert {node["level"] for node in nodes} == {"entity", "registration"}
    entity = next(node for node in nodes if node["level"] == "entity")
    assert entity["name"] == "Example Traders"
    assert set(entity) == {
        "id",
        "level",
        "key",
        "name",
        "parent_id",
        "version",
        "created_at",
        "updated_at",
    }
    attributes = {row["key"]: row for row in export.sections["attributes"]}
    assert attributes["state_codes"]["value"] == ["29"]
    assert attributes["state_codes"]["node_id"] == entity["id"]
    assert attributes["employee_count"]["state"] == "not_applicable"
    assert attributes["employee_count"]["value"] is None
    (version,) = export.sections["versions"]
    assert (version["node_id"], version["version"]) == (entity["id"], 2)
    assert version["attributes"] == {"state_codes@": ["29"]}
    reasons = sorted(task["reason"] for task in export.sections["review_tasks"])
    assert reasons == ["confirm_financial_year", "not_applicable"]
    text = json.dumps(dict(export.sections))
    assert str(OTHER_TENANT) not in text
    assert str(TENANT) not in text
    assert "Example Other" not in text
    assert not [other for other in others if other in text]


def test_every_section_is_present_for_a_tenant_without_rows() -> None:
    export = ExportTenantData(MemoryStore()).run(TENANT)
    assert dict(export.sections) == {name: [] for name in SECTIONS}
    assert export.generated_at.tzinfo is not None


def test_the_sections_are_read_a_page_at_a_time_and_in_order(
    ontology: Ontology, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore()
    moments = iter(datetime(2000, 4, 1, tzinfo=UTC) + timedelta(minutes=n) for n in range(100))
    register = RegisterNodes(store, clock=lambda: next(moments))
    for number in range(5):
        register.entity(TENANT, Pan(f"ABCDE{1000 + number}F"), f"Example {number}")
    register.entity(OTHER_TENANT, OTHER_PAN, "Example Other")
    ConfirmFinancialYear(store, ontology, clock=lambda: next(moments)).run(TENANT, FY)

    whole = ExportTenantData(store).run(TENANT)
    pages: list[int] = []
    read_nodes = MemoryProfileRepository.export_nodes

    def counted(self: MemoryProfileRepository, after: Any, limit: int) -> Any:
        page = read_nodes(self, after, limit)
        pages.append(len(page))
        return page

    monkeypatch.setattr(MemoryProfileRepository, "export_nodes", counted)
    paged = ExportTenantData(store, page_size=2).run(TENANT)

    assert pages == [2, 2, 1]

    for name in SECTIONS:
        assert paged.sections[name] == whole.sections[name], name
    nodes = paged.sections["nodes"]
    assert [node["name"] for node in nodes] == [f"Example {number}" for number in range(5)]
    tasks = paged.sections["review_tasks"]
    assert len(tasks) == 5
    keys = [(task["created_at"], task["id"]) for task in tasks]
    assert keys == sorted(keys)


def test_a_page_size_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="page_size"):
        ExportTenantData(MemoryStore(), page_size=0)


# ---------------------------------------------------------------- the route


def app_in(mode: AuthMode) -> FastAPI:
    return build_app(
        ProfileSettings(
            _env_file=None,
            service_name="profile",
            profile_store="memory",
            **ISSUER.settings_overrides(mode),
        )
    )


@pytest.fixture
def header_mode() -> Iterator[TestClient]:
    with TestClient(app_in("header")) as client:
        yield client


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    with TestClient(app_in("token")) as client:
        yield client


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def register(client: TestClient, tenant: TenantId) -> None:
    created = client.post(
        "/v1/profile/registrations",
        json={"gstin": GSTIN_KARNATAKA.value, "name": "Example Bengaluru", "entity_name": "Ex"},
        headers={
            "x-tenant-id": str(tenant),
            **bearer(ISSUER.service("pipeline", [Scope.TENANT_ACT])),
        },
    )
    assert created.status_code == 201, created.text


def test_header_mode_exports_the_tenant_named_in_the_header(header_mode: TestClient) -> None:
    register(header_mode, TENANT)
    response = header_mode.get(EXPORT, headers={"x-tenant-id": str(TENANT)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["service"], body["tenant_id"]) == ("profile", str(TENANT))
    assert datetime.fromisoformat(body["generated_at"]).tzinfo is not None
    assert sorted(body["sections"]) == sorted(SECTIONS)
    assert {node["key"] for node in body["sections"]["nodes"]} == {
        PAN.value,
        GSTIN_KARNATAKA.value,
    }
    other = header_mode.get(EXPORT, headers={"x-tenant-id": str(OTHER_TENANT)})
    assert other.json()["sections"]["nodes"] == []


def test_header_mode_without_a_tenant_is_a_401(header_mode: TestClient) -> None:
    response = header_mode.get(EXPORT)
    assert (response.status_code, problem(response)) == (401, "tenant-required")


@pytest.mark.parametrize(
    ("token", "tenant_header", "status"),
    [
        pytest.param(ISSUER.user(TENANT, [Role.OWNER]), None, 200, id="owner"),
        pytest.param(ISSUER.user(TENANT, [Role.CA_ADMIN]), None, 200, id="ca_admin"),
        pytest.param(ISSUER.user(TENANT, [Role.STAFF]), None, 403, id="staff"),
        pytest.param(
            ISSUER.service("identity", [Scope.DATA_EXPORT, Scope.TENANT_ACT]),
            TENANT,
            200,
            id="service with data:export",
        ),
        pytest.param(
            ISSUER.service("pipeline", [Scope.TENANT_ACT]),
            TENANT,
            403,
            id="service without data:export",
        ),
        pytest.param(
            ISSUER.user(TENANT, [Role.OWNER]), OTHER_TENANT, 403, id="owner naming another tenant"
        ),
    ],
)
def test_token_mode_lets_admins_and_exporting_services_read(
    token_mode: TestClient, token: str, tenant_header: TenantId | None, status: int
) -> None:
    register(token_mode, TENANT)
    headers = bearer(token)
    if tenant_header is not None:
        headers["x-tenant-id"] = str(tenant_header)
    response = token_mode.get(EXPORT, headers=headers)
    assert response.status_code == status, response.text
    if status == 200:
        body = response.json()
        assert body["tenant_id"] == str(TENANT)
        assert len(body["sections"]["nodes"]) == 2
