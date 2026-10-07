"""Migration 0008 on Postgres: the billing ledger and the idempotency keys, under forced
row-level security, written by the use cases through identity's own role and the product's
role. Needs Docker.

The roles are ``cw_identity`` as infra/dev/postgres/roles.sql makes it, given to the database
before the migrations as on a fresh dev volume, and ``cw_app`` with the grants
infra/dev/postgres/50-app-role.sql gives it after ``make migrate`` (a psql script, so its
statements are repeated here): both reach the new tables, own nothing and are not superusers.
"""

import hashlib
import importlib
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import TenantId
from identity.application.billing import ReceiveBillingWebhook, StartSubscription
from identity.application.entitlements import ReadEntitlements
from identity.domain.billing import PLANS, StoredBillingEvent, SubscriptionStatus
from identity.domain.entitlements import Limits
from identity.infrastructure.billing.memory import MemoryBillingProvider
from identity.infrastructure.flags import StaticFlags
from identity.infrastructure.models import Base
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.db_roles import apply_roles, as_role
from py_common.idempotency import IdempotencyRequest, Started, StoredResponse
from py_common.idempotency.sqlalchemy import SqlAlchemyIdempotencyStore

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "identity"
NEW_TABLES = ("billing_customer", "billing_subscription", "billing_event")
NOW = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
FREE = Limits(registrations=1, seats=1)
APP_ROLE = "cw_app"
APP_ROLE_SQL = (
    f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_ROLE}' NOSUPERUSER NOBYPASSRLS",
    f"GRANT USAGE ON SCHEMA {SCHEMA}, audit TO {APP_ROLE}",
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA}, audit TO {APP_ROLE}",
    f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {APP_ROLE}",
)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
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
def app_role_url(database_url: str, engine: Engine) -> str:
    """cw_app as make product-role leaves it, after the migrations."""
    with engine.begin() as connection:
        for statement in APP_ROLE_SQL:
            connection.execute(text(statement))
    url = make_url(database_url).set(username=APP_ROLE, password=APP_ROLE)
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="module", params=[SCHEMA, APP_ROLE])
def role_engine(
    request: pytest.FixtureRequest, database_url: str, engine: Engine, app_role_url: str
) -> Iterator[Engine]:
    # Again after the migrations, as make migrate's db-roles step runs it.
    apply_roles(database_url)
    url = app_role_url if request.param == APP_ROLE else as_role(database_url, SCHEMA)
    role_engine = create_engine(url)
    yield role_engine
    role_engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def webhook(tenant: TenantId, subscription_id: str, kind: str = "subscription.activated") -> bytes:
    return json.dumps(
        {
            "event": kind,
            "created_at": 959_850_000,
            "payload": {
                "subscription": {
                    "entity": {
                        "id": subscription_id,
                        "quantity": 2,
                        "notes": {"tenant_id": str(tenant), "plan_key": "owner_monthly"},
                    }
                },
                "payment": {"entity": {"email": "owner@example.com"}},
            },
        }
    ).encode()


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_new_tables(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table in NEW_TABLES

    assert set(NEW_TABLES) | {"idempotency_key"} <= tables(engine)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_new_tables,
            },
        )
        assert compare_metadata(context, Base.metadata) == []


def test_the_catalog_lint_accepts_the_tables_without_exemptions(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [
            t
            for t in lint.read_tables(raw)
            if t.schema == SCHEMA and t.name in (*NEW_TABLES, "idempotency_key")
        ]
    config = lint.load_config()
    assert len(catalog) == 4
    for table in catalog:
        assert config.exemption_for(table.qualified) is None
        assert (table.row_security, table.force_row_security) == (True, True)
    problems = lint.catalog_problems(catalog, config)
    assert [p for p in problems if p.startswith(f"{SCHEMA}.")] == []


def test_the_use_cases_keep_the_ledger_under_each_role(engine: Engine, role_engine: Engine) -> None:
    with engine.begin() as connection:  # the memory provider numbers its ids from 1 again
        connection.execute(text(f"TRUNCATE {', '.join(NEW_TABLES)}"))
    factory = PostgresUnitOfWorkFactory(role_engine)
    provider = MemoryBillingProvider(clock=lambda: NOW)
    tenant, other = TenantId.new(), TenantId.new()
    start = StartSubscription(provider, factory, clock=lambda: NOW)
    started = start.run(tenant, "owner_monthly", email="owner@example.com", name="Example")
    again = start.run(tenant, "ca_seat_monthly", email="owner@example.com", name="Example")
    assert len(provider.customers) == 1, "the stored customer is reused"
    receive = ReceiveBillingWebhook(provider, factory, clock=lambda: NOW)
    body = webhook(tenant, started.provider_subscription_id)
    assert not receive.run(body, provider.sign(body)).duplicate
    assert receive.run(body, provider.sign(body)).duplicate
    with factory(tenant) as uow:
        held = uow.billing.subscription(started.provider_subscription_id)
        held_ids = {s.provider_subscription_id for s in uow.billing.subscriptions()}
        assert held_ids == {started.provider_subscription_id, again.provider_subscription_id}
        customer = uow.billing.customer()
    assert held is not None
    assert (held.status, held.quantity) == (SubscriptionStatus.ACTIVE, 2)
    assert customer is not None
    with factory(other) as uow:
        assert uow.billing.subscription(started.provider_subscription_id) is None
        assert uow.billing.subscriptions() == []
        assert uow.billing.customer() is None
    found = ReadEntitlements(factory, PLANS, FREE, StaticFlags()).run(tenant)
    assert (found.plan_key, found.limits.registrations) == (
        "owner_monthly",
        PLANS["owner_monthly"].limit("registrations", 2),
    )
    with role_engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
        )
        raw = connection.execute(text("SELECT raw_event FROM billing_event")).scalar_one()
    assert raw["payload"]["payment"]["entity"]["email"] == "[EMAIL]"


def test_events_are_append_only_and_unique_per_body(role_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(role_engine)
    tenant = TenantId.new()
    digest = hashlib.sha256(b"example").hexdigest()
    event = StoredBillingEvent(
        id=uuid4(),
        tenant_id=tenant,
        provider_subscription_id="sub_example",
        kind="subscription.charged",
        status=SubscriptionStatus.ACTIVE,
        occurred_at=NOW,
        received_at=NOW,
        body_sha256=digest,
        raw_event={"event": "subscription.charged"},
    )
    with factory(tenant) as uow:
        assert uow.billing.append_event(event)
        assert not uow.billing.append_event(replace(event, id=uuid4()))
    for statement in ("UPDATE billing_event SET kind = 'x'", "DELETE FROM billing_event"):
        with pytest.raises(DBAPIError, match="append-only"):
            as_tenant(role_engine, tenant, statement)


def test_a_row_of_another_tenant_cannot_be_written(role_engine: Engine) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    insert = (
        "INSERT INTO billing_customer (tenant_id, provider, provider_customer_id, email, name, "
        f"created_at) VALUES ('{other}', 'memory', 'cust_1', 'e', 'n', now())"
    )
    with pytest.raises(DBAPIError, match="row-level security"):
        as_tenant(role_engine, tenant, insert)


def as_tenant(engine: Engine, tenant: TenantId, statement: str) -> None:
    """Run ``statement`` in a transaction of ``tenant``."""
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
        )
        connection.execute(text(statement))


def test_the_subscription_route_keys_live_under_the_tenant(role_engine: Engine) -> None:
    store = SqlAlchemyIdempotencyStore(role_engine)
    tenant = TenantId.new()
    request = IdempotencyRequest.of(
        str(uuid4()), "POST", "/v1/identity/billing/subscriptions", b"{}"
    )
    assert isinstance(store.begin(tenant, request), Started)
    store.complete(tenant, request, StoredResponse(201, {"ok": True}))
    assert not isinstance(store.begin(tenant, request), Started)
    assert isinstance(store.begin(TenantId.new(), request), Started)


def test_downgrade_drops_the_ledger_and_upgrade_restores_it(
    alembic_config: Config, engine: Engine
) -> None:
    command.downgrade(alembic_config, "0007")
    assert not (set(NEW_TABLES) | {"idempotency_key"}) & tables(engine)
    with engine.connect() as connection:
        function: bool = connection.execute(
            text("SELECT to_regprocedure('identity.identity_append_only_erasable()') IS NOT NULL")
        ).scalar_one()
    assert not function
    command.upgrade(alembic_config, "head")
    assert set(NEW_TABLES) | {"idempotency_key"} <= tables(engine)
