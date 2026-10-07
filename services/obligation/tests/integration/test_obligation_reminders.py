"""Migration 0003 on Postgres: the reminder record and the tenant directory under row-level
security through obligation's own role, the open-due query, the reminder sweep publishing
through the outbox once per threshold, and the decision consumer committing with its inbox row.
Needs Docker.

The use cases run as cw_obligation, as infra/dev/postgres/roles.sql makes it: it owns nothing and
is not a superuser, and a superuser bypasses row-level security whatever the table says.
"""

import importlib
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, TenantId
from domain_kernel.status import ClosureReason
from obligation import worker
from obligation.application.changes import CloseObligation
from obligation.application.decisions import ApplyDecision
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.application.reminders import SendDueReminders
from obligation.infrastructure.models import Base
from obligation.infrastructure.repository import PostgresTenantDirectory, PostgresUnitOfWorkFactory
from obligation.testing import FakeRuleVersionReader, rule
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer

SERVICE_DIR = Path(__file__).resolve().parents[2]
EXAMPLES = SERVICE_DIR.parents[1] / "packages" / "contracts" / "events" / "examples"
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
REMINDER = "obligation_reminder"
DIRECTORY = "obligation_tenant"
AS_OF = date(2026, 10, 1)


def at(day: int, hour: int = 10) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            # audit.event, which identity's migrations make: every change writes its entry.
            install_audit_table(connection)
        admin.dispose()
        # The service's own role, as a fresh dev volume has it before the migrations:
        # the tables they create, again after a downgrade, reach it too.
        apply_roles(base_url)
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
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def as_tenant(connection: Connection, tenant: TenantId) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
    )


def execute_as(engine: Engine, tenant: TenantId, sql: str, **params: object) -> None:
    """``sql`` in a transaction of its own under ``tenant``'s setting."""
    with engine.begin() as connection:
        as_tenant(connection, tenant)
        connection.execute(text(sql), params)


def one_off(factory: PostgresUnitOfWorkFactory, tenant: TenantId, due_in_days: int) -> ObligationId:
    """One open obligation of a fresh one-off rule for ``tenant``, due ``due_in_days`` after
    AS_OF (the end of that day in India)."""
    request = MaterialiseRequest(
        tenant,
        BusinessId.new(),
        DecisionId.new(),
        rule(recurrence=None, due_in_days=due_in_days),
        AS_OF,
    )
    (created,) = MaterialiseObligations(factory).run(request).created
    return created


def test_upgrade_downgrade_upgrade(alembic_config: Config, engine: Engine) -> None:
    command.downgrade(alembic_config, "0002")
    assert not {REMINDER, DIRECTORY} & tables(engine)
    command.upgrade(alembic_config, "head")
    assert {REMINDER, DIRECTORY} <= tables(engine)


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_the_new_tables(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table in {REMINDER, DIRECTORY}

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_the_new_tables,
            },
        )
        assert compare_metadata(context, Base.metadata) == []


def test_the_catalog_lint_accepts_the_tables(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    (reminders,) = [t for t in catalog if t.name == REMINDER]
    (directory,) = [t for t in catalog if t.name == DIRECTORY]
    assert lint.tenant_table_problems(reminders) == []
    assert lint.routing_directory_problems(directory) == []
    problems = lint.catalog_problems(catalog, lint.load_config())
    assert [p for p in problems if p.startswith(f"{SCHEMA}.")] == []


def test_open_due_between_sees_the_tenants_open_obligations_in_the_window(
    app_engine: Engine,
) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    soon = one_off(factory, tenant, 5)
    later = one_off(factory, tenant, 20)
    done = one_off(factory, tenant, 3)
    one_off(factory, other, 5)
    CloseObligation(factory).run(tenant, done, ClosureReason.COMPLETED)

    with factory(tenant) as uow:
        found = uow.obligations.open_due_between(at(1), at(14))
        everything = uow.obligations.open_due_between(at(1), at(31))
    assert [o.id for o in found] == [soon]
    assert [o.id for o in everything] == [soon, later]


def test_the_tenant_directory_is_read_across_tenants_and_written_per_tenant(
    app_engine: Engine,
) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    one_off(factory, tenant, 5)
    one_off(factory, tenant, 6)
    one_off(factory, other, 5)
    listed = PostgresTenantDirectory(app_engine).tenants()
    assert {tenant, other} <= set(listed)
    assert len(listed) == len(set(listed))

    with pytest.raises(ProgrammingError, match="row-level security"):
        execute_as(
            app_engine, tenant, f"INSERT INTO {DIRECTORY} (tenant_id) VALUES (:id)", id=uuid4()
        )
    with app_engine.begin() as connection:
        as_tenant(connection, tenant)
        deleted = connection.execute(
            text(f"DELETE FROM {DIRECTORY} WHERE tenant_id = :id"), {"id": other.value}
        ).rowcount
    assert deleted == 0, "a tenant cannot remove another tenant's entry"
    assert other in PostgresTenantDirectory(app_engine).tenants()


def test_the_sweep_publishes_each_reminder_once_through_the_outbox(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    mine = one_off(factory, tenant, 10)
    theirs = one_off(factory, other, 10)
    now = at(5)
    sweep = SendDueReminders(factory, PostgresTenantDirectory(app_engine), clock=lambda: now)

    first = sweep.run()
    assert {mine, theirs} <= set(first.reminded)
    assert first.failed == ()
    assert not {mine, theirs} & set(sweep.run().reminded), "a repeated sweep sends nothing"
    now = at(8)
    assert {mine, theirs} <= set(sweep.run().reminded), "the 3-day threshold"

    with app_engine.begin() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {REMINDER}")).scalar_one() == 0
        as_tenant(connection, tenant)
        rows = connection.execute(
            text(
                f"SELECT id, threshold_days, reminder_index FROM {REMINDER} "
                "WHERE obligation_id = :id ORDER BY reminder_index"
            ),
            {"id": mine.value},
        ).all()
        messages: dict[UUID, dict[str, Any]] = {
            row.id: row.message
            for row in connection.execute(
                text(
                    "SELECT id, message FROM outbox_event "
                    "WHERE topic = 'obligation.due_soon' AND tenant_id = :tenant"
                ),
                {"tenant": tenant.value},
            )
        }
    assert [(r.threshold_days, r.reminder_index) for r in rows] == [(7, 1), (3, 2)]
    assert {r.id for r in rows} == set(messages)
    payloads = sorted((m["payload"] for m in messages.values()), key=lambda p: p["reminder_index"])
    assert [(p["days_left"], p["reminder_index"]) for p in payloads] == [(6, 1), (3, 2)]
    assert {p["obligation_id"] for p in payloads} == {str(mine)}

    with pytest.raises(IntegrityError, match="uq_obligation_reminder_threshold"):
        execute_as(
            app_engine,
            tenant,
            f"INSERT INTO {REMINDER} (id, tenant_id, obligation_id, due_at, threshold_days, "
            "reminder_index, sent_at) SELECT :id, tenant_id, obligation_id, due_at, "
            f"threshold_days, 9, sent_at FROM {REMINDER} WHERE obligation_id = :obligation "
            "LIMIT 1",
            id=uuid4(),
            obligation=mine.value,
        )


def record(name: str, offset: int = 0, **payload: object) -> InboundRecord:
    data = json.loads(
        (EXAMPLES / "applicability.decided" / f"{name}.json").read_text(encoding="utf-8")
    )
    data["payload"].update(payload)
    data["event_id"] = str(uuid4())
    return InboundRecord(
        topic="applicability.decided",
        partition=0,
        offset=offset,
        key=b"k",
        value=json.dumps(data).encode(),
    )


async def test_the_decision_consumer_commits_with_its_inbox_row(app_engine: Engine) -> None:
    golden = json.loads(
        (EXAMPLES / "applicability.decided" / "applies-after-rule-published.json").read_text(
            encoding="utf-8"
        )
    )
    tenant = TenantId(UUID(golden["tenant_id"]))
    the_rule = replace(
        rule(), rule_version_id=RuleVersionId(UUID(golden["payload"]["rule_version_id"]))
    )
    rules = FakeRuleVersionReader([the_rule])
    producer = FakeProducer()
    consumer = IdempotentConsumer(
        group_id=worker.GROUP_ID,
        store=read_first_store(app_engine, worker.GROUP_ID),
        handler=worker.decision_handler(ApplyDecision(rules)),
        producer=producer,
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )

    def counts() -> tuple[int, int, int]:
        with app_engine.begin() as connection:
            as_tenant(connection, tenant)
            obligations: int = connection.execute(
                text("SELECT count(*) FROM obligation")
            ).scalar_one()
            outbox: int = connection.execute(
                text("SELECT count(*) FROM outbox_event WHERE tenant_id = :t"),
                {"t": tenant.value},
            ).scalar_one()
            processed: int = connection.execute(
                text("SELECT count(*) FROM processed_event WHERE consumer_group = :g"),
                {"g": worker.GROUP_ID},
            ).scalar_one()
        return obligations, outbox, processed

    applies = record("applies-after-rule-published")
    assert await consumer.process(applies) is Outcome.PROCESSED
    assert counts() == (3, 3, 1), "September, still due on 1 October, October and November"
    assert tenant in PostgresTenantDirectory(app_engine).tenants()
    assert await consumer.process(applies) is Outcome.SKIPPED
    assert counts() == (3, 3, 1)

    flipped = record("applies-after-rule-published", offset=1, result="not_applicable")
    assert await consumer.process(flipped) is Outcome.PROCESSED
    assert counts() == (3, 6, 2), "three obligation.closed rows with the inbox row"

    rules.down = True
    other_rule = record("applies-after-rule-published", offset=2, decision_id=str(uuid4()))
    assert await consumer.process(other_rule) is Outcome.DEAD
    assert counts()[:2] == (3, 6), "a failed decision leaves nothing behind"


def test_a_unit_on_a_connection_begins_a_transaction_its_owner_ends(app_engine: Engine) -> None:
    tenant = TenantId.new()
    with app_engine.connect() as connection:
        units = PostgresUnitOfWorkFactory.on_connection(connection)
        assert not connection.in_transaction()
        with units(tenant) as uow:
            assert uow.obligations.open_due_between(at(1), at(31)) == []
        assert connection.in_transaction(), "the unit leaves the transaction to its owner"
        connection.rollback()
