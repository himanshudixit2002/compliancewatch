"""Migration 0003 and the business API on Postgres through the profile's own role, cw_profile as
infra/dev/postgres/roles.sql makes it, so the forced row-level security applies: the
idempotency_key table and its policies, the business list paged by (name, id) per tenant, an
update that rolls back as a whole, and a replayed create. Needs Docker."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.errors import InvalidAttributeValueError
from domain_kernel.identifiers import Pan
from domain_kernel.ids import TenantId
from profile_service.application.businesses import (
    Answer,
    CreateBusiness,
    ListBusinesses,
    UpdateBusiness,
)
from profile_service.application.prefill import PrefillFromGstin
from profile_service.domain.errors import ProfileNodeNotFoundError
from profile_service.domain.model import AttributeChange
from profile_service.infrastructure.lookup import ManualLookupProvider
from profile_service.infrastructure.repository import PostgresUnitOfWorkFactory
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import GSTIN_DELHI, GSTIN_KARNATAKA, FixedFlags
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "profile"
NAME_INDEX = "ix_profile_node_tenant_level_name"
PANS = ("AAAAA1111A", "BBBBB2222B", "CCCCC3333C", "DDDDD4444D")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def migrated(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        config = Config(str(SERVICE_DIR / "alembic.ini"))
        command.upgrade(config, "head")
        yield config


@pytest.fixture(scope="module")
def engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_url(database_url: str, migrated: Config) -> str:
    apply_roles(database_url)
    return as_role(database_url, SCHEMA)


@pytest.fixture(scope="module")
def factory(app_url: str) -> Iterator[PostgresUnitOfWorkFactory]:
    factory = PostgresUnitOfWorkFactory.from_url(app_url)
    yield factory
    factory.engine.dispose()


def catalog(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        policies: list[str] = sorted(
            connection.execute(
                text(
                    "SELECT policyname FROM pg_policies WHERE schemaname = :s "
                    "AND tablename = 'idempotency_key'"
                ),
                {"s": SCHEMA},
            ).scalars()
        )
        forced = connection.execute(
            text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = 'idempotency_key'"
            ),
            {"s": SCHEMA},
        ).scalar()
    inspector = inspect(engine)
    return {
        "tables": set(inspector.get_table_names(schema=SCHEMA)),
        "indexes": {
            index["name"]: index["column_names"]
            for index in inspector.get_indexes("profile_node", schema=SCHEMA)
        },
        "policies": policies,
        "forced": forced,
    }


def test_migration_0003_adds_the_idempotency_table_and_the_name_index(engine: Engine) -> None:
    found = catalog(engine)
    assert "idempotency_key" in found["tables"]
    assert found["indexes"][NAME_INDEX] == ["tenant_id", "level", "name", "id"]
    assert found["policies"] == [
        "idempotency_key_purge_expired",
        "idempotency_key_tenant_isolation",
    ]
    assert found["forced"] is True


def test_migration_0003_goes_down_and_up_again(migrated: Config, engine: Engine) -> None:
    command.downgrade(migrated, "0002")
    down = catalog(engine)
    assert "idempotency_key" not in down["tables"]
    assert NAME_INDEX not in down["indexes"]
    command.upgrade(migrated, "head")
    assert catalog(engine)["indexes"][NAME_INDEX] == ["tenant_id", "level", "name", "id"]


def use_cases(
    factory: PostgresUnitOfWorkFactory,
) -> tuple[CreateBusiness, UpdateBusiness, ListBusinesses]:
    ontology = ontology_package.load()
    prefill = PrefillFromGstin(factory, ManualLookupProvider(), ontology, FixedFlags())
    return (
        CreateBusiness(factory, ontology, prefill),
        UpdateBusiness(factory, ontology),
        ListBusinesses(factory),
    )


def test_the_list_pages_by_name_within_the_tenant(factory: PostgresUnitOfWorkFactory) -> None:
    create, _, businesses = use_cases(factory)
    tenant, other = TenantId.new(), TenantId.new()
    for name, pan in zip(("delta", "Bravo", "alpha", "Charlie"), PANS, strict=True):
        create.run(tenant, name=name, pan=Pan(pan))
    create.run(tenant, name="Echo 100%_", gstin=GSTIN_KARNATAKA)
    create.run(other, name="Aardvark", gstin=GSTIN_DELHI)
    seen: list[str] = []
    after = None
    while True:
        page = businesses.run(tenant, after=after, limit=2)
        seen.extend(business.entity.name for business in page)
        if len(page) < 2:
            break
        after = page[-1].id
    with factory.engine.connect() as connection:
        expected: list[str] = list(
            connection.execute(
                text(
                    "SELECT name FROM (VALUES ('delta'), ('Bravo'), ('alpha'), ('Charlie'), "
                    "('Echo 100%_')) AS v(name) ORDER BY name"
                )
            ).scalars()
        )
    assert seen == expected, "the database's collation orders the names"
    assert [b.entity.name for b in businesses.run(other, limit=10)] == ["Aardvark"]
    with pytest.raises(ProfileNodeNotFoundError):
        businesses.run(other, after=after, limit=2)
    found = businesses.run(tenant, limit=10, query=GSTIN_KARNATAKA.value.lower())
    assert [(b.entity.name, [r.key for r in b.registrations]) for b in found] == [
        ("Echo 100%_", [GSTIN_KARNATAKA.value])
    ]
    assert [b.entity.name for b in businesses.run(tenant, limit=10, query="100%_")] == [
        "Echo 100%_"
    ]
    assert businesses.run(tenant, limit=10, query="0_%") == [], "wildcards match literally"
    assert [b.entity.name for b in businesses.run(tenant, limit=10, query="ddddd")] == ["Charlie"]


def test_an_update_rolls_back_every_node(factory: PostgresUnitOfWorkFactory) -> None:
    create, update, _ = use_cases(factory)
    tenant = TenantId.new()
    business = create.run(tenant, name="Acme", gstin=GSTIN_KARNATAKA).business
    with pytest.raises(InvalidAttributeValueError):
        update.run(
            tenant,
            business.id,
            name="Renamed",
            answers=[
                Answer(AttributeChange("employee_count", 7)),
                Answer(AttributeChange("supply_type", "spaceships")),
            ],
        )
    with factory(tenant) as uow:
        entity = uow.profiles.get(business.id)
    assert entity is not None
    assert (entity.name, entity.version, entity.value("employee_count")) == (
        "Acme",
        business.entity.version,
        None,
    )
    renamed = update.run(
        tenant,
        business.id,
        name="Renamed",
        answers=[Answer(AttributeChange("employee_count", 7))],
    )
    assert (renamed.entity.name, renamed.entity.version) == ("Renamed", entity.version + 2)
    with factory.engine.connect() as connection:
        versions: int = connection.execute(
            text("SELECT count(*) FROM profile_version WHERE node_id = :id"),
            {"id": business.id.value},
        ).scalar_one()
    assert versions == 0, "cw_profile sees no row without a tenant"


def test_a_create_is_replayed_from_postgres(app_url: str) -> None:
    settings = ProfileSettings(
        _env_file=None,
        service_name="profile",
        profile_store="postgres",
        database_url=app_url,
        profile_gstin_lookup="static",
    )
    tenant, other = TenantId.new(), TenantId.new()
    body = {"name": "Acme", "gstin": GSTIN_KARNATAKA.value}
    headers = {"x-tenant-id": str(tenant), "Idempotency-Key": "postgres-key-01"}
    with TestClient(build_app(settings, flags=FixedFlags())) as client:
        first = client.post("/v1/businesses", json=body, headers=headers)
        assert first.status_code == 201, first.text
        retry = client.post("/v1/businesses", json=body, headers=headers)
        assert retry.headers["idempotent-replayed"] == "true"
        assert retry.json() == first.json()
        reused = client.post("/v1/businesses", json={**body, "name": "B"}, headers=headers)
        assert reused.status_code == 422
        as_other = {**headers, "x-tenant-id": str(other)}
        theirs = client.post("/v1/businesses", json=body, headers=as_other)
        assert theirs.status_code == 201, "another tenant's key of the same text is another key"
        assert "idempotent-replayed" not in theirs.headers
        assert theirs.json()["business"]["id"] != first.json()["business"]["id"]
        listed = client.get("/v1/businesses", headers={"x-tenant-id": str(tenant)}).json()
    assert [item["name"] for item in listed["items"]] == ["Acme"]
