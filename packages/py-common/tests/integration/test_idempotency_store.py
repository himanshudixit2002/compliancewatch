"""Idempotency keys on Postgres through the real store, the recorder and the purge command.
Needs Docker.

The table is created by ``create_idempotency_table`` in a service-style schema, as a service
migration would call it, and the stores connect as a plain role that owns nothing, so the forced
row-level security applies to them. The container's own user is a superuser and bypasses it;
the tests use it only to arrange rows (moving expiry into the past) and to read the catalog.
"""

import threading
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Engine, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import TenantId
from py_common.idempotency import (
    IdempotencyRequest,
    InFlight,
    Outcome,
    Replay,
    Reused,
    Started,
    StoredResponse,
)
from py_common.idempotency.__main__ import main as purge_main
from py_common.idempotency.schema import (
    IDEMPOTENCY_TABLE,
    PURGE_POLICY,
    create_idempotency_table,
    drop_idempotency_table,
)
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore
from py_common.migrations import tenant_policy_name

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "idempotency_test"
APP_ROLE = "idempotency_app"
APP_PASSWORD = "idempotency-role-for-tests"
TENANT_A = TenantId(uuid.uuid4())
TENANT_B = TenantId(uuid.uuid4())
PATH = "/v1/things"
CREATED = StoredResponse(201, {"id": "7", "name": "Acme"}, {"location": "/v1/things/7"})

thing = Table("thing", MetaData(), Column("name", String(80), primary_key=True))


def request(key: str, body: bytes = b'{"name":"Acme"}') -> IdempotencyRequest:
    return IdempotencyRequest.of(key, "POST", PATH, body)


def fresh_key() -> str:
    return f"key-{uuid.uuid4()}"


@pytest.fixture(scope="module")
def urls() -> Iterator[tuple[str, str]]:
    """(admin url, app url), both with the test schema first on the search_path."""
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        base = container.get_connection_url()
        admin = create_engine(base, poolclass=NullPool)
        with admin.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
            connection.execute(text(f"SET LOCAL search_path TO {SCHEMA}, public"))
            create_idempotency_table(Operations(MigrationContext.configure(connection)))
            thing.create(connection)
            for table in (IDEMPOTENCY_TABLE, "thing"):
                connection.execute(
                    text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} TO {APP_ROLE}")
                )
        admin.dispose()
        options = f"?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        yield (
            base + options,
            base.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@") + options,
        )


@pytest.fixture(scope="module")
def admin(urls: tuple[str, str]) -> Iterator[Engine]:
    engine = create_engine(urls[0], poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app(urls: tuple[str, str]) -> Iterator[Engine]:
    engine = create_engine(urls[1], poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def store(app: Engine) -> SqlAlchemyIdempotencyStore:
    return SqlAlchemyIdempotencyStore(app)


def expire(admin: Engine, tenant: TenantId, key: str) -> None:
    with admin.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {IDEMPOTENCY_TABLE} SET expires_at = now() - interval '1 second' "
                "WHERE tenant_id = :tenant AND key = :key"
            ),
            {"tenant": tenant.value, "key": key},
        )


def rows(admin: Engine, key: str) -> list[Any]:
    with admin.connect() as connection:
        return list(
            connection.execute(
                text(
                    f"SELECT tenant_id, status_code FROM {IDEMPOTENCY_TABLE} WHERE key = :key "
                    "ORDER BY tenant_id"
                ),
                {"key": key},
            )
        )


def as_tenant(connection: Any, tenant: TenantId) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
    )


# ---- the table ----------------------------------------------------------------------------------


def test_the_table_has_forced_row_security_and_two_policies(admin: Engine) -> None:
    with admin.connect() as connection:
        forced = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = to_regclass(:table)"
            ),
            {"table": f"{SCHEMA}.{IDEMPOTENCY_TABLE}"},
        ).one()
        policies: dict[str, str] = dict(
            connection.execute(
                text(
                    "SELECT policyname, cmd FROM pg_policies "
                    "WHERE schemaname = :schema AND tablename = :table"
                ),
                {"schema": SCHEMA, "table": IDEMPOTENCY_TABLE},
            ).all()
        )
        columns = {column["name"] for column in inspect(connection).get_columns(IDEMPOTENCY_TABLE)}
    assert tuple(forced) == (True, True)
    assert policies == {tenant_policy_name(IDEMPOTENCY_TABLE): "ALL", PURGE_POLICY: "DELETE"}
    assert columns == {
        "tenant_id",
        "key",
        "method",
        "path",
        "fingerprint",
        "status_code",
        "response",
        "response_headers",
        "created_at",
        "expires_at",
    }


def test_drop_removes_the_table(admin: Engine) -> None:
    with admin.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("CREATE SCHEMA idempotency_drop"))
        connection.execute(text("SET LOCAL search_path TO idempotency_drop, public"))
        op = Operations(MigrationContext.configure(connection))
        create_idempotency_table(op)
        drop_idempotency_table(op)
        assert not inspect(connection).has_table(IDEMPOTENCY_TABLE, schema="idempotency_drop")
        transaction.rollback()


# ---- the store ----------------------------------------------------------------------------------


def test_a_recorded_response_is_replayed(store: SqlAlchemyIdempotencyStore) -> None:
    key = request(fresh_key())
    assert store.begin(TENANT_A, key) == Started()
    assert store.begin(TENANT_A, key) == InFlight()
    assert store.begin(TENANT_A, request(key.key, b"another body")) == Reused()
    store.complete(TENANT_A, key, CREATED)
    assert store.begin(TENANT_A, key) == Replay(CREATED)


def test_tenant_b_cannot_replay_or_touch_tenant_a_key(
    store: SqlAlchemyIdempotencyStore, admin: Engine, app: Engine
) -> None:
    key = request(fresh_key())
    store.begin(TENANT_A, key)
    store.complete(TENANT_A, key, CREATED)
    assert store.begin(TENANT_B, key) == Started()
    store.abandon(TENANT_B, key)
    with app.begin() as connection:
        as_tenant(connection, TENANT_B)
        seen = connection.execute(
            text(f"SELECT count(*) FROM {IDEMPOTENCY_TABLE} WHERE key = :key"), {"key": key.key}
        ).scalar()
    assert seen == 0
    assert [(row.tenant_id, row.status_code) for row in rows(admin, key.key)] == [
        (TENANT_A.value, 201)
    ]


def test_without_a_tenant_the_app_role_sees_no_key(
    store: SqlAlchemyIdempotencyStore, app: Engine
) -> None:
    key = request(fresh_key())
    store.begin(TENANT_A, key)
    with app.connect() as connection:
        seen = connection.execute(text(f"SELECT count(*) FROM {IDEMPOTENCY_TABLE}")).scalar()
    assert seen == 0


def test_two_concurrent_begins_start_exactly_one(store: SqlAlchemyIdempotencyStore) -> None:
    key = request(fresh_key())
    barrier = threading.Barrier(8)
    outcomes: list[Outcome] = []
    lock = threading.Lock()

    def begin() -> None:
        barrier.wait()
        outcome = store.begin(TENANT_A, key)
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=begin) for _ in range(8)]
    for started in threads:
        started.start()
    for started in threads:
        started.join()
    assert outcomes.count(Started()) == 1
    assert outcomes.count(InFlight()) == 7


def test_an_expired_key_is_claimed_again(store: SqlAlchemyIdempotencyStore, admin: Engine) -> None:
    key = request(fresh_key())
    store.begin(TENANT_A, key)
    store.complete(TENANT_A, key, CREATED)
    expire(admin, TENANT_A, key.key)
    other = request(key.key, b"a different body")
    assert store.begin(TENANT_A, other) == Started()
    store.complete(TENANT_A, key, CREATED)
    assert store.begin(TENANT_A, other) == InFlight()


def test_abandon_releases_the_claim(store: SqlAlchemyIdempotencyStore) -> None:
    key = request(fresh_key())
    store.begin(TENANT_A, key)
    store.abandon(TENANT_A, key)
    assert store.begin(TENANT_A, key) == Started()


def test_a_short_lease_frees_a_key_nobody_recorded(app: Engine) -> None:
    store = SqlAlchemyIdempotencyStore(app, lease=timedelta(0))
    key = request(fresh_key())
    assert store.begin(TENANT_A, key) == Started()
    assert store.begin(TENANT_A, key) == Started()


# ---- the recorder in the caller's transaction --------------------------------------------------


def test_the_key_row_commits_and_rolls_back_with_the_business_write(
    store: SqlAlchemyIdempotencyStore, app: Engine, admin: Engine
) -> None:
    key = request(fresh_key())
    with app.connect() as connection:
        transaction = connection.begin()
        as_tenant(connection, TENANT_A)
        recorder = store.recorder(connection)
        assert recorder.begin(TENANT_A, key) == Started()
        connection.execute(thing.insert().values(name=key.key))
        recorder.complete(TENANT_A, key, CREATED)
        transaction.rollback()
    assert rows(admin, key.key) == []
    with app.begin() as connection:
        as_tenant(connection, TENANT_A)
        recorder = store.recorder(connection)
        assert recorder.begin(TENANT_A, key) == Started()
        connection.execute(thing.insert().values(name=key.key))
        recorder.complete(TENANT_A, key, CREATED)
    assert store.begin(TENANT_A, key) == Replay(CREATED)
    with admin.connect() as connection:
        names: list[str] = list(
            connection.execute(thing.select().where(thing.c.name == key.key)).scalars()
        )
    assert names == [key.key]


def test_a_concurrent_request_waits_for_the_first_transaction_and_replays(
    store: SqlAlchemyIdempotencyStore, app: Engine
) -> None:
    key = request(fresh_key())
    claimed = threading.Event()
    outcomes: list[Outcome] = []

    def second() -> None:
        claimed.wait()
        with app.begin() as connection:
            as_tenant(connection, TENANT_A)
            outcomes.append(store.recorder(connection).begin(TENANT_A, key))

    waiter = threading.Thread(target=second)
    waiter.start()
    with app.begin() as connection:
        as_tenant(connection, TENANT_A)
        recorder = store.recorder(connection)
        assert recorder.begin(TENANT_A, key) == Started()
        claimed.set()
        waiter.join(timeout=0.5)
        assert waiter.is_alive(), "the second begin must wait for this transaction"
        recorder.complete(TENANT_A, key, CREATED)
    waiter.join(timeout=10)
    assert outcomes == [Replay(CREATED)]


def test_a_concurrent_request_claims_the_key_when_the_first_rolls_back(
    store: SqlAlchemyIdempotencyStore, app: Engine
) -> None:
    key = request(fresh_key())
    claimed = threading.Event()
    outcomes: list[Outcome] = []

    def second() -> None:
        claimed.wait()
        with app.begin() as connection:
            as_tenant(connection, TENANT_A)
            outcomes.append(store.recorder(connection).begin(TENANT_A, key))

    waiter = threading.Thread(target=second)
    waiter.start()
    with app.connect() as connection:
        transaction = connection.begin()
        as_tenant(connection, TENANT_A)
        assert store.recorder(connection).begin(TENANT_A, key) == Started()
        claimed.set()
        waiter.join(timeout=0.5)
        transaction.rollback()
    waiter.join(timeout=10)
    assert outcomes == [Started()]


def test_the_recorder_refuses_a_row_for_another_tenant(
    store: SqlAlchemyIdempotencyStore, app: Engine
) -> None:
    with app.connect() as connection:
        transaction = connection.begin()
        as_tenant(connection, TENANT_B)
        with pytest.raises(ProgrammingError, match="row-level security"):
            store.recorder(connection).begin(TENANT_A, request(fresh_key()))
        transaction.rollback()


# ---- the purge ----------------------------------------------------------------------------------


def test_the_purge_deletes_only_expired_keys_of_every_tenant(
    store: SqlAlchemyIdempotencyStore, admin: Engine
) -> None:
    with admin.begin() as connection:
        connection.execute(text(f"DELETE FROM {IDEMPOTENCY_TABLE}"))
    live, old_a, old_b = (request(fresh_key()) for _ in range(3))
    for tenant, key in ((TENANT_A, live), (TENANT_A, old_a), (TENANT_B, old_b)):
        store.begin(tenant, key)
        store.complete(tenant, key, CREATED)
    expire(admin, TENANT_A, old_a.key)
    expire(admin, TENANT_B, old_b.key)
    assert store.purge_expired() == 2
    assert rows(admin, live.key) != []
    assert rows(admin, old_a.key) == rows(admin, old_b.key) == []
    assert store.purge_expired() == 0


def test_a_role_that_bypasses_row_security_still_purges_only_expired_keys(
    store: SqlAlchemyIdempotencyStore, admin: Engine
) -> None:
    live, old = request(fresh_key()), request(fresh_key())
    for key in (live, old):
        store.begin(TENANT_A, key)
    expire(admin, TENANT_A, old.key)
    SqlAlchemyIdempotencyStore(admin).purge_expired()
    assert rows(admin, old.key) == []
    assert rows(admin, live.key) != []


def test_the_purge_command(
    store: SqlAlchemyIdempotencyStore,
    admin: Engine,
    urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = request(fresh_key())
    store.begin(TENANT_A, old)
    expire(admin, TENANT_A, old.key)
    monkeypatch.setenv("CW_DATABASE_URL", urls[1])
    monkeypatch.setenv("CW_LOG_LEVEL", "WARNING")
    assert purge_main(["purge"]) == 0
    assert rows(admin, old.key) == []


def test_the_purge_command_fails_without_the_table(
    urls: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CW_DATABASE_URL", urls[1].split("?", 1)[0])
    monkeypatch.setenv("CW_LOG_LEVEL", "WARNING")
    assert purge_main(["purge"]) == 1
