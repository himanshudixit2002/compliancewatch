"""audit.event on Postgres: the table ``create_audit_table`` makes, as identity's migration does,
written by ``AuditWriter`` in the transaction of an action. Needs Docker.

The writes run as a role that owns nothing and is not a superuser, granted what
``infra/dev/postgres/50-app-role.sql`` grants ``cw_app``, so row-level security applies to it as
it does to the product's services. The superuser bypasses the policies but not the trigger.
"""

import uuid
from collections.abc import Iterator

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.ids import TenantId
from py_common.audit.schema import (
    PLATFORM_INSERT_POLICY,
    QUALIFIED_TABLE,
    create_audit_table,
    drop_audit_table,
)
from py_common.audit.testing import audit_entry, install_audit_table, read_audit_entries
from py_common.audit.writer import AuditWriter, PostgresAuditSink

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
APP_ROLE = "audit_app"
APP_PASSWORD = "audit-role-for-tests"
RESTRICT_VIOLATION = "23001"
TENANT_A = TenantId.new()
TENANT_B = TenantId.new()
SERVICE = "example-service"


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        engine = create_engine(url, poolclass=NullPool)
        with engine.begin() as connection:
            connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
            install_audit_table(connection)
            connection.execute(text(f"GRANT USAGE ON SCHEMA audit TO {APP_ROLE}"))
            connection.execute(
                text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {QUALIFIED_TABLE} TO {APP_ROLE}")
            )
            # The action an entry records: a write to a service's own table.
            connection.execute(text("CREATE SCHEMA work"))
            connection.execute(
                text("CREATE TABLE work.thing (id uuid PRIMARY KEY, tenant_id uuid NOT NULL)")
            )
            connection.execute(text(f"GRANT USAGE ON SCHEMA work TO {APP_ROLE}"))
            connection.execute(text(f"GRANT SELECT, INSERT ON work.thing TO {APP_ROLE}"))
        engine.dispose()
        yield url


@pytest.fixture(scope="module")
def admin(base_url: str) -> Iterator[Engine]:
    engine = create_engine(base_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app(base_url: str) -> Iterator[Engine]:
    engine = create_engine(
        base_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@"), poolclass=NullPool
    )
    yield engine
    engine.dispose()


def as_tenant(connection: Connection, tenant: TenantId) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
    )


def act(connection: Connection, thing: uuid.UUID, tenant: TenantId) -> None:
    connection.execute(
        text("INSERT INTO work.thing (id, tenant_id) VALUES (:id, :tenant)"),
        {"id": thing, "tenant": tenant.value},
    )


def entry_of(tenant: TenantId | None, **overrides: object) -> AuditEntry:
    values: dict[str, object] = {"tenant_id": tenant, "subject_id": f"thing-{uuid.uuid4()}"}
    return audit_entry(**{**values, **overrides})


def write_as(engine: Engine, tenant: TenantId | None, *entries: AuditEntry) -> None:
    """``entries`` in one transaction under ``tenant``'s setting, or with no tenant set."""
    with engine.begin() as connection:
        if tenant is not None:
            as_tenant(connection, tenant)
        for entry in entries:
            AuditWriter().write(connection, entry)


def execute_as(engine: Engine, tenant: TenantId | None, sql: str, **params: object) -> int:
    """``sql`` in a transaction of its own under ``tenant``'s setting; the rows it touched."""
    with engine.begin() as connection:
        if tenant is not None:
            as_tenant(connection, tenant)
        touched: int = connection.execute(text(sql), params).rowcount
    return touched


def stored(admin: Engine, entry: AuditEntry) -> int:
    with admin.connect() as connection:
        found: int = connection.execute(
            text(f"SELECT count(*) FROM {QUALIFIED_TABLE} WHERE id = :id"),
            {"id": entry.entry_id.value},
        ).scalar_one()
    return found


def sqlstate(error: DBAPIError) -> object:
    return getattr(error.orig, "sqlstate", None)


def test_the_app_role_is_not_a_superuser(app: Engine) -> None:
    with app.connect() as connection:
        query = text("SELECT usesuper FROM pg_user WHERE usename = current_user")
        assert connection.execute(query).scalar_one() is False


def test_the_table_has_forced_row_level_security_and_two_policies(admin: Engine) -> None:
    with admin.connect() as connection:
        flags = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                f"WHERE oid = '{QUALIFIED_TABLE}'::regclass"
            )
        ).one()
        policies = connection.execute(
            text(
                "SELECT policyname, cmd FROM pg_policies "
                "WHERE schemaname = 'audit' AND tablename = 'event' ORDER BY policyname"
            )
        ).all()
    assert tuple(flags) == (True, True)
    assert [tuple(policy) for policy in policies] == [
        (PLATFORM_INSERT_POLICY, "INSERT"),
        ("event_tenant_isolation", "ALL"),
    ]


def test_an_entry_commits_with_the_action(admin: Engine, app: Engine) -> None:
    thing = uuid.uuid4()
    entry = entry_of(TENANT_A, subject_id=str(thing), correlation_id="request-1")
    with app.begin() as connection:
        as_tenant(connection, TENANT_A)
        act(connection, thing, TENANT_A)
        PostgresAuditSink(connection).write(entry)
    with app.begin() as connection:
        as_tenant(connection, TENANT_A)
        assert entry in read_audit_entries(connection, action=entry.action)
        assert connection.execute(
            text("SELECT count(*) FROM work.thing WHERE id = :id"), {"id": thing}
        ).scalar_one()


def test_an_entry_rolls_back_with_the_action(admin: Engine, app: Engine) -> None:
    def unit(entry: AuditEntry, thing: uuid.UUID, *, fail: bool) -> None:
        """The entry, then the action, in one transaction."""
        with app.begin() as connection:
            as_tenant(connection, TENANT_A)
            AuditWriter().write(connection, entry)
            act(connection, thing, TENANT_A)
            if fail:
                raise RuntimeError("the action failed after its entry was written")

    failed_later = entry_of(TENANT_A)
    with pytest.raises(RuntimeError, match="the action failed"):
        unit(failed_later, uuid.uuid4(), fail=True)
    assert stored(admin, failed_later) == 0

    thing = uuid.uuid4()
    unit(entry_of(TENANT_A), thing, fail=False)
    clashing = entry_of(TENANT_A)
    with pytest.raises(IntegrityError, match="thing_pkey"):
        unit(clashing, thing, fail=False)
    assert stored(admin, clashing) == 0, "the failed action takes its entry with it"


def test_row_level_security_refuses_an_entry_of_another_tenant(admin: Engine, app: Engine) -> None:
    refused = entry_of(TENANT_B)
    with pytest.raises(ProgrammingError, match="row-level security"):
        write_as(app, TENANT_A, refused)
    unset = entry_of(TENANT_A)
    with pytest.raises(ProgrammingError, match="row-level security"):
        write_as(app, None, unset)
    assert stored(admin, refused) == stored(admin, unset) == 0

    platform_wide = [entry_of(None, actor=AuditActor.system(SERVICE)) for _ in range(2)]
    write_as(app, TENANT_A, platform_wide[0])
    write_as(app, None, platform_wide[1])
    assert [stored(admin, entry) for entry in platform_wide] == [1, 1]


def test_a_tenant_reads_its_own_entries_and_no_one_reads_the_platform_ones(
    admin: Engine, app: Engine
) -> None:
    mine, theirs, platform = entry_of(TENANT_A), entry_of(TENANT_B), entry_of(None)
    write_as(app, TENANT_A, mine, platform)
    write_as(app, TENANT_B, theirs)
    with app.begin() as connection:
        as_tenant(connection, TENANT_A)
        seen = read_audit_entries(connection)
    assert mine in seen
    assert theirs not in seen
    assert platform not in seen
    assert {entry.tenant_id for entry in seen} == {TENANT_A}
    with app.begin() as connection:
        assert read_audit_entries(connection) == [], "no tenant setting reads nothing"
    with admin.connect() as connection:
        everything = read_audit_entries(connection)
    assert {mine, theirs, platform} <= set(everything), "the superuser bypasses the policies"


@pytest.mark.parametrize(
    "statement",
    [
        f"UPDATE {QUALIFIED_TABLE} SET reason = 'rewritten' WHERE id = :id",
        f"DELETE FROM {QUALIFIED_TABLE} WHERE id = :id",
    ],
)
def test_update_and_delete_are_refused(admin: Engine, app: Engine, statement: str) -> None:
    mine, platform = entry_of(TENANT_A), entry_of(None)
    write_as(app, TENANT_A, mine, platform)

    with pytest.raises(DBAPIError, match="event is append-only") as refused:
        execute_as(app, TENANT_A, statement, id=mine.entry_id.value)
    assert sqlstate(refused.value) == RESTRICT_VIOLATION
    hidden = execute_as(app, TENANT_A, statement, id=platform.entry_id.value)
    assert hidden == 0, "row-level security hides the rows of no tenant from the role"
    for entry in (mine, platform):
        with pytest.raises(DBAPIError, match="append-only") as refused:
            execute_as(admin, None, statement, id=entry.entry_id.value)
        assert sqlstate(refused.value) == RESTRICT_VIOLATION
    with app.begin() as connection:
        as_tenant(connection, TENANT_A)
        assert mine in read_audit_entries(connection), "unchanged"
    assert stored(admin, platform) == 1


def test_the_stored_row_is_masked_but_its_ids_are_not(app: Engine) -> None:
    node = "5a3c6a0e-0d7b-4f43-9a4e-234567890123"  # made up; its last group reads as Aadhaar
    entry = entry_of(
        TENANT_A,
        subject_id=node,
        reason="Example Owner, 9876543210, asked to correct the PAN",
        before={"pan": "ABCDE1234F", "node_id": "234567890123"},
        after={"pan": "ABCDE9876F", "emails": ["owner@example.com"], "set_by": node},
    )
    write_as(app, TENANT_A, entry)
    with app.begin() as connection:
        as_tenant(connection, TENANT_A)
        [stored] = [found for found in read_audit_entries(connection) if found.subject_id == node]
    assert stored.entry_id == entry.entry_id
    assert stored.reason == "Example Owner, [PHONE], asked to correct the PAN"
    assert stored.before == {"pan": "[PAN]", "node_id": "234567890123"}
    assert stored.after == {"pan": "[PAN]", "emails": ("[EMAIL]",), "set_by": node}


def test_the_drop_removes_the_table_and_its_function_but_keeps_the_schema(admin: Engine) -> None:
    def exists(connection: Connection, sql: str) -> bool:
        found: bool = connection.execute(text(sql)).scalar_one()
        return found

    with admin.connect() as connection:
        transaction = connection.begin()
        op = Operations(MigrationContext.configure(connection))
        drop_audit_table(op)
        assert not exists(connection, f"SELECT to_regclass('{QUALIFIED_TABLE}') IS NOT NULL")
        assert not exists(
            connection, "SELECT to_regprocedure('audit.audit_append_only()') IS NOT NULL"
        )
        assert exists(
            connection, "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'audit')"
        )
        create_audit_table(op)
        assert exists(connection, f"SELECT to_regclass('{QUALIFIED_TABLE}') IS NOT NULL")
        transaction.rollback()
