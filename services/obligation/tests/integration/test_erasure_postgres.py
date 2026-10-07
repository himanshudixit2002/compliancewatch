"""Obligation's erasure on Postgres, as its own role cw_obligation under forced row-level
security: the append-only changes and comments go only inside an erasure, the tenant's rows go
in the order of the foreign keys and another tenant's stay. Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.erasure import DeletionRequest
from domain_kernel.ids import CorrelationId, EventId, TenantId
from obligation.infrastructure.erasure import TABLES, PostgresObligationEraser
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.testing import tenant_records
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.erasure import count_rows, erase_and_record

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
NOW = datetime(2000, 1, 5, 4, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            install_audit_table(connection)
        admin.dispose()
        database_url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", database_url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        apply_roles(database_url)
        engine = create_engine(as_role(database_url, SCHEMA))
        yield engine
        engine.dispose()


def keep(factory: PostgresUnitOfWorkFactory, tenant: TenantId, count: int) -> None:
    for index in range(count):
        records = tenant_records(tenant, NOW + timedelta(minutes=index))
        with factory(tenant) as uow:
            uow.obligations.add(records.obligation)
            for change in records.changes:
                uow.history.append(change)
            uow.comments.add(records.comment)


def counts(engine: Engine, tenant: TenantId) -> dict[str, int]:
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        return {table: count_rows(connection, table, tenant) for table in TABLES}


def deletion(tenant: TenantId) -> DeletionRequest:
    return DeletionRequest(
        event_id=EventId.new(),
        tenant_id=tenant,
        correlation_id=CorrelationId.new(),
        requested_at=NOW,
        deadline_at=NOW + timedelta(days=30),
    )


def refused_outside_an_erasure(engine: Engine, tenant: TenantId) -> bool:
    try:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
            )
            connection.execute(text("DELETE FROM obligation_change"))
    except DBAPIError:
        return True
    return False


def test_the_tenant_s_obligations_go_and_another_s_stay(engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(engine)
    tenant, other = TenantId.new(), TenantId.new()
    keep(factory, tenant, 3)
    keep(factory, other, 2)
    before, theirs = counts(engine, tenant), counts(engine, other)
    assert (before["obligation"], before["obligation_comment"]) == (3, 3)
    assert before["obligation_tenant"] == 1
    assert refused_outside_an_erasure(engine, tenant), "the changes stay append-only"
    with engine.begin() as connection:
        answer = erase_and_record(
            "obligation", PostgresObligationEraser(connection), deletion(tenant), clock=lambda: NOW
        )
    assert {table: answer.tables[table] for table in TABLES} == before
    assert counts(engine, tenant) == dict.fromkeys(TABLES, 0)
    assert counts(engine, other) == theirs, "another tenant's obligations stay"
    with engine.begin() as connection:
        topics = connection.execute(
            text("SELECT topic FROM outbox_event WHERE tenant_id = :t"), {"t": tenant.value}
        ).scalars()
        assert "tenant.data.erased" in list(topics)
