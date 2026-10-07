"""The tenant's data export on Postgres, read through the profile's own role cw_profile (not a
superuser), so row-level security decides what a tenant's unit of work sees. Needs Docker."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Pan
from domain_kernel.ids import TenantId
from profile_service.application.attributes import ConfirmFinancialYear, SetAttributes
from profile_service.application.export import SECTIONS, ExportTenantData
from profile_service.application.registration import RegisterNodes
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange, ValueState
from profile_service.infrastructure.repository import PostgresUnitOfWorkFactory
from profile_service.testing import GSTIN_KARNATAKA, PAN
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "profile"
FY = FinancialYear(2000)


@pytest.fixture(scope="module")
def factory() -> Iterator[PostgresUnitOfWorkFactory]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        database_url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", database_url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        owner = create_engine(database_url)
        with owner.begin() as connection:
            install_audit_table(connection)
        owner.dispose()
        apply_roles(database_url)
        engine = create_engine(as_role(database_url, SCHEMA))
        yield PostgresUnitOfWorkFactory(engine)
        engine.dispose()


def clock_from(start: datetime) -> Iterator[datetime]:
    return (start + timedelta(minutes=n) for n in range(1000))


def stock(factory: PostgresUnitOfWorkFactory, tenant: TenantId, name: str, start: datetime) -> None:
    """A registration and its entity with values (one not applicable), a few more entities, and a
    financial-year confirmation task per entity."""
    ontology = ontology_package.load()
    moments = clock_from(start)
    register = RegisterNodes(factory, clock=lambda: next(moments))
    registered = register.registration(
        tenant, GSTIN_KARNATAKA, f"{name} Bengaluru", entity_name=name
    )
    entity_id = registered.node.parent_id
    assert entity_id is not None
    SetAttributes(factory, ontology, clock=lambda: next(moments)).run(
        tenant,
        entity_id,
        [
            AttributeChange("state_codes", ["29"]),
            AttributeChange("turnover_band", "2_crore_to_5_crore", as_of_fy=FY),
            AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE),
        ],
        source=ChangeSource.USER_INPUT,
    )
    for number in range(3):
        register.entity(tenant, Pan(f"ABCDE{1000 + number}F"), f"{name} {number}")
    ConfirmFinancialYear(factory, ontology, clock=lambda: next(moments)).run(
        tenant, FinancialYear(2001)
    )


def test_the_export_as_the_service_role_holds_the_tenants_rows_only(
    factory: PostgresUnitOfWorkFactory,
) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    stock(factory, tenant, "Example Traders", datetime(2000, 4, 1, tzinfo=UTC))
    stock(factory, other, "Example Other", datetime(2000, 4, 1, 0, 30, tzinfo=UTC))

    export = ExportTenantData(factory).run(tenant)

    assert tuple(export.sections) == SECTIONS
    nodes = export.sections["nodes"]
    assert len(nodes) == 5
    assert {node["key"] for node in nodes} >= {PAN.value, GSTIN_KARNATAKA.value}
    assert all(node["name"].startswith("Example Traders") for node in nodes)
    entity = next(node for node in nodes if node["key"] == PAN.value)
    attributes = {(row["key"], row["as_of_fy"]): row for row in export.sections["attributes"]}
    assert attributes[("state_codes", None)]["value"] == ["29"]
    assert attributes[("turnover_band", "2000-01")]["value"] == "2_crore_to_5_crore"
    assert attributes[("employee_count", None)]["state"] == "not_applicable"
    assert {row["node_id"] for row in attributes.values()} == {entity["id"]}
    (version,) = export.sections["versions"]
    assert (version["node_id"], version["version"]) == (entity["id"], 2)
    assert version["attributes"] == {
        "state_codes@": ["29"],
        "turnover_band@2000-01": "2_crore_to_5_crore",
    }
    reasons = sorted(task["reason"] for task in export.sections["review_tasks"])
    assert reasons.count("not_applicable") == 1
    assert reasons.count("confirm_financial_year") == 4
    text = json.dumps(dict(export.sections))
    assert "Example Other" not in text
    assert str(other) not in text
    assert str(tenant) not in text

    paged = ExportTenantData(factory, page_size=2).run(tenant)
    assert dict(paged.sections) == dict(export.sections)
    for name in SECTIONS:
        rows = export.sections[name]
        stamp = {"nodes": "created_at", "review_tasks": "created_at"}.get(name)
        if stamp is not None:
            keys = [(row[stamp], row["id"]) for row in rows]
            assert keys == sorted(keys), name

    other_export = ExportTenantData(factory).run(other)
    assert len(other_export.sections["nodes"]) == 5
    assert all(node["name"].startswith("Example Other") for node in other_export.sections["nodes"])
    assert ExportTenantData(factory).run(TenantId.new()).sections == {name: [] for name in SECTIONS}
