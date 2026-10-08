"""Obligation's erasure on Postgres, as its own role cw_obligation under forced row-level
security: the append-only changes and comments go only inside an erasure, the tenant's rows go
in the order of the foreign keys and another tenant's stay, and the catalog shows every table of
the schema with a tenant column erased or retained with a reason. A decision that arrives after
the erasure writes nothing: the consumer finds the erased marker under the erasure's lock.
Needs Docker."""

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.erasure import DeletionRequest
from domain_kernel.ids import CorrelationId, EventId, RuleVersionId, TenantId
from obligation import worker
from obligation.application.decisions import ApplyDecision
from obligation.infrastructure.erasure import TABLES, PostgresObligationEraser
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.testing import FakeRuleVersionReader, rule, tenant_records
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.erasure import count_rows, erase_and_record
from py_common.erasure_testing import assert_nothing_left
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
NOW = datetime(2000, 1, 5, 4, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
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
        yield database_url


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
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


def test_the_tenant_s_obligations_go_and_another_s_stay(engine: Engine, database_url: str) -> None:
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

    owner = create_engine(database_url)
    with owner.connect() as connection:
        retained = assert_nothing_left(connection, SCHEMA, tenant, answer)
    owner.dispose()
    assert retained == {"erased_tenant.tenant_id": 1, "outbox_event.tenant_id": 1}


EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
DECIDED = "applicability.decided"
EXAMPLE_TENANT = TenantId(UUID("5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a"))
EXAMPLE_RULE = RuleVersionId(UUID("4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b"))


async def test_a_decision_after_the_erasure_writes_nothing(engine: Engine) -> None:
    with engine.begin() as connection:
        erase_and_record(
            "obligation",
            PostgresObligationEraser(connection),
            deletion(EXAMPLE_TENANT),
            clock=lambda: NOW,
        )
    reader = FakeRuleVersionReader([replace(rule(), rule_version_id=EXAMPLE_RULE)])
    handler = worker.decision_handler(ApplyDecision(reader, clock=lambda: NOW))
    consumer = IdempotentConsumer(
        group_id=worker.GROUP_ID,
        store=read_first_store(engine, worker.GROUP_ID),
        handler=handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    data = json.loads((EXAMPLES / DECIDED / "applies-after-rule-published.json").read_text())
    data["event_id"] = str(uuid4())
    record = InboundRecord(
        topic=DECIDED, partition=0, offset=0, key=b"k", value=json.dumps(data).encode()
    )
    assert await consumer.process(record) is Outcome.PROCESSED
    assert counts(engine, EXAMPLE_TENANT) == dict.fromkeys(TABLES, 0), "nothing came back"
    with engine.begin() as connection:
        marked = connection.execute(
            text("SELECT count(*) FROM processed_event WHERE consumer_group = :g"),
            {"g": worker.GROUP_ID},
        ).scalar_one()
    assert marked == 1, "the decision is marked processed"
