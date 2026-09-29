"""Migration 0002 on Postgres: the obligation_change table, its append-only trigger, row-level
security through a plain role, and the change row committing or rolling back with the outbox
row. Needs Docker.

The use cases run as a role that owns nothing and is not a superuser: a superuser bypasses
row-level security whatever the table says.
"""

import importlib
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, DecisionId, TenantId, UserId
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import ClosureReason
from obligation.application.audit import record
from obligation.application.changes import (
    ApplyDeadlineChange,
    CloseObligation,
    DeadlineChange,
    WithdrawRule,
)
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.domain.events import RescheduleReason
from obligation.domain.history import ChangeKind, change_from_event
from obligation.infrastructure.models import Base
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.testing import rule

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
TABLE = "obligation_change"
APP_ROLE = "obligation_app"
APP_PASSWORD = "app-role-for-tests"
RESTRICT_VIOLATION = "23001"
AS_OF = date(2026, 9, 28)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
            # Tables the migrations create later, again after a downgrade, reach the role too.
            connection.execute(
                text(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
                )
            )
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
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, engine: Engine) -> Iterator[Engine]:
    engine = create_engine(database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@"))
    yield engine
    engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def function_exists(engine: Engine, name: str) -> bool:
    with engine.connect() as connection:
        found: object = connection.execute(
            text("SELECT to_regprocedure(:name) IS NOT NULL"), {"name": f"{SCHEMA}.{name}()"}
        ).scalar_one()
    return bool(found)


def as_tenant(connection: Connection, tenant: TenantId) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
    )


def count(connection: Connection, sql: str, **params: object) -> int:
    value: int = connection.execute(text(sql), params).scalar_one()
    return value


def sqlstate(error: DBAPIError) -> object:
    return getattr(error.orig, "sqlstate", None)


def materialise(factory: PostgresUnitOfWorkFactory, tenant: TenantId) -> RuleVersionSnapshot:
    """Two open obligations of a fresh monthly rule for ``tenant``; the rule is returned."""
    the_rule = rule()
    request = MaterialiseRequest(tenant, BusinessId.new(), DecisionId.new(), the_rule, AS_OF)
    MaterialiseObligations(factory, window=2).run(request)
    return the_rule


def test_upgrade_downgrade_upgrade(alembic_config: Config, engine: Engine) -> None:
    command.downgrade(alembic_config, "0001")
    assert TABLE not in tables(engine)
    assert not function_exists(engine, "obligation_append_only_erasable")
    command.upgrade(alembic_config, "0002")
    assert TABLE in tables(engine)
    assert function_exists(engine, "obligation_append_only_erasable")
    command.downgrade(alembic_config, "base")
    assert tables(engine) == {"alembic_version"}
    command.upgrade(alembic_config, "head")
    assert TABLE in tables(engine)


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_the_change_log(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table == TABLE

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_the_change_log,
            },
        )
        assert compare_metadata(context, Base.metadata) == []
    columns = {c["name"]: c for c in inspect(engine).get_columns(TABLE, schema=SCHEMA)}
    assert columns["tenant_id"]["nullable"] is False
    indexes = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes(TABLE, SCHEMA)}
    assert indexes["ix_obligation_change_obligation"] == [
        "tenant_id",
        "obligation_id",
        "occurred_at",
    ]


def test_the_catalog_lint_accepts_the_table(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    (change_log,) = [t for t in catalog if t.name == TABLE]
    assert change_log.tenant_id == "not_null"
    assert lint.tenant_table_problems(change_log) == []
    problems = lint.catalog_problems(catalog, lint.load_config())
    assert [p for p in problems if p.startswith(f"{SCHEMA}.")] == []


def test_every_event_writes_one_change_row_under_row_level_security(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    the_rule = materialise(factory, tenant)
    ApplyDeadlineChange(factory).run(
        DeadlineChange(
            tenant,
            the_rule.rule_version_id,
            "2026-09",
            date(2026, 10, 25),
            RescheduleReason.DEADLINE_EXTENDED,
        )
    )
    with factory(tenant) as uow:
        september, october = uow.obligations.open_for_rule_version(the_rule.rule_version_id)
    user = UserId.new()
    CloseObligation(factory).run(tenant, september.id, ClosureReason.COMPLETED, by=user)
    WithdrawRule(factory).run(tenant, the_rule.rule_version_id)
    WithdrawRule(factory).run(tenant, the_rule.rule_version_id)

    with factory(tenant) as uow:
        history = uow.history.for_obligation(september.id)
        assert [c.kind for c in history] == [
            ChangeKind.CREATED,
            ChangeKind.RESCHEDULED,
            ChangeKind.CLOSED,
        ]
        assert history[1].reason == "deadline_extended"
        assert history[1].previous_due_at is not None
        assert history[1].new_due_at is not None
        assert history[1].previous_due_at < history[1].new_due_at
        assert (history[2].reason, history[2].actor) == ("completed", user)
        assert [c.reason for c in uow.history.for_obligation(october.id)] == [
            "",
            "rule_withdrawn",
        ]
    with factory(other) as uow:
        assert uow.history.for_obligation(september.id) == []

    with app_engine.begin() as connection:
        assert count(connection, f"SELECT count(*) FROM {TABLE}") == 0, "no tenant, no rows"
        as_tenant(connection, tenant)
        change_ids: set[UUID] = set(connection.execute(text(f"SELECT id FROM {TABLE}")).scalars())
        outbox_ids: set[UUID] = set(
            connection.execute(
                text("SELECT id FROM outbox_event WHERE tenant_id = :tenant"),
                {"tenant": tenant.value},
            ).scalars()
        )
    assert len(change_ids) == 5, "2 created, 1 rescheduled, 2 closed; the second withdraw adds none"
    assert change_ids == outbox_ids


def test_update_and_delete_are_refused_outside_an_erasure(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant = TenantId.new()
    materialise(factory, tenant)
    for statement in (f"UPDATE {TABLE} SET reason = 'manual'", f"DELETE FROM {TABLE}"):
        with app_engine.begin() as connection:
            as_tenant(connection, tenant)
            with pytest.raises(DBAPIError, match="obligation_change is append-only") as refused:
                connection.execute(text(statement))
        assert sqlstate(refused.value) == RESTRICT_VIOLATION

    with app_engine.connect() as connection, connection.begin() as transaction:
        as_tenant(connection, tenant)
        connection.execute(text("SELECT set_config('app.erasure', 'on', true)"))
        with pytest.raises(DBAPIError, match="append-only"), connection.begin_nested():
            connection.execute(text(f"UPDATE {TABLE} SET reason = 'manual'"))
        deleted = connection.execute(text(f"DELETE FROM {TABLE}")).rowcount
        assert deleted == 2, "an erasure may delete the tenant's rows"
        transaction.rollback()
    with app_engine.begin() as connection:
        as_tenant(connection, tenant)
        assert count(connection, f"SELECT count(*) FROM {TABLE}") == 2


def test_the_change_row_and_the_outbox_row_commit_or_roll_back_together(
    app_engine: Engine,
) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant = TenantId.new()
    the_rule = materialise(factory, tenant)

    def totals() -> tuple[int, int]:
        with app_engine.begin() as connection:
            as_tenant(connection, tenant)
            changes = count(connection, f"SELECT count(*) FROM {TABLE}")
            outbox = count(
                connection,
                "SELECT count(*) FROM outbox_event WHERE tenant_id = :tenant",
                tenant=tenant.value,
            )
        return changes, outbox

    assert totals() == (2, 2)

    with pytest.raises(RuntimeError, match="boom"):
        close_first(factory, tenant, the_rule, then_fail=True)
    assert totals() == (2, 2), "a failure after both writes leaves neither"

    with pytest.raises(ProgrammingError, match="row-level security"):
        close_first(factory, tenant, the_rule, foreign_change=True)
    assert totals() == (2, 2), "a refused change row takes the outbox row with it"
    with factory(tenant) as uow:
        assert len(uow.obligations.open_for_rule_version(the_rule.rule_version_id)) == 2

    close_first(factory, tenant, the_rule)
    assert totals() == (3, 3)


def close_first(
    factory: PostgresUnitOfWorkFactory,
    tenant: TenantId,
    the_rule: RuleVersionSnapshot,
    *,
    then_fail: bool = False,
    foreign_change: bool = False,
) -> None:
    """Close the rule's first open obligation in one unit of work. ``then_fail`` raises after
    both writes; ``foreign_change`` writes the outbox row, then a change row of another tenant,
    which the row-level security policy refuses."""
    with factory(tenant) as uow:
        obligation = uow.obligations.open_for_rule_version(the_rule.rule_version_id)[0]
        done, event = obligation.close(ClosureReason.COMPLETED, at=utc_now())
        uow.obligations.save(done)
        if foreign_change:
            uow.events.publish(event)
            uow.history.append(replace(change_from_event(event, done), tenant_id=TenantId.new()))
        else:
            record(uow, event, done)
        if then_fail:
            raise RuntimeError("boom")
