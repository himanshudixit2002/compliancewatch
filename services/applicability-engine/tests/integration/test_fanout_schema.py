"""Migration 0003 on Postgres: ``fanout_run`` and ``fanout_hold`` with their checks, the lint's
exemptions, and the fan-out stores through a plain role: the runs and the hold with their audit
rows of no tenant, a batch writing decisions under each tenant's row-level security, and the rule
events consumer committing the run with its inbox row. Needs Docker.

The stores run as a role that owns nothing and is not a superuser, as ``cw_app`` does in the
product; the audit rows of no tenant, which no policy lets that role read, are read back as the
superuser.
"""

import importlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import ontology as ontology_package
from applicability_engine import worker
from applicability_engine.application.fanout import (
    CANCEL_ACTION,
    HOLD_ACTION,
    PAUSE_ACTION,
    RELEASE_ACTION,
    FanOutControl,
    FanOutQuery,
    HoldControl,
    ListFanOuts,
    PauseFanOut,
    ReleaseHold,
    SetHold,
)
from applicability_engine.application.fanout_batch import BatchRequest, EvaluateBatch
from applicability_engine.application.fanout_runs import BeginFanOut, ReadControls
from applicability_engine.application.rule_events import RuleEvents
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.fanout import FanOutSignal, FanOutStart, FanOutStatus
from applicability_engine.domain.model import Trigger
from applicability_engine.infrastructure.repository import (
    PostgresBusinessDirectory,
    PostgresFanOutUnitOfWorkFactory,
    PostgresUnitOfWorkFactory,
)
from applicability_engine.testing import MemoryProfiles, MemoryRulebook, rule_version
from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.ids import BusinessId, EventId, RuleVersionId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from py_common.audit.schema import AUDIT_SCHEMA, QUALIFIED_TABLE
from py_common.audit.testing import install_audit_table, read_audit_entries
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
EXAMPLES = SERVICE_DIR.parents[1] / "packages" / "contracts" / "events" / "examples"
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "applicability"
RUN = "fanout_run"
HOLD = "fanout_hold"
APP_ROLE = "fanout_app"
APP_PASSWORD = "app-role-for-tests"
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
ADMIN = AuditActor.user(UserId.new(), [Role.ADMIN])
REASON = "Checking the version with the analysts"
NOW = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
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
    with engine.begin() as connection:
        install_audit_table(connection)
        connection.execute(text(f"GRANT USAGE ON SCHEMA {AUDIT_SCHEMA} TO {APP_ROLE}"))
        connection.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {QUALIFIED_TABLE} TO {APP_ROLE}")
        )
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, engine: Engine) -> Iterator[Engine]:
    engine = create_engine(database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@"))
    yield engine
    engine.dispose()


@pytest.fixture
def clean(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"DELETE FROM {RUN}"))
        connection.execute(text(f"DELETE FROM {HOLD}"))


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


class Signals:
    def __init__(self) -> None:
        self.sent: list[tuple[RuleVersionId, FanOutSignal]] = []
        self.started: list[FanOutStart] = []

    def start(self, start: FanOutStart) -> bool:
        self.started.append(start)
        return True

    def signal(self, rule_version_id: RuleVersionId, signal: FanOutSignal) -> None:
        self.sent.append((rule_version_id, signal))


def start_of(level: AttributeLevel = AttributeLevel.REGISTRATION) -> FanOutStart:
    return FanOutStart(
        rule_version_id=RuleVersionId.new(),
        rule_key="gstr9_annual",
        level=level,
        trigger_event_id=EventId.new(),
        supersedes=(RuleVersionId.new(),),
    )


def test_upgrade_downgrade_upgrade(alembic_config: Config, engine: Engine) -> None:
    assert {RUN, HOLD} <= tables(engine)
    command.downgrade(alembic_config, "0002")
    assert not {RUN, HOLD} & tables(engine)
    command.upgrade(alembic_config, "head")
    assert {RUN, HOLD} <= tables(engine)
    with engine.begin() as connection:
        connection.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {RUN}, {HOLD} TO {APP_ROLE}")
        )


def test_the_catalog_lint_exempts_the_two_tables(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    config = lint.load_config()
    for name in (RUN, HOLD):
        (table,) = [t for t in catalog if t.name == name]
        assert table.tenant_id == "absent"
        exemption = config.exemption_for(f"{SCHEMA}.{name}")
        assert exemption is not None
        assert exemption.kind == "exempt"
    problems = lint.catalog_problems(catalog, config)
    assert [p for p in problems if p.startswith(f"{SCHEMA}.")] == []


def test_the_tables_refuse_what_the_domain_refuses(engine: Engine, clean: None) -> None:
    def refused(sql: str) -> None:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text(sql))

    refused(
        f"INSERT INTO {HOLD} (id, reason, set_by, set_at) VALUES (2, 'A long reason', 'x', now())"
    )
    refused(
        f"INSERT INTO {HOLD} (id, reason, set_by, set_at) VALUES (1, '   short   ', 'x', now())"
    )
    columns = "rule_version_id, rule_key, level, status, trigger_event_id, started_at, updated_at"
    values = f"'{uuid4()}', 'k', 'registration', '{{status}}', '{uuid4()}', now(), now()"
    refused(f"INSERT INTO {RUN} ({columns}) VALUES ({values.format(status='completed')})")
    refused(f"INSERT INTO {RUN} ({columns}) VALUES ({values.format(status='sleeping')})")
    refused(
        f"INSERT INTO {RUN} ({columns}, evaluated, applies) "
        f"VALUES ({values.format(status='running')}, 1, 2)"
    )


def test_runs_and_the_hold_through_a_plain_role_with_audit_rows_of_no_tenant(
    engine: Engine, app_engine: Engine, clean: None
) -> None:
    fanouts = PostgresFanOutUnitOfWorkFactory(app_engine)
    directory = PostgresBusinessDirectory(app_engine)
    signals = Signals()
    begin = BeginFanOut(fanouts, directory)
    starts = [start_of() for _ in range(3)]
    for start in starts:
        begun = begin.run(start)
        assert (begun.status, begun.supersedes) == (FanOutStatus.RUNNING, start.supersedes)
    assert begin.run(starts[0]) == ReadControls(fanouts).run(starts[0].rule_version_id).run
    runs = ListFanOuts(fanouts)
    page = runs.run(FanOutQuery(limit=2))
    assert len(page) == 2
    assert page[0].started_at >= page[1].started_at

    SetHold(fanouts).run(HoldControl(ADMIN, "Deploy of the rulebook in progress", "req-1"))
    SetHold(fanouts).run(HoldControl(ADMIN, "Deploy of the rulebook still in progress"))
    paused = PauseFanOut(fanouts, signals).run(
        FanOutControl(starts[0].rule_version_id, ADMIN, REASON)
    )
    assert paused.status is FanOutStatus.PAUSED
    controls = ReadControls(fanouts).run(starts[0].rule_version_id)
    assert controls.hold is not None
    assert controls.hold.reason == "Deploy of the rulebook still in progress"
    released = ReleaseHold(fanouts, signals).run(HoldControl(ADMIN))
    assert released is not None
    assert ReadControls(fanouts).run(starts[0].rule_version_id).hold is None
    assert signals.sent == [(starts[0].rule_version_id, FanOutSignal.PAUSE)]

    with app_engine.connect() as connection:
        assert read_audit_entries(connection) == [], "no policy reads rows of no tenant"
    subjects = {"global", *(str(start.rule_version_id) for start in starts)}
    with engine.connect() as connection:
        entries = [e for e in read_audit_entries(connection) if e.subject_id in subjects]
    assert [entry.action for entry in entries] == [
        HOLD_ACTION,
        HOLD_ACTION,
        PAUSE_ACTION,
        RELEASE_ACTION,
    ]
    assert {entry.tenant_id for entry in entries} == {None}
    assert entries[0].correlation_id == "req-1"


def test_a_batch_writes_each_tenant_under_its_own_setting(
    engine: Engine, app_engine: Engine, clean: None
) -> None:
    profiles, rulebook = MemoryProfiles(), MemoryRulebook()
    version = rulebook.put(rule_version(REGULAR))
    tenant_units = PostgresUnitOfWorkFactory(app_engine)
    tenants = [TenantId.new(), TenantId.new()]
    for tenant in tenants:
        for _ in range(3):
            entity, business = BusinessId.new(), BusinessId.new()
            profiles.put(
                {"registration_type": "regular"},
                tenant_id=tenant,
                business_id=business,
                lineage=[entity],
            )
            with tenant_units(tenant) as uow:
                uow.directory.add(
                    DirectoryEntry(tenant, business, AttributeLevel.REGISTRATION, entity, entity)
                )
    directory = PostgresBusinessDirectory(app_engine)
    before = directory.count(level=AttributeLevel.REGISTRATION)
    assert before >= 6
    batch = EvaluateBatch(directory, tenant_units, profiles, rulebook, ontology_package.load())
    start = FanOutStart(
        version.rule_version_id, "example_rule", AttributeLevel.REGISTRATION, EventId.new()
    )
    first = batch.run(BatchRequest(start, limit=before))
    assert (first.evaluated, first.appended, first.published) == (6, 6, 6)
    again = batch.run(BatchRequest(start, limit=before))
    assert (again.evaluated, again.appended) == (6, 0)
    for tenant in tenants:
        with app_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
            )
            rows = connection.execute(
                text(
                    "SELECT trigger, trigger_ref FROM applicability_decision "
                    "WHERE rule_version_id = :v"
                ),
                {"v": version.rule_version_id.value},
            ).all()
            outbox: int = connection.execute(
                text("SELECT count(*) FROM outbox_event WHERE tenant_id = :t"),
                {"t": tenant.value},
            ).scalar_one()
        assert {row.trigger for row in rows} == {Trigger.RULE_PUBLISHED.value}
        assert {row.trigger_ref for row in rows} == {start.trigger_ref}
        assert (len(rows), outbox) == (3, 3)


def rule_record(topic: str, example: str, **payload: object) -> InboundRecord:
    data: dict[str, Any] = json.loads((EXAMPLES / topic / f"{example}.json").read_text("utf-8"))
    data["event_id"] = str(uuid4())
    data["payload"].update(payload)
    return InboundRecord(
        topic=topic, partition=0, offset=0, key=b"k", value=json.dumps(data).encode()
    )


async def test_the_rule_events_consumer_commits_the_run_with_its_inbox_row(
    engine: Engine, app_engine: Engine, clean: None
) -> None:
    rulebook = MemoryRulebook()
    version = rulebook.put(rule_version(REGULAR, rule_key="gstr9_annual"))
    signals = Signals()
    consumer = IdempotentConsumer(
        group_id=worker.RULES_GROUP_ID,
        store=read_first_store(app_engine, worker.RULES_GROUP_ID),
        handler=worker.rules_handler(RuleEvents(rulebook, signals, enabled=True)),
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    published = rule_record(
        "rule.published", "first-version", rule_version_id=str(version.rule_version_id)
    )
    assert await consumer.process(published) is Outcome.PROCESSED
    assert await consumer.process(published) is Outcome.SKIPPED
    controls = ReadControls(PostgresFanOutUnitOfWorkFactory(app_engine)).run(
        version.rule_version_id
    )
    assert controls.run is not None
    assert controls.run.status is FanOutStatus.RUNNING
    assert len(signals.started) == 1
    withdrawn = rule_record(
        "rule.withdrawn", "withdrawn-by-an-analyst", rule_version_id=str(version.rule_version_id)
    )
    assert await consumer.process(withdrawn) is Outcome.PROCESSED
    cancelled = ReadControls(PostgresFanOutUnitOfWorkFactory(app_engine)).run(
        version.rule_version_id
    )
    assert cancelled.run is not None
    assert cancelled.run.status is FanOutStatus.CANCELLED
    with engine.connect() as connection:
        processed: int = connection.execute(
            text("SELECT count(*) FROM processed_event WHERE consumer_group = :g"),
            {"g": worker.RULES_GROUP_ID},
        ).scalar_one()
        (entry,) = read_audit_entries(connection, action=CANCEL_ACTION)
    assert processed == 2
    assert entry.actor.label == "system:applicability-engine"
    assert entry.occurred_at > NOW - timedelta(days=1)
