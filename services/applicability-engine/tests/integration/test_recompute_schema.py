"""Migration 0002 on Postgres: the consumer inbox, the business directory and the review queue
under row-level security through a plain role, the profile.updated consumer committing with its
inbox row and storing nothing twice for a replayed event, no transaction open while it reads, and
the review flow, whose resolution writes one audit row in its own transaction (``audit.event`` as
identity's migration makes it, installed by ``py_common.audit.testing``). Needs Docker.

The use cases run as a role that owns nothing and is not a superuser: a superuser bypasses
row-level security whatever the table says.
"""

import importlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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

import ontology as ontology_package
from applicability_engine import worker
from applicability_engine.application.recompute import ApplyProfileUpdate, ProfileUpdate
from applicability_engine.application.review import (
    RESOLVE_ACTION,
    ListReviewItems,
    ResolveRequest,
    ResolveReviewItem,
    ReviewQuery,
)
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.errors import ReviewItemResolvedError
from applicability_engine.domain.review import Resolution, ReviewStatus
from applicability_engine.infrastructure.models import Base
from applicability_engine.infrastructure.repository import (
    DirectoryKey,
    PostgresBusinessDirectory,
    PostgresUnitOfWorkFactory,
)
from applicability_engine.testing import MemoryProfiles, MemoryRulebook, rule_in_force
from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.ids import BusinessId, EventId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.profiles import ProfileSnapshot
from py_common.audit.schema import AUDIT_SCHEMA, QUALIFIED_TABLE
from py_common.audit.testing import install_audit_table, read_audit_entries
from py_common.audit.writer import PostgresAuditSink
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
DECISION = "applicability_decision"
DIRECTORY = "business_directory"
REVIEW = "review_item"
NEW_TABLES = {DIRECTORY, REVIEW, "processed_event"}
APP_ROLE = "recompute_app"
APP_PASSWORD = "app-role-for-tests"
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
FREE_TEXT = {"attribute": "business_category", "free_text": "Example premises shared with a hotel"}


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
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


def count(engine: Engine, tenant: TenantId, sql: str, **params: object) -> int:
    with engine.begin() as connection:
        as_tenant(connection, tenant)
        found: int = connection.execute(text(sql), params).scalar_one()
    return found


class World:
    """A tenant's entity with one registration, a rule of each kind, and the recompute."""

    def __init__(self, *, free_text: bool = False) -> None:
        self.tenant = TenantId.new()
        self.entity = BusinessId.new()
        self.registration = BusinessId.new()
        self.profiles = MemoryProfiles()
        self.rulebook = MemoryRulebook()
        self.profiles.put(
            {"state_codes": frozenset({"29"})},
            tenant_id=self.tenant,
            business_id=self.entity,
            level=AttributeLevel.ENTITY,
        )
        self.profiles.put(
            {"registration_type": "regular"},
            tenant_id=self.tenant,
            business_id=self.registration,
            lineage=[self.entity],
            version=2,
        )
        specification = {"all_of": [REGULAR, FREE_TEXT]} if free_text else REGULAR
        self.rule = self.rulebook.put_in_force(rule_in_force(specification))
        self.recompute = ApplyProfileUpdate(
            self.profiles, self.rulebook, ontology_package.load(), enabled=True
        )

    def update(self) -> ProfileUpdate:
        return ProfileUpdate(self.tenant, EventId.new(), self.entity, profile_version=2)

    def record(self, event_id: UUID | None = None, offset: int = 0) -> InboundRecord:
        data = json.loads(
            (EXAMPLES / "profile.updated" / "turnover-band-by-user.json").read_text("utf-8")
        )
        data["event_id"] = str(event_id or uuid4())
        data["tenant_id"] = str(self.tenant)
        data["payload"]["business_id"] = str(self.entity)
        return InboundRecord(
            topic="profile.updated",
            partition=0,
            offset=offset,
            key=b"k",
            value=json.dumps(data).encode(),
        )

    def consumer(self, app_engine: Engine, group_id: str = worker.GROUP_ID) -> IdempotentConsumer:
        return IdempotentConsumer(
            group_id=group_id,
            store=read_first_store(app_engine, group_id),
            handler=worker.profile_handler(self.recompute),
            producer=FakeProducer(),
            config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
        )

    def counts(self, app_engine: Engine) -> tuple[int, int, int]:
        """Decisions, their outbox rows and directory entries of the tenant."""
        return (
            count(app_engine, self.tenant, f"SELECT count(*) FROM {DECISION}"),
            count(
                app_engine,
                self.tenant,
                "SELECT count(*) FROM outbox_event WHERE tenant_id = :t",
                t=self.tenant.value,
            ),
            count(
                app_engine,
                self.tenant,
                f"SELECT count(*) FROM {DIRECTORY} WHERE tenant_id = :t",
                t=self.tenant.value,
            ),
        )


def test_upgrade_downgrade_upgrade_keeps_the_decisions(
    alembic_config: Config, engine: Engine
) -> None:
    decision_id, tenant = uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {DECISION} (id, tenant_id, business_id, rule_version_id, result, "
                "confidence, profile_version, trigger, trigger_ref, evaluated, decided_at) "
                "VALUES (:id, :tenant, :id, :id, 'applies', 1, 1, 'review', 'review:x', '[]', "
                "now())"
            ),
            {"id": decision_id, "tenant": tenant},
        )
    command.downgrade(alembic_config, "0001")
    assert not NEW_TABLES & tables(engine)
    columns = {column["name"] for column in inspect(engine).get_columns(DECISION, schema=SCHEMA)}
    assert "trigger_ref" not in columns
    with engine.connect() as connection:
        kept: str = connection.execute(
            text(f"SELECT trigger FROM {DECISION} WHERE id = :id"), {"id": decision_id}
        ).scalar_one()
    assert kept == "review", "going back deletes no decision"
    command.upgrade(alembic_config, "head")
    assert tables(engine) >= NEW_TABLES


def test_models_and_migration_agree(engine: Engine) -> None:
    mine = {table.name for table in Base.metadata.sorted_tables}

    def only_the_models(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table in mine

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_the_models,
            },
        )
        assert compare_metadata(context, Base.metadata) == []


def test_the_catalog_lint_accepts_the_tables(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    (review,) = [t for t in catalog if t.name == REVIEW]
    (directory,) = [t for t in catalog if t.name == DIRECTORY]
    assert lint.tenant_table_problems(review) == []
    assert lint.routing_directory_problems(directory) == []
    problems = lint.catalog_problems(catalog, lint.load_config())
    assert [p for p in problems if p.startswith(f"{SCHEMA}.")] == []


def test_the_app_role_is_not_a_superuser(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        query = text("SELECT usesuper FROM pg_user WHERE usename = current_user")
        assert connection.execute(query).scalar_one() is False


def test_the_directory_is_read_across_tenants_and_written_per_tenant(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    entries = {}
    for owner in (tenant, other):
        entity = BusinessId.new()
        entries[owner] = DirectoryEntry(owner, entity, AttributeLevel.ENTITY, None, entity)
        with factory(owner) as uow:
            assert uow.directory.add(entries[owner])
            assert not uow.directory.add(entries[owner]), "written once"
    listed = PostgresBusinessDirectory(app_engine).entries(level=AttributeLevel.ENTITY)
    assert {entries[tenant], entries[other]} <= set(listed)
    first = min(entries.values(), key=lambda e: (e.tenant_id.value, e.business_id.value))
    after = PostgresBusinessDirectory(app_engine).entries(
        after=DirectoryKey(first.tenant_id, first.business_id)
    )
    assert first not in after

    with pytest.raises(ProgrammingError, match="row-level security"):
        execute_as(
            app_engine,
            tenant,
            f"INSERT INTO {DIRECTORY} (business_id, tenant_id, level, entity_id) "
            "VALUES (:id, :other, 'entity', :id)",
            id=uuid4(),
            other=other.value,
        )
    with app_engine.begin() as connection:
        as_tenant(connection, tenant)
        deleted = connection.execute(
            text(f"DELETE FROM {DIRECTORY} WHERE tenant_id = :id"), {"id": other.value}
        ).rowcount
    assert deleted == 0, "a tenant cannot remove another tenant's entry"


async def test_the_consumer_commits_with_its_inbox_row_and_a_replay_adds_nothing(
    app_engine: Engine,
) -> None:
    world = World()
    event_id = uuid4()
    consumer = world.consumer(app_engine)
    assert await consumer.process(world.record(event_id)) is Outcome.PROCESSED
    assert world.counts(app_engine) == (1, 1, 2), "a decision, its event, two directory entries"
    assert await consumer.process(world.record(event_id, offset=1)) is Outcome.SKIPPED
    assert world.counts(app_engine) == (1, 1, 2)

    replay = world.consumer(app_engine, group_id="applicability-engine.replay")
    assert await replay.process(world.record(event_id, offset=2)) is Outcome.PROCESSED
    assert world.counts(app_engine) == (1, 1, 2), "the decision's id derives from the event"
    with app_engine.begin() as connection:
        groups: list[str] = list(
            connection.execute(
                text("SELECT consumer_group FROM processed_event WHERE event_id = :id ORDER BY 1"),
                {"id": event_id},
            ).scalars()
        )
        assert groups == ["applicability-engine.profiles", "applicability-engine.replay"]
        as_tenant(connection, world.tenant)
        payload: dict[str, Any] = connection.execute(
            text("SELECT message -> 'payload' FROM outbox_event WHERE tenant_id = :t"),
            {"t": world.tenant.value},
        ).scalar_one()
    assert (payload["trigger"], payload["business_id"]) == (
        "profile_updated",
        str(world.registration),
    )

    with pytest.raises(IntegrityError, match="uq_applicability_decision_trigger_ref"):
        execute_as(
            app_engine,
            world.tenant,
            f"INSERT INTO {DECISION} (id, tenant_id, business_id, rule_version_id, result, "
            "confidence, profile_version, trigger, trigger_ref, evaluated, decided_at) "
            "SELECT :id, tenant_id, business_id, rule_version_id, result, confidence, "
            f"profile_version, trigger, trigger_ref, evaluated, decided_at FROM {DECISION} "
            "WHERE trigger_ref = :ref",
            id=uuid4(),
            ref=f"profile.updated:{event_id}",
        )


async def test_no_transaction_is_open_while_the_consumer_reads(
    engine: Engine, app_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World()
    idle_in_transaction: list[int] = []
    original = world.profiles.snapshot

    def watching(*args: Any) -> ProfileSnapshot | None:
        with engine.connect() as connection:
            idle_in_transaction.append(
                connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE usename = :role AND state LIKE 'idle in transaction%'"
                    ),
                    {"role": APP_ROLE},
                ).scalar_one()
            )
        return original(*args)

    monkeypatch.setattr(world.profiles, "snapshot", watching)
    assert await world.consumer(app_engine).process(world.record()) is Outcome.PROCESSED
    assert idle_in_transaction, "the profile was read"
    assert set(idle_in_transaction) == {0}, "the consumer's connection held no transaction"


def test_the_review_flow_under_row_level_security(app_engine: Engine) -> None:
    world = World(free_text=True)
    factory = PostgresUnitOfWorkFactory(app_engine)
    done = world.recompute.run(world.update(), factory)
    assert [d.business_id for d in done.appended] == [world.registration]
    listing = ListReviewItems(factory)
    (entry,) = listing.run(ReviewQuery(world.tenant, limit=10, status=ReviewStatus.OPEN))
    assert entry.decision == done.appended[0]
    assert listing.run(ReviewQuery(TenantId.new(), limit=10)) == ()

    second = world.recompute.run(world.update(), factory)
    (followed,) = listing.run(ReviewQuery(world.tenant, limit=10))
    assert followed.item.item_id == entry.item.item_id
    assert followed.item.decision_id == second.appended[0].decision_id

    with pytest.raises(IntegrityError, match="uq_review_item_open"):
        execute_as(
            app_engine,
            world.tenant,
            f"INSERT INTO {REVIEW} (id, tenant_id, business_id, rule_version_id, decision_id, "
            "reason, status, opened_at) SELECT :id, tenant_id, business_id, rule_version_id, "
            f"decision_id, reason, status, opened_at FROM {REVIEW}",
            id=uuid4(),
        )

    reviewer = UserId.new()
    resolve = ResolveReviewItem(factory, clock=lambda: datetime.now(UTC) + timedelta(minutes=1))
    request = ResolveRequest(
        world.tenant,
        entry.item.item_id,
        Resolution.APPLIES,
        reviewer,
        "Example premises checked against the clause",
        AuditActor.user(reviewer, [Role.REVIEWER]),
        "review-request-1",
    )
    resolved = resolve.run(request)
    assert (resolved.item.status, resolved.item.resolved_by) == (ReviewStatus.RESOLVED, reviewer)
    with pytest.raises(ReviewItemResolvedError):
        resolve.run(request)
    with app_engine.begin() as connection:
        as_tenant(connection, world.tenant)
        (audited,) = read_audit_entries(connection, action=RESOLVE_ACTION)
    assert (audited.tenant_id, audited.subject_type, audited.subject_id) == (
        world.tenant,
        "review_item",
        str(entry.item.item_id),
    )
    assert (audited.actor, audited.reason, audited.correlation_id) == (
        request.actor,
        request.note,
        "review-request-1",
    )
    assert audited.before is not None
    assert audited.after is not None
    assert (audited.before["status"], audited.after["status"]) == ("open", "resolved")
    assert (audited.after["resolution"], audited.after["resolution_decision_id"]) == (
        "applies",
        str(resolved.item.resolution_decision_id),
    )
    with factory(world.tenant) as uow:
        appended = uow.decisions.latest(world.registration, world.rule.rule_version_id)
    assert appended is not None
    assert (appended.trigger.value, appended.decision_id) == (
        "review",
        resolved.item.resolution_decision_id,
    )
    with app_engine.begin() as connection:
        as_tenant(connection, world.tenant)
        triggers: list[str] = list(
            connection.execute(
                text(
                    "SELECT message -> 'payload' ->> 'trigger' FROM outbox_event "
                    "WHERE tenant_id = :t ORDER BY occurred_at"
                ),
                {"t": world.tenant.value},
            ).scalars()
        )
        assert triggers[-1] == "review"
        as_tenant(connection, TenantId.new())
        hidden: int = connection.execute(text(f"SELECT count(*) FROM {REVIEW}")).scalar_one()
    assert hidden == 0, "another tenant reads none of the items"


def test_a_resolution_that_fails_after_its_audit_row_leaves_nothing(
    app_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World(free_text=True)
    factory = PostgresUnitOfWorkFactory(app_engine)
    world.recompute.run(world.update(), factory)
    listing = ListReviewItems(factory)
    (entry,) = listing.run(ReviewQuery(world.tenant, limit=10, status=ReviewStatus.OPEN))
    written = PostgresAuditSink.write

    def write_then_fail(sink: PostgresAuditSink, *args: Any) -> None:
        written(sink, *args)
        raise RuntimeError("synthetic failure after the audit row was written")

    monkeypatch.setattr(PostgresAuditSink, "write", write_then_fail)
    reviewer = UserId.new()
    request = ResolveRequest(
        world.tenant,
        entry.item.item_id,
        Resolution.APPLIES,
        reviewer,
        "Example premises checked against the clause",
        AuditActor.user(reviewer, [Role.REVIEWER]),
    )
    with pytest.raises(RuntimeError, match="synthetic failure"):
        ResolveReviewItem(factory).run(request)
    (still_open,) = listing.run(ReviewQuery(world.tenant, limit=10))
    assert still_open.item.is_open
    assert count(app_engine, world.tenant, "SELECT count(*) FROM applicability_decision") == 1
    with app_engine.begin() as connection:
        as_tenant(connection, world.tenant)
        assert read_audit_entries(connection) == [], "the audit row went with the resolution"
