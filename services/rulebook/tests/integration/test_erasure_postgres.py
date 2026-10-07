"""The rulebook's erasure on Postgres, as its own role cw_rulebook: it deletes nothing, and its
answer (tenant.data.erased of the tenant) and audit entry commit on the consumer's connection
under the tenant's setting. Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.erasure import DeletionRequest
from domain_kernel.ids import CorrelationId, EventId, TenantId
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.erasure import erase_and_record
from rulebook.infrastructure.erasure import PostgresRulebookEraser

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
NOW = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        with admin.begin() as connection:
            install_audit_table(connection)
        admin.dispose()
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        apply_roles(url)
        engine = create_engine(as_role(url, SCHEMA))
        yield engine
        engine.dispose()


def test_the_rulebook_answers_with_what_it_keeps(engine: Engine) -> None:
    tenant = TenantId.new()
    request = DeletionRequest(
        event_id=EventId.new(),
        tenant_id=tenant,
        correlation_id=CorrelationId.new(),
        requested_at=NOW,
        deadline_at=NOW + timedelta(days=30),
    )
    with engine.begin() as connection:
        answer = erase_and_record(
            "rulebook", PostgresRulebookEraser(connection), request, clock=lambda: NOW
        )
    assert dict(answer.tables) == {}
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT message->'payload'->>'service' FROM outbox_event "
                "WHERE tenant_id = :t AND topic = 'tenant.data.erased'"
            ),
            {"t": tenant.value},
        ).scalars()
        assert list(rows) == ["rulebook"]
