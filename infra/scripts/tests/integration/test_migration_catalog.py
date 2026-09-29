"""The catalog lint against a real Postgres after every service has migrated. Needs Docker.

The schemas and the vector extension come from infra/dev/postgres/init.sql, and each service's
alembic runs the way ``make migrate`` runs it: the URL carries the search_path and CW_DB_SCHEMA
names the schema that holds alembic_version. The negative cases create their tables inside a
transaction that is rolled back, so they read Postgres's own deparsed policy text without
changing the migrated catalog.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg.rows import TupleRow
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from check_migrations import (
    ROUTING_DIRECTORY,
    Exemption,
    LintConfig,
    catalog_problems,
    libpq_dsn,
    load_config,
    main,
    read_catalog,
    read_tables,
)
from py_common.idempotency.schema import create_idempotency_table

ROOT = Path(__file__).resolve().parents[4]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA_OF_SERVICE = {"applicability-engine": "applicability", "llm-gateway": "llm_gateway"}
TENANT_CHECK = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def dev_schemas() -> list[str]:
    init = (ROOT / "infra" / "dev" / "postgres" / "init.sql").read_text(encoding="utf-8")
    return re.findall(r"CREATE SCHEMA IF NOT EXISTS (\w+);", init)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """A database with every service migrated to head, as the dev stack has after make migrate."""
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        with psycopg.connect(libpq_dsn(url), autocommit=True) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            for schema in dev_schemas():
                connection.execute(f"CREATE SCHEMA {schema}")
        with pytest.MonkeyPatch.context() as env:
            for service in sorted(path.parent for path in ROOT.glob("services/*/alembic.ini")):
                schema = SCHEMA_OF_SERVICE.get(service.name, service.name)
                env.setenv("CW_DATABASE_URL", f"{url}?options=-csearch_path%3D{schema}%2Cpublic")
                env.setenv("CW_DB_SCHEMA", schema)
                command.upgrade(Config(str(service / "alembic.ini")), "head")
        yield url


@pytest.fixture
def connection(database_url: str) -> Iterator[psycopg.Connection[TupleRow]]:
    """A connection whose changes are rolled back at the end of the test."""
    with psycopg.connect(libpq_dsn(database_url)) as connection:
        yield connection
        connection.rollback()


def test_the_migrated_catalog_passes_with_the_seeded_exemptions(database_url: str) -> None:
    tables = read_catalog(database_url)
    names = {table.qualified for table in tables}
    assert {"identity.consent_record", "obligation.obligation", "profile.profile_node"} <= names
    assert {"obligation.outbox_event", "llm_gateway.cost_ledger", "rulebook.document"} <= names
    assert catalog_problems(tables, load_config()) == []


def test_the_cli_prints_the_exemptions_and_passes(
    database_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["catalog", "--dsn", database_url]) == 0
    out = capsys.readouterr().out
    assert "exempt llm_gateway.cost_ledger (1 table): Row-level security is deliberately" in out
    assert "every tenant table has forced row-level security" in out


def problems_after(connection: psycopg.Connection[TupleRow], *sql: str) -> list[str]:
    for statement in sql:
        connection.execute(statement)
    return catalog_problems(read_tables(connection), load_config())


def test_a_tenant_table_without_force_fails(
    connection: psycopg.Connection[TupleRow],
) -> None:
    problems = problems_after(
        connection,
        "CREATE TABLE identity.leak (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        "ALTER TABLE identity.leak ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY leak_isolation ON identity.leak USING ({TENANT_CHECK}) "
        f"WITH CHECK ({TENANT_CHECK})",
    )
    assert problems == [
        "identity.leak: R1: row-level security is not forced, so the table owner bypasses it"
    ]


def test_a_policy_without_nullif_or_with_check_fails(
    connection: psycopg.Connection[TupleRow],
) -> None:
    problems = problems_after(
        connection,
        "CREATE TABLE identity.leak (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        "ALTER TABLE identity.leak ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE identity.leak FORCE ROW LEVEL SECURITY",
        "CREATE POLICY leak_isolation ON identity.leak "
        "USING (tenant_id = current_setting('app.tenant_id')::uuid)",
    )
    assert problems == [
        "identity.leak: R1: policy leak_isolation USING does not compare tenant_id with "
        "NULLIF(current_setting('app.tenant_id', true), '')",
        "identity.leak: R1: policy leak_isolation has USING but no WITH CHECK",
    ]


def test_tenant_schema_rules_read_the_real_catalog(
    connection: psycopg.Connection[TupleRow],
) -> None:
    problems = problems_after(
        connection,
        "CREATE TABLE profile.lookup (id uuid PRIMARY KEY)",
        "CREATE TABLE profile.shared (id uuid PRIMARY KEY, tenant_id uuid)",
    )
    assert problems == [
        "profile.lookup: R2: a table in tenant schema profile has no tenant_id",
        "profile.shared: R3: tenant_id is nullable and the table is not exempt",
    ]


def test_a_routing_directory_reads_across_tenants_but_writes_within_one(
    connection: psycopg.Connection[TupleRow],
) -> None:
    repo = load_config()
    config = LintConfig(
        repo.tenant_schemas,
        repo.global_schemas,
        (
            *repo.exemptions,
            Exemption("applicability.directory", "routes work by business", ROUTING_DIRECTORY),
        ),
    )
    for statement in (
        "CREATE TABLE applicability.directory (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)",
        "ALTER TABLE applicability.directory ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE applicability.directory FORCE ROW LEVEL SECURITY",
        "CREATE POLICY directory_read ON applicability.directory FOR SELECT USING (true)",
        f"CREATE POLICY directory_write ON applicability.directory USING ({TENANT_CHECK}) "
        f"WITH CHECK ({TENANT_CHECK})",
    ):
        connection.execute(statement)
    assert catalog_problems(read_tables(connection), config) == []

    connection.execute(
        "CREATE POLICY directory_backfill ON applicability.directory FOR INSERT WITH CHECK (true)"
    )
    assert catalog_problems(read_tables(connection), config) == [
        "applicability.directory: R1: write policy directory_backfill (FOR INSERT) needs a WITH "
        "CHECK that compares tenant_id with the app.tenant_id setting"
    ]


def test_an_idempotency_table_passes_with_its_purge_policy(database_url: str) -> None:
    """The table ``create_idempotency_table`` makes, read back from the catalog: the tenant
    policy and the extra DELETE policy for expired rows raise no problem."""
    repo = load_config()
    config = LintConfig(repo.tenant_schemas | {"idempotency_lint"}, repo.global_schemas, ())
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("CREATE SCHEMA idempotency_lint"))
            connection.execute(text("SET LOCAL search_path TO idempotency_lint, public"))
            create_idempotency_table(Operations(MigrationContext.configure(connection)))
            driver = connection.connection.driver_connection
            assert isinstance(driver, psycopg.Connection)
            tables = read_tables(driver)
            transaction.rollback()
    finally:
        engine.dispose()
    created = [table for table in tables if table.schema == "idempotency_lint"]
    assert [table.name for table in created] == ["idempotency_key"]
    assert {policy.command for policy in created[0].policies} == {"ALL", "DELETE"}
    assert catalog_problems(created, config) == []
