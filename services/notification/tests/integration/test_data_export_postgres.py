"""The tenant's data export on Postgres, as the notification service's own role cw_notification
(not the container's superuser, which would bypass row-level security): two tenants' recipients,
preferences and notifications, and the export of one holds only its own rows, the preferences of
its own recipients' addresses included and no other address's. Needs Docker."""

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
from domain_kernel.ids import BusinessId, ObligationId, TenantId, UserId
from notification.application.export import ExportTenantData
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.domain.ids import RecipientId
from notification.domain.notification import Notification
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import ConsentSource
from notification.domain.recipients import BusinessLink, RecipientRole
from notification.domain.repository import WorkEntry
from notification.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "notification"
WHEN = datetime(2000, 1, 3, 6, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def app_engine(database_url: str) -> Iterator[Engine]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
    apply_roles(database_url)
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


@pytest.fixture
def factory(app_engine: Engine) -> PostgresUnitOfWorkFactory:
    return PostgresUnitOfWorkFactory(app_engine)


def register(
    factory: PostgresUnitOfWorkFactory,
    tenant: TenantId,
    addresses: list[tuple[Channel, str]],
    *,
    at: datetime = WHEN,
) -> RecipientId:
    recipient_id = RecipientId.new()
    RegisterRecipient(factory, clock=lambda: at).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=recipient_id,
            role=RecipientRole.OWNER,
            user_id=UserId.new(),
            addresses=addresses,
            businesses=[BusinessLink(BusinessId.new(), "Example Traders")],
        )
    )
    return recipient_id


def notify(
    factory: PostgresUnitOfWorkFactory, tenant: TenantId, address: str, *, at: datetime = WHEN
) -> Notification:
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
        params={"title": "Example obligation", "steps": ["Reconcile", "File"]},
        dedupe_key=DedupeKey(uuid4().hex * 2),
        now=at,
    )
    with factory(tenant) as unit:
        assert unit.notifications.add_if_absent(notification)
        unit.work.add(WorkEntry.of(notification))
    return notification


def test_the_export_as_the_service_role_holds_only_the_tenants_rows(
    factory: PostgresUnitOfWorkFactory,
) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    phone, mail = "+919876543220", "owner.a@example.com"
    other_phone, stranger = "+919876543221", "+919876543222"
    inbound_only = "+919876543223"
    register(factory, tenant, [(Channel.WHATSAPP, phone), (Channel.EMAIL, mail)])
    register(factory, tenant, [(Channel.WHATSAPP, inbound_only)], at=WHEN + timedelta(hours=1))
    register(factory, other, [(Channel.WHATSAPP, other_phone)])
    opt_in = SetOptIn(factory, clock=lambda: WHEN)
    for channel, address in (
        (Channel.WHATSAPP, phone),
        (Channel.EMAIL, mail),
        (Channel.WHATSAPP, other_phone),
        (Channel.WHATSAPP, stranger),
    ):
        opt_in.run(channel, address, opted_in=True, source=ConsentSource.API)
    with factory.shared() as unit:
        unit.preferences.record_inbound(Channel.WHATSAPP, inbound_only, WHEN)
    mine = [
        notify(factory, tenant, phone, at=WHEN + timedelta(minutes=2)),
        notify(factory, tenant, phone, at=WHEN + timedelta(minutes=1)),
    ]
    notify(factory, other, other_phone)

    export = ExportTenantData(factory, clock=lambda: WHEN).run(tenant)
    assert set(export.sections) == {"recipients", "preferences", "notifications"}
    recipients = export.sections["recipients"]
    assert [r["addresses"][0]["address"] for r in recipients] == [phone, inbound_only]
    assert {r["tenant_id"] for r in recipients} == {str(tenant.value)}
    preferences = export.sections["preferences"]
    assert [(p["channel"], p["address"]) for p in preferences] == [
        ("email", mail),
        ("whatsapp", phone),
        ("whatsapp", inbound_only),
    ]
    assert preferences[2] == {
        "channel": "whatsapp",
        "address": inbound_only,
        "opted_in": None,
        "source": None,
        "language": "en",
        "quiet_hours_start": "21:00",
        "quiet_hours_end": "08:00",
        "updated_at": None,
        "last_inbound_at": WHEN.isoformat(),
    }
    assert [n["id"] for n in export.sections["notifications"]] == [
        str(mine[1].id.value),
        str(mine[0].id.value),
    ], "oldest first"
    text_of = repr(export.sections)
    assert str(other.value) not in text_of
    assert other_phone not in text_of
    assert stranger not in text_of

    paged = ExportTenantData(factory, clock=lambda: WHEN, page_size=1).run(tenant)
    assert paged.sections == export.sections, "pages of one row join to the same export"
