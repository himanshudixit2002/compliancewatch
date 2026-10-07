"""Migration 0001 on Postgres: the tables, the unit of work with the outbox, the use cases end to
end as the eval service's own role (``cw_eval`` as infra/dev/postgres/roles.sql makes it, not a
superuser), and a downgrade back to nothing. Needs Docker."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer

from eval_service.application.queries import GetEvalRun, ListEvalRuns, RunQuery
from eval_service.application.run_eval import RunEvalSuite
from eval_service.domain.errors import EvalHarnessError
from eval_service.domain.model import Profile, Suite
from eval_service.infrastructure.repository import PostgresUnitOfWorkFactory
from eval_service.testing import ScriptedRunner, TickingClock, gate
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "eval"
TABLES = {"eval_run", "eval_gate_result", "outbox_event", "processed_event", "alembic_version"}
RECALL = "relations.relation_recall[scripted]"
PARSE = "relations.relation_parse_rate[fake]"


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
def role_engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    apply_roles(database_url)
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def test_migration_creates_the_tables_without_tenant_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(inspector.get_table_names(schema=SCHEMA)) == TABLES
    for table in ("eval_run", "eval_gate_result"):
        columns = {column["name"] for column in inspector.get_columns(table, schema=SCHEMA)}
        assert "tenant_id" not in columns, "eval runs are platform data"


def test_runs_are_stored_with_drift_and_published_through_the_outbox(
    engine: Engine, role_engine: Engine
) -> None:
    factory = PostgresUnitOfWorkFactory(role_engine)
    runner = ScriptedRunner(
        [gate(RECALL, 1.0), gate(PARSE, 1.0)], [gate(RECALL, 0.75), gate(PARSE, None)]
    )
    run_suite = RunEvalSuite(factory, runner, clock=TickingClock())
    first = run_suite.run(Suite.RELATIONS, Profile.CI)
    second = run_suite.run(Suite.RELATIONS, Profile.CI)
    nightly = run_suite.run(Suite.RELATIONS, Profile.NIGHTLY)

    stored = GetEvalRun(factory).run(second.id)
    assert stored == second
    assert stored.previous_run_id == first.id
    assert [(g.name, g.measurement.value, g.previous_value) for g in stored.gates] == [
        (RECALL, 0.75, 1.0),
        (PARSE, None, 1.0),
    ]
    assert stored.failed_gates == (RECALL, PARSE)
    assert stored.regressed_gates == (RECALL,)
    assert nightly.previous_run_id is None

    list_runs = ListEvalRuns(factory)
    assert list_runs.run(RunQuery()) == [nightly, second, first]
    assert list_runs.run(RunQuery(profile=Profile.CI, limit=1)) == [second]

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT topic, tenant_id, message FROM outbox_event ORDER BY occurred_at")
        ).all()
    assert [(row.topic, row.tenant_id) for row in rows] == [("eval.run.completed", None)] * 3
    assert rows[1].message["payload"]["previous_run_id"] == str(first.id)


def test_a_harness_failure_writes_no_row(engine: Engine, role_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(role_engine)
    with engine.connect() as connection:
        before: int = connection.execute(text("SELECT count(*) FROM eval_run")).scalar_one()
    with pytest.raises(EvalHarnessError):
        RunEvalSuite(factory, ScriptedRunner(failure="boom")).run(Suite.QA, Profile.CI)
    with engine.connect() as connection:
        after: int = connection.execute(text("SELECT count(*) FROM eval_run")).scalar_one()
    assert after == before
    assert factory.ping()


def test_downgrade_removes_everything(engine: Engine, migrated: Config) -> None:
    command.downgrade(migrated, "base")
    try:
        assert set(inspect(engine).get_table_names(schema=SCHEMA)) == {"alembic_version"}
    finally:
        command.upgrade(migrated, "head")
