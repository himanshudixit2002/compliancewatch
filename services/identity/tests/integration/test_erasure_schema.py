"""Migrations 0011 and 0012 on Postgres, and identity's erasure as its own role (cw_identity)
under forced row-level security: the consent records' guard (by allowlist), an erased tenant's
empty name, the eraser on a consumer's connection with its pepper, its marker and the catalog's
check, what identity answers the services' checks, and the answers of both passes that complete
the deletion request, the second pass held in the outbox. Needs Docker."""

import importlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.access import ANONYMOUS
from domain_kernel.erasure import DeletionRequest, ErasureCheck, TenantDataErased
from domain_kernel.ids import CorrelationId, EventId, TenantId
from identity.application.consents import RecordConsent
from identity.application.data_requests import RequestDeletion
from identity.application.erasure import CheckErasure, RecordErasure
from identity.application.tenancy import CreateTenant
from identity.domain.billing import Customer, Subscription, SubscriptionStatus
from identity.domain.consent import ConsentPurpose, ConsentSource
from identity.domain.data_requests import DataRequestStatus
from identity.domain.erasure import ERASURE_SERVICES, pseudonym
from identity.domain.tenancy import TenantKind
from identity.infrastructure.erasure import PostgresIdentityEraser
from identity.infrastructure.minter import IssuerMinter
from identity.infrastructure.providers.fake import FakeIdentityProvider
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.auth import TokenIssuer
from py_common.auth.testing import TestIssuer
from py_common.db_roles import apply_roles, as_role
from py_common.erasure import PostgresErasedTenants, begin_erasure, erase_and_record
from py_common.erasure_testing import assert_nothing_left

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "identity"
NOW = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
RESTRICT_VIOLATION = "23001"
CHECK_VIOLATION = "23514"
PEPPER = b"Example pepper of thirty-two bytes or more"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        apply_roles(base_url)
        yield url


@pytest.fixture(scope="module")
def role_engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


class Tenant:
    """A business signed up as cw_identity with its owner, a consent, a billing customer and an
    idempotency key, and its deletion requested."""

    def __init__(self, engine: Engine, phone: str) -> None:
        self.factory = PostgresUnitOfWorkFactory(engine)
        provider = FakeIdentityProvider()
        issuer = TestIssuer()
        minter = IssuerMinter(
            TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
        )
        created = CreateTenant(
            self.factory, provider, minter, ttl=timedelta(minutes=10), clock=lambda: NOW
        ).run(provider.issue(phone=phone), TenantKind.BUSINESS, "Example Traders")
        self.id, self.user = created.tenant.id, created.user
        RecordConsent(self.factory, clock=lambda: NOW).run(
            self.id,
            str(self.user.id),
            ConsentPurpose.WHATSAPP_REMINDERS,
            granted=True,
            source=ConsentSource.WEB_ONBOARDING,
            notice_version="2000-01",
            evidence="Example onboarding checkbox",
            recorded_by=self.user.id,
        )
        with self.factory(self.id) as uow:
            uow.billing.add_customer(
                Customer(self.id, "cust_example", "owner@example.org", "Example Owner"),
                provider="memory",
                at=NOW,
            )
            uow.billing.add_subscription(
                Subscription(
                    tenant_id=self.id,
                    plan_key="owner_monthly",
                    provider_subscription_id=f"sub_{phone[-4:]}",
                    status=SubscriptionStatus.CREATED,
                    started_at=NOW,
                    checkout_url="https://checkout.example.org/pay",
                )
            )
        with engine.begin() as connection:
            tenant_setting(connection, self.id)
            connection.execute(
                text(
                    "INSERT INTO idempotency_key (tenant_id, key, method, path, fingerprint,"
                    " status_code, expires_at) VALUES (:t, 'k-1', 'POST', '/x', :h, 201,"
                    " now() + interval '1 day')"
                ),
                {"t": self.id.value, "h": "0" * 64},
            )
        self.request = RequestDeletion(self.factory, clock=lambda: NOW).run(ANONYMOUS, self.id)

    def deletion(self) -> DeletionRequest:
        assert self.request.deletion_event_id is not None
        return DeletionRequest(
            event_id=self.request.deletion_event_id,
            tenant_id=self.id,
            correlation_id=CorrelationId.new(),
            requested_at=NOW,
            deadline_at=NOW + timedelta(days=30),
        )


def tenant_setting(connection: Connection, tenant: TenantId) -> None:
    connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})


def count(connection: Connection, table: str, tenant: TenantId) -> int:
    tenant_setting(connection, tenant)
    found = connection.execute(
        text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": tenant.value}
    ).scalar_one()
    return int(found)


def test_the_catalog_lint_accepts_the_new_inbox_and_marker(database_url: str) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    engine = create_engine(database_url)
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    engine.dispose()
    assert {"processed_event", "erased_tenant"} <= {table.name for table in catalog}
    assert [p for p in lint.catalog_problems(catalog, lint.load_config()) if SCHEMA in p] == []


def sqlstate_of(engine: Engine, tenant: TenantId, statement: str, *, erasure: bool) -> str:
    """The SQLSTATE ``statement`` fails with, run as the tenant (in an erasure or not)."""
    try:
        with engine.begin() as connection:
            if erasure:
                begin_erasure(connection, tenant)
            else:
                tenant_setting(connection, tenant)
            connection.execute(text(statement))
    except DBAPIError as exc:
        return str(getattr(exc.orig, "sqlstate", ""))
    return ""


def test_the_consent_guard_lets_only_an_erasure_pseudonymise(role_engine: Engine) -> None:
    tenant = Tenant(role_engine, "+919800000101")
    outside = sqlstate_of(
        role_engine, tenant.id, "UPDATE consent_record SET evidence = ''", erasure=False
    )
    assert outside == RESTRICT_VIOLATION
    deleted = sqlstate_of(role_engine, tenant.id, "DELETE FROM consent_record", erasure=True)
    assert deleted == RESTRICT_VIOLATION
    changed = sqlstate_of(
        role_engine, tenant.id, "UPDATE consent_record SET granted = false", erasure=True
    )
    assert changed == RESTRICT_VIOLATION
    allowed = "UPDATE consent_record SET subject = 'erased:x', evidence = '', recorded_by = NULL"
    assert sqlstate_of(role_engine, tenant.id, allowed, erasure=True) == ""


def test_the_consent_guard_refuses_a_column_it_does_not_name(
    database_url: str, role_engine: Engine
) -> None:
    """The guard compares whole rows: a column added later cannot be changed by an erasure
    without being named in the guard."""
    tenant = Tenant(role_engine, "+919800000105")
    owner = create_engine(database_url)
    with owner.begin() as connection:
        connection.execute(text("ALTER TABLE consent_record ADD COLUMN example_note text"))
        connection.execute(text("GRANT UPDATE ON consent_record TO cw_identity"))
    try:
        later = "UPDATE consent_record SET example_note = 'Example'"
        assert sqlstate_of(role_engine, tenant.id, later, erasure=True) == RESTRICT_VIOLATION
    finally:
        with owner.begin() as connection:
            connection.execute(text("ALTER TABLE consent_record DROP COLUMN example_note"))
        owner.dispose()


def test_an_erased_tenant_has_no_name_and_any_other_has_one(role_engine: Engine) -> None:
    tenant = Tenant(role_engine, "+919800000106")
    named = "UPDATE tenant SET status = 'erased'"
    assert sqlstate_of(role_engine, tenant.id, named, erasure=False) == CHECK_VIOLATION
    empty = "UPDATE tenant SET name = ''"
    assert sqlstate_of(role_engine, tenant.id, empty, erasure=False) == CHECK_VIOLATION
    erased = "UPDATE tenant SET status = 'erased', name = ''"
    assert sqlstate_of(role_engine, tenant.id, erased, erasure=False) == ""


def erase(engine: Engine, tenant: Tenant) -> TenantDataErased:
    with engine.begin() as connection:
        return erase_and_record(
            "identity",
            PostgresIdentityEraser(connection, pepper=PEPPER),
            tenant.deletion(),
            clock=lambda: NOW,
        )


def test_the_eraser_leaves_nothing_of_the_tenant_but_what_it_keeps(
    database_url: str, role_engine: Engine
) -> None:
    tenant = Tenant(role_engine, "+919800000102")
    other = Tenant(role_engine, "+919800000103")
    check = CheckErasure(tenant.factory)
    assert check.run(tenant.id) == ErasureCheck(
        tenant.id, "deletion_requested", deletion_event_id=tenant.request.deletion_event_id
    )
    event = erase(role_engine, tenant)
    assert dict(event.tables) == {
        "user_subject": 1,
        "app_user": 1,
        "idempotency_key": 1,
        "consent_record": 1,
        "billing_customer": 1,
        "billing_subscription": 1,
        "billing_start": 0,
        "outbox_event": 0,
        "tenant": 1,
    }
    with role_engine.begin() as connection:
        for table in ("app_user", "user_subject", "idempotency_key"):
            assert count(connection, table, tenant.id) == 0, table
            assert count(connection, table, other.id) == 1, f"{table} of another tenant stays"
        tenant_setting(connection, tenant.id)
        consent = connection.execute(
            text("SELECT subject, evidence, recorded_by, granted FROM consent_record")
        ).one()
        assert tuple(consent) == (
            pseudonym(tenant.id, str(tenant.user.id), PEPPER),
            "",
            None,
            True,
        )
        customer = connection.execute(
            text("SELECT provider_customer_id, email, name FROM billing_customer")
        ).one()
        assert tuple(customer) == (
            "cust_example",
            pseudonym(tenant.id, "owner@example.org", PEPPER),
            "",
        )
        checkout = connection.execute(text("SELECT checkout_url FROM billing_subscription"))
        assert checkout.scalar_one() == "", "the checkout link is gone"
        assert tuple(connection.execute(text("SELECT name, status FROM tenant")).one()) == (
            "",
            "erased",
        )
        erased = connection.execute(
            text(
                "SELECT message->'payload'->>'service' FROM outbox_event "
                "WHERE tenant_id = :t AND topic = 'tenant.data.erased'"
            ),
            {"t": tenant.id.value},
        ).scalars()
        assert list(erased) == ["identity"]
        assert count(connection, "data_request", tenant.id) == 1, "the request is kept"
    owner = create_engine(database_url)
    with owner.connect() as connection:
        retained = assert_nothing_left(connection, SCHEMA, tenant.id, event)
    owner.dispose()
    assert retained["erased_tenant.tenant_id"] == 1, "the marker"
    assert retained["consent_record.tenant_id"] == 1, "pseudonymised, not deleted"
    assert PostgresErasedTenants(role_engine).is_erased(tenant.id)
    assert not PostgresErasedTenants(role_engine).is_erased(other.id)
    assert check.run(tenant.id).tenant_status == "erased"
    again = erase(role_engine, tenant)
    assert sum(again.tables.values()) == 0, "a second erasure changes nothing more"


def answer_all(engine: Engine, tenant: Tenant, record: RecordErasure, event_id: EventId) -> None:
    for service in ERASURE_SERVICES:
        with engine.begin() as connection:
            factory = PostgresUnitOfWorkFactory.on_connection(connection)
            with factory(tenant.id) as uow:
                record.run_in(uow, tenant.id, service, deletion_event_id=event_id)


def test_both_passes_complete_the_request_on_the_consumer_s_connection(
    role_engine: Engine,
) -> None:
    tenant = Tenant(role_engine, "+919800000104")
    first = tenant.request.deletion_event_id
    assert first is not None
    record = RecordErasure(
        ERASURE_SERVICES, clock=lambda: NOW, second_pass_after=timedelta(seconds=900)
    )
    answer_all(role_engine, tenant, record, first)
    with tenant.factory(tenant.id) as uow:
        waiting = uow.data_requests.get(tenant.request.id)
    assert waiting is not None
    assert (waiting.status, waiting.erasure_pass, waiting.second_pass_at) == (
        DataRequestStatus.IN_PROGRESS,
        2,
        NOW + timedelta(seconds=900),
    )
    second = waiting.deletion_event_id
    assert second is not None
    assert second != first
    with role_engine.begin() as connection:
        held = connection.execute(
            text("SELECT topic, status, available_at FROM outbox_event WHERE id = :id"),
            {"id": second.value},
        ).one()
    assert tuple(held) == (
        "tenant.deletion.requested",
        "pending",
        NOW + timedelta(seconds=900),
    ), "the second pass waits in the outbox until it is due"
    answer_all(role_engine, tenant, record, second)
    with tenant.factory(tenant.id) as uow:
        done = uow.data_requests.get(tenant.request.id)
    assert done is not None
    assert (done.status, done.services_done, done.second_pass_done) == (
        DataRequestStatus.COMPLETED,
        ERASURE_SERVICES,
        ERASURE_SERVICES,
    )
    with role_engine.begin() as connection:
        rolled = connection.begin_nested()
        factory = PostgresUnitOfWorkFactory.on_connection(connection)
        with factory(tenant.id) as uow:
            assert uow.data_requests.open_deletion() is None
        rolled.rollback()
