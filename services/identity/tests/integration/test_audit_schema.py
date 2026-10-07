"""Migrations 0005 to 0007 on Postgres: ``audit.event`` on top of identity's chain, the schema
0005 creates when missing, the read scopes of 0006, the subject index of 0007, the catalog
lint's view of the table, a write and the audit trail's reads through a plain role, and the
downgrades. Needs Docker.

The role owns nothing and is not a superuser, and is granted what ``make product-role`` grants
``cw_app`` (infra/dev/postgres/50-app-role.sql). The policies, the trigger and the writer in the
transaction of an action are tested in packages/py-common/tests/integration/test_audit_postgres.py.
"""

import importlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.audit import AuditActor
from domain_kernel.ids import TenantId
from identity.domain.audit import AuditKey, AuditQuery, AuditScope
from identity.infrastructure.audit_reader import PostgresAuditReader
from py_common.audit.schema import AUDIT_SCHEMA, AUDIT_TABLE, audit_event, metadata
from py_common.audit.testing import audit_entry, read_audit_entries
from py_common.audit.writer import PostgresAuditSink

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "identity"
APP_ROLE = "identity_audit_app"
APP_PASSWORD = "app-role-for-tests"
PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """A database with the identity schema only: the migration has to make ``audit`` itself, as
    it does outside the dev stack."""
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def alembic_config(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        yield Config(str(SERVICE_DIR / "alembic.ini"))


@pytest.fixture(scope="module")
def engine(database_url: str, alembic_config: Config) -> Iterator[Engine]:
    command.upgrade(alembic_config, "head")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        # What 50-app-role.sql grants on every service schema, audit among them, run after
        # make migrate; the default privileges reach a table a later migration makes again.
        connection.execute(text(f"GRANT USAGE ON SCHEMA {AUDIT_SCHEMA} TO {APP_ROLE}"))
        connection.execute(
            text(f"GRANT {PRIVILEGES} ON ALL TABLES IN SCHEMA {AUDIT_SCHEMA} TO {APP_ROLE}")
        )
        connection.execute(
            text(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {AUDIT_SCHEMA} "
                f"GRANT {PRIVILEGES} ON TABLES TO {APP_ROLE}"
            )
        )
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, engine: Engine) -> Iterator[Engine]:
    engine = create_engine(database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@"))
    yield engine
    engine.dispose()


def audit_tables(engine: Engine) -> list[str]:
    return sorted(inspect(engine).get_table_names(schema=AUDIT_SCHEMA))


def test_the_migration_creates_the_schema_and_the_table(engine: Engine) -> None:
    assert audit_tables(engine) == [AUDIT_TABLE]
    found = inspect(engine)
    columns = {column["name"]: column for column in found.get_columns(AUDIT_TABLE, AUDIT_SCHEMA)}
    assert list(columns) == [column.name for column in audit_event.columns]
    assert columns["tenant_id"]["nullable"] is True
    assert {index["name"] for index in found.get_indexes(AUDIT_TABLE, AUDIT_SCHEMA)} == {
        "ix_audit_event_tenant_time",
        "ix_audit_event_action_time",
        "ix_audit_event_subject_time",
    }
    with engine.connect() as connection:
        version: str = connection.execute(
            text(f"SELECT version_num FROM {SCHEMA}.alembic_version")
        ).scalar_one()
    assert version == "0007"


def test_the_table_and_py_common_agree(engine: Engine) -> None:
    def only_audit(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = obj if type_ == "table" else getattr(obj, "table", None)
        return getattr(table, "schema", None) == AUDIT_SCHEMA

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_schemas": True,
                "include_object": only_audit,
            },
        )
        assert compare_metadata(context, metadata) == []


def test_the_catalog_lint_accepts_the_table(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    config = lint.load_config()
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == AUDIT_SCHEMA]
    (table,) = catalog
    assert (table.tenant_id, table.row_security, table.force_row_security) == (
        "nullable",
        True,
        True,
    )
    exemption = config.exemption_for(table.qualified)
    assert exemption is not None
    assert exemption.kind == "exempt"
    for policy in ("event_platform_insert", "event_platform_read", "event_export_read"):
        assert policy in exemption.reason, policy
    problems = lint.catalog_problems(catalog, config)
    assert [p for p in problems if p.startswith(f"{AUDIT_SCHEMA}.")] == []


def test_a_plain_role_writes_an_entry_of_its_tenant(app_engine: Engine) -> None:
    tenant = TenantId.new()
    entry = audit_entry(
        tenant_id=tenant, actor=AuditActor.system("identity"), correlation_id="request-1"
    )
    with app_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
        )
        PostgresAuditSink(connection).write(entry)
        assert read_audit_entries(connection) == [entry]
    with app_engine.connect() as connection:
        assert read_audit_entries(connection) == [], "no tenant setting reads nothing"


def test_the_trail_reads_each_scope_through_the_plain_role(app_engine: Engine) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    at = datetime(2000, 1, 3, 9, 0, tzinfo=UTC)
    mine = [
        audit_entry(tenant_id=tenant, occurred_at=at + timedelta(minutes=index))
        for index in range(3)
    ]
    theirs = audit_entry(tenant_id=other, occurred_at=at)
    platform = audit_entry(tenant_id=None, occurred_at=at + timedelta(minutes=10))
    for owner, entries in ((tenant, [*mine, platform]), (other, [theirs])):
        with app_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(owner)}
            )
            for entry in entries:
                PostgresAuditSink(connection).write(entry)
    reader = PostgresAuditReader(app_engine)

    first = reader.page(AuditScope.TENANT, tenant, AuditQuery(limit=2))
    assert first == [mine[2], mine[1], mine[0]], "limit + 1, newest first"
    rest = reader.page(AuditScope.TENANT, tenant, AuditQuery(limit=2, after=AuditKey.of(mine[1])))
    assert rest == [mine[0]]
    regulatory = reader.page(AuditScope.REGULATORY, tenant, AuditQuery(limit=10))
    assert set(regulatory) == {*mine, platform}
    assert reader.page(AuditScope.REGULATORY, None, AuditQuery(limit=10)) == [platform]
    assert reader.page(AuditScope.TENANT, other, AuditQuery(limit=10)) == [theirs]
    exported = list(reader.export(at, at + timedelta(hours=1)))
    assert exported == sorted(
        [*mine, theirs, platform], key=lambda e: (e.occurred_at, str(e.entry_id))
    )


def test_downgrade_drops_the_index_the_read_scopes_then_the_table_and_keeps_the_schema(
    alembic_config: Config, engine: Engine
) -> None:
    command.downgrade(alembic_config, "0006")
    assert {index["name"] for index in inspect(engine).get_indexes(AUDIT_TABLE, AUDIT_SCHEMA)} == {
        "ix_audit_event_tenant_time",
        "ix_audit_event_action_time",
    }
    command.downgrade(alembic_config, "0005")
    with engine.connect() as connection:
        policies = set(
            connection.execute(
                text("SELECT policyname FROM pg_policies WHERE schemaname = 'audit'")
            ).scalars()
        )
    assert policies == {"event_tenant_isolation", "event_platform_insert"}
    command.downgrade(alembic_config, "0004")
    assert audit_tables(engine) == []
    with engine.connect() as connection:
        kept: int = connection.execute(
            text("SELECT count(*) FROM pg_namespace WHERE nspname = :schema"),
            {"schema": AUDIT_SCHEMA},
        ).scalar_one()
        function: bool = connection.execute(
            text("SELECT to_regprocedure('audit.audit_append_only()') IS NOT NULL")
        ).scalar_one()
    assert (kept, function) == (1, False)
    command.upgrade(alembic_config, "head")
    assert audit_tables(engine) == [AUDIT_TABLE]
