"""Profile's erasure on Postgres, as its own role cw_profile under forced row-level security:
the tenant's rows go in the order of the foreign keys, another tenant's stay, and the answer, its
audit entry and the erased marker commit with the erasure (the role inserts audit rows; it reads
none). The catalog then shows that every table of the schema with a tenant column is erased or
retained with a reason, and holds no row of the tenant unless retained. Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.erasure import DeletionRequest
from domain_kernel.ids import CorrelationId, EventId, TenantId
from profile_service.application.attributes import SetAttributes
from profile_service.application.registration import RegisterNodes
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange, ValueState
from profile_service.infrastructure.erasure import TABLES, PostgresProfileEraser
from profile_service.infrastructure.repository import PostgresUnitOfWorkFactory
from profile_service.testing import GSTIN_KARNATAKA
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.erasure import ConnectionErasedTenants, count_rows, erase_and_record
from py_common.erasure_testing import assert_nothing_left

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "profile"
NOW = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
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
        yield database_url


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def stocked(factory: PostgresUnitOfWorkFactory, tenant: TenantId, name: str) -> None:
    register = RegisterNodes(factory, clock=lambda: NOW)
    registered = register.registration(
        tenant, GSTIN_KARNATAKA, f"{name} Bengaluru", entity_name=name
    )
    entity = registered.node.parent_id
    assert entity is not None
    SetAttributes(factory, ontology_package.load(), clock=lambda: NOW).run(
        tenant,
        entity,
        [
            AttributeChange("state_codes", ["29"]),
            AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE),
        ],
        source=ChangeSource.USER_INPUT,
    )


def counts(engine: Engine, tenant: TenantId) -> dict[str, int]:
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        return {table: count_rows(connection, table, tenant) for table in TABLES}


def test_the_tenant_s_profile_goes_and_another_s_stays(engine: Engine, database_url: str) -> None:
    factory = PostgresUnitOfWorkFactory(engine)
    tenant, other = TenantId.new(), TenantId.new()
    stocked(factory, tenant, "Example Traders")
    stocked(factory, other, "Example Other")
    before = counts(engine, tenant)
    assert before["profile_node"] == 2
    assert before["profile_attribute"] > 0
    assert before["review_task"] == 1
    request = DeletionRequest(
        event_id=EventId.new(),
        tenant_id=tenant,
        correlation_id=CorrelationId.new(),
        requested_at=NOW,
        deadline_at=NOW + timedelta(days=30),
    )
    with engine.begin() as connection:
        answer = erase_and_record(
            "profile", PostgresProfileEraser(connection), request, clock=lambda: NOW
        )
    assert {table: answer.tables[table] for table in TABLES} == before
    assert counts(engine, tenant) == dict.fromkeys(TABLES, 0)
    assert counts(engine, other) == before, "another tenant's profile stays"
    with engine.begin() as connection:
        topics = connection.execute(
            text("SELECT topic FROM outbox_event WHERE tenant_id = :t"), {"t": tenant.value}
        ).scalars()
        assert "tenant.data.erased" in list(topics)

    owner = create_engine(database_url)
    with owner.connect() as connection:
        retained = assert_nothing_left(connection, SCHEMA, tenant, answer)
    owner.dispose()
    assert retained["erased_tenant.tenant_id"] == 1, "the marker"
    assert retained["outbox_event.tenant_id"] >= 1, "the answer waits for the relay"
    with engine.begin() as connection:
        assert ConnectionErasedTenants(connection).is_erased(tenant)
        assert not ConnectionErasedTenants(connection).is_erased(other)
    with engine.begin() as connection:
        again = erase_and_record(
            "profile", PostgresProfileEraser(connection), request, clock=lambda: NOW
        )
    assert sum(again.tables.values()) == 0, "run again it finds nothing"
