"""Migration 0011 on Postgres, and identity's erasure as its own role (cw_identity) under forced
row-level security: the consent records' guard, an erased tenant's empty name, the eraser on a
consumer's connection, and the answers that complete the deletion request. Needs Docker."""

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
from domain_kernel.erasure import DeletionRequest
from domain_kernel.ids import CorrelationId, EventId, TenantId
from identity.application.consents import RecordConsent
from identity.application.data_requests import RequestDeletion
from identity.application.erasure import RecordErasure
from identity.application.tenancy import CreateTenant
from identity.domain.billing import Customer
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
from py_common.erasure import begin_erasure, erase_and_record

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "identity"
NOW = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
RESTRICT_VIOLATION = "23001"


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
        return DeletionRequest(
            event_id=EventId.new(),
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


def test_the_catalog_lint_accepts_the_new_inbox(database_url: str) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    engine = create_engine(database_url)
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    engine.dispose()
    assert "processed_event" in {table.name for table in catalog}
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
    allowed = "UPDATE consent_record SET evidence = '', recorded_by = NULL"
    assert sqlstate_of(role_engine, tenant.id, allowed, erasure=True) == ""


def test_the_eraser_leaves_nothing_of_the_tenant_but_what_it_keeps(role_engine: Engine) -> None:
    tenant = Tenant(role_engine, "+919800000102")
    other = Tenant(role_engine, "+919800000103")
    with role_engine.begin() as connection:
        event = erase_and_record(
            "identity", PostgresIdentityEraser(connection), tenant.deletion(), clock=lambda: NOW
        )
    assert dict(event.tables) == {
        "user_subject": 1,
        "app_user": 1,
        "idempotency_key": 1,
        "consent_record": 1,
        "billing_customer": 1,
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
        assert tuple(consent) == (pseudonym(tenant.id, str(tenant.user.id)), "", None, True)
        customer = connection.execute(
            text("SELECT provider_customer_id, email, name FROM billing_customer")
        ).one()
        assert tuple(customer) == ("cust_example", pseudonym(tenant.id, "owner@example.org"), "")
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
    with role_engine.begin() as connection:
        again = erase_and_record(
            "identity", PostgresIdentityEraser(connection), tenant.deletion(), clock=lambda: NOW
        )
    assert again.tables["app_user"] == 0, "a second erasure finds nothing more"
    assert again.tables["consent_record"] == 0


def test_the_answers_complete_the_request_on_the_consumer_s_connection(
    role_engine: Engine,
) -> None:
    tenant = Tenant(role_engine, "+919800000104")
    record = RecordErasure(ERASURE_SERVICES, clock=lambda: NOW)
    for service in ERASURE_SERVICES:
        with role_engine.begin() as connection:
            factory = PostgresUnitOfWorkFactory.on_connection(connection)
            with factory(tenant.id) as uow:
                record.run_in(uow, tenant.id, service)
    with tenant.factory(tenant.id) as uow:
        done = uow.data_requests.get(tenant.request.id)
    assert done is not None
    assert (done.status, done.services_done) == (DataRequestStatus.COMPLETED, ERASURE_SERVICES)
    with role_engine.begin() as connection:
        rolled = connection.begin_nested()
        factory = PostgresUnitOfWorkFactory.on_connection(connection)
        with factory(tenant.id) as uow:
            assert uow.data_requests.open_deletion() is None
        rolled.rollback()
