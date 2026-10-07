"""Migration 0005 and obligation tracking on Postgres, through a role that owns nothing and is not a
superuser, so row-level security holds as in a deployment. Needs Docker.

- the profile version, the assignee, the wider change log, the comments and the idempotency keys
  migrate down and up (a person's change survives the round trip: the narrowed kind check binds
  new rows only), match the models and pass the catalog lint;
- starting, completing, assigning and commenting write their change rows, the closure's outbox
  row and an audit row (``audit.event`` as identity's migration makes it) in one transaction, and
  a failure after the audit row leaves none of them;
- a tenant reads and changes none of another tenant's obligations, comments or assignees, through
  the use cases or in SQL;
- comments are append-only outside a tenant's erasure;
- the routes replay a change sent twice with one Idempotency-Key, with the key kept per tenant;
- the detail fills the rule version cache once when it lacks the version.
"""

import importlib
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, TenantId, UserId
from domain_kernel.status import ObligationStatus
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.application.tracking import (
    ASSIGN_ACTION,
    COMMENT_ACTION,
    COMPLETE_ACTION,
    START_ACTION,
    Acting,
    AddComment,
    Assignment,
    AssignObligation,
    ChangeStatus,
    NewComment,
    ReadObligation,
    StatusAction,
    StatusChange,
)
from obligation.domain.errors import ObligationNotFoundError
from obligation.domain.history import ChangeKind
from obligation.infrastructure.models import Base
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.main import build_app
from obligation.settings import ObligationSettings
from obligation.testing import FakeRuleVersionReader, FakeTenantMembers, ref_of, rule
from py_common.audit.schema import AUDIT_SCHEMA, QUALIFIED_TABLE
from py_common.audit.testing import install_audit_table, read_audit_entries
from py_common.audit.writer import PostgresAuditSink
from py_common.idempotency.fastapi import REPLAYED_HEADER

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
COMMENT = "obligation_comment"
KEYS = "idempotency_key"
TRACKED = {"obligation", "obligation_change", COMMENT, "obligation_decision"}
APP_ROLE = "obligation_app"
APP_PASSWORD = "app-role-for-tests"
RESTRICT_VIOLATION = "23001"
AS_OF = date(2026, 9, 28)
OWNER = UserId(UUID(int=0x0E1))
STAFF = UserId(UUID(int=0x5AF))
REQUEST_ID = "0123456789abcdef0123456789abcdef"


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
    with engine.begin() as connection:
        install_audit_table(connection)
        connection.execute(text(f"GRANT USAGE ON SCHEMA {AUDIT_SCHEMA} TO {APP_ROLE}"))
        connection.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {QUALIFIED_TABLE} TO {APP_ROLE}")
        )
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_url(database_url: str, engine: Engine) -> str:
    return database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@")


@pytest.fixture(scope="module")
def app_engine(app_url: str) -> Iterator[Engine]:
    engine = create_engine(app_url)
    yield engine
    engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def columns(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table, schema=SCHEMA)}


def as_tenant(connection: Connection, tenant: TenantId) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
    )


def count(engine: Engine, tenant: TenantId, sql: str, **params: object) -> int:
    with engine.begin() as connection:
        as_tenant(connection, tenant)
        value: int = connection.execute(text(sql), params).scalar_one()
    return value


def sqlstate(error: DBAPIError) -> object:
    return getattr(error.orig, "sqlstate", None)


def acting(tenant: TenantId, user: UserId = OWNER) -> Acting:
    return Acting(
        tenant,
        AuditActor.user(user, [Role.OWNER]),
        user_id=user,
        verified=True,
        correlation_id=REQUEST_ID,
    )


class Tracked:
    """Two open obligations of a fresh monthly rule for one business of a new tenant, made from
    profile version 5, and the tracking use cases on the app role's engine."""

    def __init__(self, engine: Engine, *, cached: bool = True) -> None:
        self.factory = PostgresUnitOfWorkFactory(engine)
        self.tenant = TenantId.new()
        self.rule = rule()
        self.reader = FakeRuleVersionReader([self.rule])
        made = MaterialiseObligations(self.factory).run(
            MaterialiseRequest(
                self.tenant,
                BusinessId.new(),
                DecisionId.new(),
                self.rule,
                AS_OF,
                ref=ref_of(self.rule) if cached else None,
                profile_version=5,
            )
        )
        if cached:
            with self.factory(self.tenant) as uow:
                uow.rule_versions.merge(ref_of(self.rule))
        self.first, self.second = made.created
        self.members = FakeTenantMembers([(self.tenant, OWNER), (self.tenant, STAFF)])
        self.read = ReadObligation(self.factory, self.reader)
        self.status = ChangeStatus(self.factory)
        self.assign = AssignObligation(self.factory, self.members)
        self.comment = AddComment(self.factory)


def comment_as(
    engine: Engine, setting: TenantId, tenant: TenantId, obligation: ObligationId
) -> None:
    """A comment of ``tenant`` on ``obligation``, inserted under ``setting``'s tenant setting."""
    with engine.begin() as connection:
        as_tenant(connection, setting)
        connection.execute(
            text(
                f"INSERT INTO {COMMENT} (id, tenant_id, obligation_id, author_label, body, "
                "created_at) VALUES (:id, :tenant, :obligation, 'owner', 'Example', now())"
            ),
            {"id": uuid4(), "tenant": tenant.value, "obligation": obligation.value},
        )


# ---------------------------------------------------------------- the migration


def test_upgrade_downgrade_upgrade_keeps_a_persons_change(
    alembic_config: Config, engine: Engine, app_engine: Engine
) -> None:
    tracked = Tracked(app_engine)
    tracked.status.run(StatusChange(acting(tracked.tenant), tracked.first, StatusAction.START))
    command.downgrade(alembic_config, "0004")
    assert not {COMMENT, KEYS} & tables(engine)
    assert not {"profile_version", "assignee_id"} & columns(engine, "obligation")
    assert "note" not in columns(engine, "obligation_change")
    assert "profile_version" not in columns(engine, "obligation_decision")
    with engine.connect() as connection:
        valid: object = connection.execute(
            text(
                "SELECT convalidated FROM pg_constraint WHERE conname = 'ck_obligation_change_kind'"
            )
        ).scalar_one()
    assert valid is False, "the narrowed kind check binds new rows only"
    command.upgrade(alembic_config, "head")
    assert {COMMENT, KEYS} <= tables(engine)
    kinds = count(
        app_engine,
        tracked.tenant,
        "SELECT count(*) FROM obligation_change WHERE kind = 'started'",
    )
    assert kinds == 1, "going back deleted no change"


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_the_tracked_tables(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table in TRACKED

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_the_tracked_tables,
            },
        )
        assert compare_metadata(context, Base.metadata) == []
    indexes = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes(COMMENT, SCHEMA)}
    assert indexes["ix_obligation_comment_obligation"] == [
        "tenant_id",
        "obligation_id",
        "created_at",
    ]


def test_the_catalog_lint_accepts_the_tables(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    for name in (COMMENT, KEYS):
        (table,) = [t for t in catalog if t.name == name]
        assert table.tenant_id == "not_null"
        assert lint.tenant_table_problems(table) == []
    problems = lint.catalog_problems(catalog, lint.load_config())
    assert [p for p in problems if p.startswith(f"{SCHEMA}.")] == []


# ---------------------------------------------------------------- the use cases


def test_tracking_writes_changes_the_closure_event_and_audit_rows_together(
    app_engine: Engine,
) -> None:
    tracked = Tracked(app_engine)
    owner = acting(tracked.tenant)
    started = tracked.status.run(StatusChange(owner, tracked.first, StatusAction.START))
    assigned = tracked.assign.run(Assignment(owner, tracked.first, STAFF))
    done = tracked.status.run(
        StatusChange(owner, tracked.first, StatusAction.COMPLETE, "Filed on the portal")
    )
    comment = tracked.comment.run(NewComment(owner, tracked.first, "Example note (synthetic)"))
    assert (started.status, assigned.assignee_id, done.status) == (
        ObligationStatus.IN_PROGRESS,
        STAFF,
        ObligationStatus.DONE,
    )
    detail = tracked.read.run(tracked.tenant, tracked.first)
    assert detail.obligation.profile_version == 5
    assert detail.obligation.assignee_id == STAFF
    assert [c.kind for c in detail.history] == [
        ChangeKind.CREATED,
        ChangeKind.STARTED,
        ChangeKind.ASSIGNED,
        ChangeKind.CLOSED,
    ]
    closed = detail.history[-1]
    assert (closed.reason, closed.note, closed.actor) == ("completed", "Filed on the portal", OWNER)
    assert detail.history[2].new_assignee_id == STAFF
    assert detail.comments == (comment,)
    assert detail.ref == ref_of(tracked.rule)
    with app_engine.begin() as connection:
        as_tenant(connection, tracked.tenant)
        entries = read_audit_entries(connection)
        topics: list[str] = list(
            connection.execute(
                text("SELECT topic FROM outbox_event WHERE tenant_id = :t ORDER BY occurred_at"),
                {"t": tracked.tenant.value},
            ).scalars()
        )
    created = [e for e in entries if e.action == "obligation.created"]
    assert len(created) == 2, "materialising wrote one entry per obligation"
    entries = [e for e in entries if e.action != "obligation.created"]
    assert [e.action for e in entries] == [
        START_ACTION,
        ASSIGN_ACTION,
        COMPLETE_ACTION,
        COMMENT_ACTION,
    ]
    assert {e.subject_id for e in entries} == {str(tracked.first)}
    assert {e.correlation_id for e in entries} == {REQUEST_ID}
    assert dict(entries[-1].after or {}) == {"comment_id": str(comment.id)}
    assert topics == ["obligation.created", "obligation.created", "obligation.closed"]


def test_a_change_that_fails_after_its_audit_row_leaves_nothing(
    app_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracked = Tracked(app_engine)
    written = PostgresAuditSink.write

    def write_then_fail(sink: PostgresAuditSink, *args: Any) -> None:
        written(sink, *args)
        raise RuntimeError("synthetic failure after the audit row was written")

    monkeypatch.setattr(PostgresAuditSink, "write", write_then_fail)
    owner = acting(tracked.tenant)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        tracked.status.run(StatusChange(owner, tracked.first, StatusAction.COMPLETE))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        tracked.comment.run(NewComment(owner, tracked.first, "Example note (synthetic)"))
    monkeypatch.undo()
    detail = tracked.read.run(tracked.tenant, tracked.first)
    assert detail.obligation.status is ObligationStatus.OPEN
    assert [c.kind for c in detail.history] == [ChangeKind.CREATED]
    assert detail.comments == ()
    tracking_rows = "SELECT count(*) FROM audit.event WHERE action <> 'obligation.created'"
    assert count(app_engine, tracked.tenant, tracking_rows) == 0
    closed_events = (
        "SELECT count(*) FROM outbox_event WHERE topic = 'obligation.closed' AND tenant_id = :t"
    )
    assert count(app_engine, tracked.tenant, closed_events, t=tracked.tenant.value) == 0


def test_a_tenant_reads_and_changes_nothing_of_another(app_engine: Engine) -> None:
    tracked = Tracked(app_engine)
    owner = acting(tracked.tenant)
    tracked.assign.run(Assignment(owner, tracked.first, STAFF))
    tracked.comment.run(NewComment(owner, tracked.first, "Example note (synthetic)"))
    other = TenantId.new()
    theirs = acting(other)
    with pytest.raises(ObligationNotFoundError):
        tracked.read.run(other, tracked.first)
    with pytest.raises(ObligationNotFoundError):
        tracked.status.run(StatusChange(theirs, tracked.first, StatusAction.COMPLETE))
    with pytest.raises(ObligationNotFoundError):
        tracked.assign.run(Assignment(theirs, tracked.first, None))
    with pytest.raises(ObligationNotFoundError):
        tracked.comment.run(NewComment(theirs, tracked.first, "Example note (synthetic)"))

    for sql in (
        f"SELECT count(*) FROM {COMMENT}",
        "SELECT count(*) FROM obligation WHERE assignee_id IS NOT NULL",
        "SELECT count(*) FROM audit.event",
    ):
        assert count(app_engine, other, sql) == 0, sql
    with app_engine.begin() as connection:
        as_tenant(connection, other)
        moved = connection.execute(
            text("UPDATE obligation SET assignee_id = :someone WHERE id = :id"),
            {"someone": uuid4(), "id": tracked.first.value},
        ).rowcount
    assert moved == 0, "another tenant's update matches no row"
    with pytest.raises(ProgrammingError, match="row-level"):
        comment_as(app_engine, other, tracked.tenant, tracked.first)
    detail = tracked.read.run(tracked.tenant, tracked.first)
    assert (detail.obligation.assignee_id, len(detail.comments)) == (STAFF, 1)
    assert detail.obligation.status is ObligationStatus.OPEN


def test_comments_are_append_only_outside_an_erasure(app_engine: Engine) -> None:
    tracked = Tracked(app_engine)
    tracked.comment.run(
        NewComment(acting(tracked.tenant), tracked.first, "Example note (synthetic)")
    )
    for statement in (f"UPDATE {COMMENT} SET body = 'changed'", f"DELETE FROM {COMMENT}"):
        with app_engine.begin() as connection:
            as_tenant(connection, tracked.tenant)
            with pytest.raises(DBAPIError, match="obligation_comment is append-only") as refused:
                connection.execute(text(statement))
        assert sqlstate(refused.value) == RESTRICT_VIOLATION
    with app_engine.connect() as connection, connection.begin() as transaction:
        as_tenant(connection, tracked.tenant)
        connection.execute(text("SELECT set_config('app.erasure', 'on', true)"))
        with pytest.raises(DBAPIError, match="append-only"), connection.begin_nested():
            connection.execute(text(f"UPDATE {COMMENT} SET body = 'changed'"))
        assert connection.execute(text(f"DELETE FROM {COMMENT}")).rowcount == 1
        transaction.rollback()
    assert count(app_engine, tracked.tenant, f"SELECT count(*) FROM {COMMENT}") == 1


def test_the_detail_fills_a_missing_cache_row_once(app_engine: Engine) -> None:
    tracked = Tracked(app_engine, cached=False)
    version = tracked.rule.rule_version_id
    with tracked.factory(tracked.tenant) as uow:
        assert uow.rule_versions.get(version) is None
    detail = tracked.read.run(tracked.tenant, tracked.first)
    assert detail.ref is not None
    assert detail.ref.citations
    assert tracked.read.run(tracked.tenant, tracked.second).ref == detail.ref
    assert tracked.reader.reads == [version]
    with tracked.factory(TenantId.new()) as uow:
        assert uow.rule_versions.get(version) == detail.ref, "the cache is rule-level"


# ---------------------------------------------------------------- the routes


def test_a_change_sent_twice_with_one_key_is_made_once(app_engine: Engine, app_url: str) -> None:
    tracked = Tracked(app_engine)
    settings = ObligationSettings(
        _env_file=None,
        service_name="obligation",
        obligation_store="postgres",
        database_url=app_url,
    )
    app = build_app(settings, rules=tracked.reader, members=tracked.members)
    route = f"/v1/obligations/{tracked.first}"
    key = str(uuid4())
    with TestClient(app) as client:
        headers = {"x-tenant-id": str(tracked.tenant), "Idempotency-Key": key}
        first = client.post(f"{route}/status", json={"action": "complete"}, headers=headers)
        second = client.post(f"{route}/status", json={"action": "complete"}, headers=headers)
        other = TenantId.new()
        theirs = client.post(
            f"{route}/status",
            json={"action": "complete"},
            headers={"x-tenant-id": str(other), "Idempotency-Key": key},
        )
        commented = client.post(
            f"{route}/comments",
            json={"body": "Example note (synthetic)"},
            headers={"x-tenant-id": str(tracked.tenant), "Idempotency-Key": str(uuid4())},
        )
    assert (first.status_code, second.status_code) == (200, 200), first.text
    assert first.json() == second.json()
    assert second.headers[REPLAYED_HEADER] == "true"
    assert (theirs.status_code, REPLAYED_HEADER in theirs.headers) == (404, False), (
        "the key of another tenant is another key"
    )
    assert commented.status_code == 201, commented.text
    closures = "SELECT count(*) FROM obligation_change WHERE kind = 'closed'"
    assert count(app_engine, tracked.tenant, closures) == 1
    assert count(app_engine, tracked.tenant, f"SELECT count(*) FROM {KEYS}") == 2
    assert count(app_engine, other, f"SELECT count(*) FROM {KEYS}") == 0
    assert count(app_engine, tracked.tenant, f"SELECT count(*) FROM {COMMENT}") == 1


def test_the_list_route_reads_the_new_fields(app_engine: Engine, app_url: str) -> None:
    tracked = Tracked(app_engine)
    tracked.assign.run(Assignment(acting(tracked.tenant), tracked.second, STAFF))
    settings = ObligationSettings(
        _env_file=None,
        service_name="obligation",
        obligation_store="postgres",
        database_url=app_url,
    )
    app = build_app(settings, rules=tracked.reader, members=tracked.members)
    with TestClient(app) as client:
        with tracked.factory(tracked.tenant) as uow:
            obligation = uow.obligations.get(tracked.second)
        assert obligation is not None
        listed = client.get(
            "/v1/obligation/obligations",
            params={"business_id": str(obligation.business_id)},
            headers={"x-tenant-id": str(tracked.tenant)},
        ).json()
    by_id = {item["obligation_id"]: item for item in listed}
    assert by_id[str(tracked.second)]["assignee_id"] == str(STAFF)
    assert {item["profile_version"] for item in listed} == {5}
    assert {ObligationId(UUID(item["obligation_id"])) for item in listed} == {
        tracked.first,
        tracked.second,
    }
