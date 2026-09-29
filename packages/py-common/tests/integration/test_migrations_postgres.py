"""The migration helpers on Postgres: the tenant policy under a plain role, the append-only
trigger with and without the erasure exception, and the drop twins. Needs Docker.

Each test works in its own service-style schema, on the ``search_path`` exactly as a service
migration runs, so the guard's function lands in that schema without being named.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from py_common.migrations import (
    create_append_only_guard,
    drop_append_only_guard,
    drop_tenant_rls,
    enable_tenant_rls,
)

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
APP_ROLE = "guard_app"
APP_PASSWORD = "guard-role-for-tests"
RESTRICT_VIOLATION = "23001"
TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()

type Step = Callable[[Operations], None]


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        engine = create_engine(url, poolclass=NullPool)
        with engine.begin() as connection:
            connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
        engine.dispose()
        yield url


@pytest.fixture(scope="module")
def admin(base_url: str) -> Iterator[Engine]:
    engine = create_engine(base_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app(base_url: str) -> Iterator[Engine]:
    """A role that owns nothing and is not a superuser, so the policies apply to it."""
    engine = create_engine(
        base_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@"), poolclass=NullPool
    )
    yield engine
    engine.dispose()


def service_schema(admin: Engine, schema: str, *tables: str) -> None:
    """A schema with ``tables`` (id, tenant_id, note) the app role may read and write."""
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {APP_ROLE}"))
        for table in tables:
            connection.execute(
                text(
                    f"CREATE TABLE {schema}.{table} "
                    "(id uuid PRIMARY KEY, tenant_id uuid NOT NULL, note text)"
                )
            )
            connection.execute(
                text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.{table} TO {APP_ROLE}")
            )


def migrate(admin: Engine, schema: str, *steps: Step) -> None:
    """Run helper calls in one transaction with ``schema`` first on the search_path."""
    with admin.begin() as connection:
        connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))
        op = Operations(MigrationContext.configure(connection))
        for step in steps:
            step(op)


def in_schema(connection: Connection, schema: str) -> None:
    connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))


def as_tenant(connection: Connection, tenant: uuid.UUID) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
    )


def erasing(connection: Connection) -> None:
    connection.execute(text("SELECT set_config('app.erasure', 'on', true)"))


def insert(connection: Connection, table: str, tenant: uuid.UUID) -> uuid.UUID:
    row = uuid.uuid4()
    connection.execute(
        text(f"INSERT INTO {table} (id, tenant_id, note) VALUES (:id, :tenant, 'x')"),
        {"id": row, "tenant": tenant},
    )
    return row


def sqlstate(error: DBAPIError) -> object:
    return getattr(error.orig, "sqlstate", None)


def function_exists(admin: Engine, qualified: str) -> bool:
    with admin.connect() as connection:
        found: object = connection.execute(
            text("SELECT to_regprocedure(:signature) IS NOT NULL"),
            {"signature": f"{qualified}()"},
        ).scalar_one()
    return bool(found)


def test_tenant_policy_admits_only_the_current_tenant(admin: Engine, app: Engine) -> None:
    service_schema(admin, "rls_test", "tenant_rows")
    migrate(admin, "rls_test", lambda op: enable_tenant_rls(op, "tenant_rows"))
    with app.begin() as connection:
        in_schema(connection, "rls_test")
        as_tenant(connection, TENANT_A)
        mine = insert(connection, "tenant_rows", TENANT_A)
        with pytest.raises(ProgrammingError, match="row-level security"), connection.begin_nested():
            insert(connection, "tenant_rows", TENANT_B)
    with app.begin() as connection:
        in_schema(connection, "rls_test")
        as_tenant(connection, TENANT_B)
        assert connection.execute(text("SELECT count(*) FROM tenant_rows")).scalar_one() == 0
        as_tenant(connection, TENANT_A)
        assert connection.execute(text("SELECT id FROM tenant_rows")).scalars().all() == [mine]
    with app.begin() as connection:
        in_schema(connection, "rls_test")
        unset: int = connection.execute(text("SELECT count(*) FROM tenant_rows")).scalar_one()
        assert unset == 0, "no tenant setting means no rows"

    migrate(admin, "rls_test", lambda op: drop_tenant_rls(op, "tenant_rows"))
    with admin.connect() as connection:
        flags = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'rls_test.tenant_rows'::regclass"
            )
        ).one()
        policies: int = connection.execute(
            text("SELECT count(*) FROM pg_policies WHERE schemaname = 'rls_test'")
        ).scalar_one()
    assert tuple(flags) == (False, False)
    assert policies == 0


def test_append_only_refuses_update_and_delete_even_during_erasure(
    admin: Engine, app: Engine
) -> None:
    service_schema(admin, "strict_test", "strict_rows")
    migrate(admin, "strict_test", lambda op: create_append_only_guard(op, "strict_rows"))
    assert function_exists(admin, "strict_test.strict_test_append_only")
    with app.begin() as connection:
        in_schema(connection, "strict_test")
        row = insert(connection, "strict_rows", TENANT_A)
    for statement in (
        "UPDATE strict_rows SET note = 'y' WHERE id = :id",
        "DELETE FROM strict_rows WHERE id = :id",
    ):
        with app.begin() as connection:
            in_schema(connection, "strict_test")
            erasing(connection)
            with pytest.raises(DBAPIError, match="strict_rows is append-only") as refused:
                connection.execute(text(statement), {"id": row})
        assert sqlstate(refused.value) == RESTRICT_VIOLATION


def test_erasure_variant_allows_delete_only_while_app_erasure_is_on(
    admin: Engine, app: Engine
) -> None:
    service_schema(admin, "erasure_test", "erasable_rows")
    migrate(
        admin,
        "erasure_test",
        lambda op: create_append_only_guard(op, "erasable_rows", allow_erasure_delete=True),
    )
    with app.begin() as connection:
        in_schema(connection, "erasure_test")
        row = insert(connection, "erasable_rows", TENANT_A)
    with app.begin() as connection:
        in_schema(connection, "erasure_test")
        with pytest.raises(DBAPIError, match="append-only") as refused:
            connection.execute(text("DELETE FROM erasable_rows WHERE id = :id"), {"id": row})
    assert sqlstate(refused.value) == RESTRICT_VIOLATION
    with app.begin() as connection:
        in_schema(connection, "erasure_test")
        erasing(connection)
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(
                text("UPDATE erasable_rows SET note = 'y' WHERE id = :id"), {"id": row}
            )
    with app.begin() as connection:
        in_schema(connection, "erasure_test")
        erasing(connection)
        deleted = connection.execute(
            text("DELETE FROM erasable_rows WHERE id = :id"), {"id": row}
        ).rowcount
    assert deleted == 1

    migrate(
        admin,
        "erasure_test",
        lambda op: drop_append_only_guard(op, "erasable_rows", allow_erasure_delete=True),
    )
    assert not function_exists(admin, "erasure_test.erasure_test_append_only_erasable")


def test_tables_share_the_schema_function_until_the_last_guard_is_dropped(
    admin: Engine,
) -> None:
    service_schema(admin, "shared_test", "first_log", "second_log")
    migrate(
        admin,
        "shared_test",
        lambda op: create_append_only_guard(op, "first_log"),
        lambda op: create_append_only_guard(op, "second_log"),
    )
    function = "shared_test.shared_test_append_only"
    migrate(admin, "shared_test", lambda op: drop_append_only_guard(op, "first_log"))
    assert function_exists(admin, function), "second_log still calls it"
    with admin.begin() as connection:
        in_schema(connection, "shared_test")
        insert(connection, "first_log", TENANT_A)
        assert connection.execute(text("DELETE FROM first_log")).rowcount == 1
    migrate(admin, "shared_test", lambda op: drop_append_only_guard(op, "second_log"))
    assert not function_exists(admin, function)
