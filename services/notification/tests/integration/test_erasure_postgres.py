"""Notification's erasure on Postgres, as its own role cw_notification under forced row-level
security on the tenant tables: the tenant's notifications, work, recipients and directory rows
go, the opt-ins of addresses no other tenant holds go, the opt-outs and a shared one stay without
the tenant's reference, a preference another tenant's user set stays that tenant's, and another
tenant's rows stay. The catalog shows every table of the schema with a tenant column erased or
retained with a reason. Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.erasure import DeletionRequest
from domain_kernel.ids import BusinessId, CorrelationId, EventId, ObligationId, TenantId, UserId
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.domain.ids import RecipientId
from notification.domain.notification import Notification
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import ConsentSource
from notification.domain.recipients import BusinessLink, RecipientRole
from notification.domain.repository import UnitOfWorkFactory, WorkEntry
from notification.infrastructure.erasure import TABLES, PostgresNotificationEraser
from notification.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.erasure import count_rows, erase_and_record
from py_common.erasure_testing import assert_nothing_left

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "notification"
WHEN = datetime(2000, 1, 3, 6, 30, tzinfo=UTC)
SHARED_PHONE = "+919876543240"
OWN_PHONE = "+919876543241"
OWN_MAIL = "owner.erased@example.com"


def register(
    factory: UnitOfWorkFactory, tenant: TenantId, addresses: list[tuple[Channel, str]]
) -> None:
    RegisterRecipient(factory, clock=lambda: WHEN).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=RecipientId.new(),
            role=RecipientRole.OWNER,
            user_id=UserId.new(),
            addresses=addresses,
            businesses=[BusinessLink(BusinessId.new(), "Example Traders")],
        )
    )


def notify(factory: UnitOfWorkFactory, tenant: TenantId, address: str) -> None:
    notification = Notification.queue(
        tenant_id=tenant,
        business_id=BusinessId.new(),
        obligation_id=ObligationId.new(),
        recipient_id=None,
        channel=Channel.WHATSAPP,
        address=address,
        occasion=OccasionKind.REMINDER,
        template_key="obligation_due_soon",
        language="en",
        params={"title": "Example obligation"},
        dedupe_key=DedupeKey(uuid4().hex * 2),
        now=WHEN,
    )
    with factory(tenant) as unit:
        assert unit.notifications.add_if_absent(notification)
        unit.work.add(WorkEntry.of(notification))


def scenario(factory: UnitOfWorkFactory) -> tuple[TenantId, TenantId]:
    """Two tenants that share a number; the first also has its own number and email address,
    each with a preference, and notifications of both."""
    tenant, other = TenantId.new(), TenantId.new()
    register(factory, tenant, [(Channel.WHATSAPP, SHARED_PHONE), (Channel.EMAIL, OWN_MAIL)])
    register(factory, tenant, [(Channel.WHATSAPP, OWN_PHONE)])
    register(factory, other, [(Channel.WHATSAPP, SHARED_PHONE)])
    opt_in = SetOptIn(factory, clock=lambda: WHEN)
    opt_in.run(
        Channel.WHATSAPP,
        SHARED_PHONE,
        opted_in=True,
        source=ConsentSource.WEB_ONBOARDING,
        set_for_tenant=tenant,
    )
    opt_in.run(
        Channel.EMAIL,
        OWN_MAIL,
        opted_in=False,
        source=ConsentSource.WEB_SETTINGS,
        set_for_tenant=tenant,
    )
    opt_in.run(Channel.WHATSAPP, OWN_PHONE, opted_in=True, source=ConsentSource.API)
    for _ in range(2):
        notify(factory, tenant, SHARED_PHONE)
    notify(factory, other, SHARED_PHONE)
    return tenant, other


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


def counts(engine: Engine, tenant: TenantId) -> dict[str, int]:
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        return {table: count_rows(connection, table, tenant) for table in TABLES}


def preferences(engine: Engine) -> dict[str, tuple[bool, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT address, opted_in, set_for_tenant_id FROM channel_preference")
        ).all()
    return {row.address: (row.opted_in, row.set_for_tenant_id) for row in rows}


def request_for(tenant: TenantId) -> DeletionRequest:
    return DeletionRequest(
        event_id=EventId.new(),
        tenant_id=tenant,
        correlation_id=CorrelationId.new(),
        requested_at=WHEN,
        deadline_at=WHEN + timedelta(days=30),
    )


def test_the_tenant_s_notifications_go_and_kept_preferences_stay(
    engine: Engine, database_url: str
) -> None:
    factory = PostgresUnitOfWorkFactory(engine)
    tenant, other = scenario(factory)
    before, theirs = counts(engine, tenant), counts(engine, other)
    assert (before["notification"], before["recipient"], before["work_index"]) == (2, 2, 2)
    request = DeletionRequest(
        event_id=EventId.new(),
        tenant_id=tenant,
        correlation_id=CorrelationId.new(),
        requested_at=WHEN,
        deadline_at=WHEN + timedelta(days=30),
    )
    with engine.begin() as connection:
        answer = erase_and_record(
            "notification", PostgresNotificationEraser(connection), request, clock=lambda: WHEN
        )
    assert {table: answer.tables[table] for table in TABLES} == before
    assert answer.tables["channel_preference"] == 3, "one deleted, two without the tenant"
    assert counts(engine, tenant) == dict.fromkeys(TABLES, 0)
    assert counts(engine, other) == theirs, "another tenant's rows stay"
    assert preferences(engine) == {
        SHARED_PHONE: (True, None),
        OWN_MAIL: (False, None),
    }, "the shared number's consent and the opt-out stay, without the tenant"
    owner = create_engine(database_url)
    with owner.connect() as connection:
        retained = assert_nothing_left(connection, SCHEMA, tenant, answer)
    owner.dispose()
    assert retained["erased_tenant.tenant_id"] == 1


def test_a_preference_another_tenant_s_user_set_stays_theirs(engine: Engine) -> None:
    """The review's case: B's user opts in on the web for a number only A holds in the
    directory; A's erasure keeps B's preference, and B's reference."""
    factory = PostgresUnitOfWorkFactory(engine)
    first, second = TenantId.new(), TenantId.new()
    number = "+919876543249"
    register(factory, first, [(Channel.WHATSAPP, number)])
    SetOptIn(factory, clock=lambda: WHEN).run(
        Channel.WHATSAPP,
        number,
        opted_in=True,
        source=ConsentSource.WEB_ONBOARDING,
        set_for_tenant=second,
    )
    with engine.begin() as connection:
        answer = erase_and_record(
            "notification",
            PostgresNotificationEraser(connection),
            request_for(first),
            clock=lambda: WHEN,
        )
    assert answer.tables["channel_preference"] == 0
    assert preferences(engine)[number] == (True, second.value), "B's preference stays B's"
