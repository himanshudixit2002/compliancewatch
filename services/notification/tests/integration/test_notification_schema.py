"""Migration 0001 on Postgres: the tables, row-level security by tenant on the tenant tables, the
store's repositories, recipients with their address directory, one row per dedupe key under
concurrent writes, the work index under two dispatchers, the consumer's transaction, queueing and
dispatching a batch and a digest, the retention sweep, and the outbox. Needs Docker.

The store runs as a plain database role, not the container's superuser: a superuser bypasses
row-level security whatever the table says, so the service's runtime role must never be one.
Each test uses its own tenants, and the tests that claim work use their own years and remove
what they leave, because a claim sees every tenant's due work.
"""

import json
import threading
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.ids import (
    BusinessId,
    NotificationId,
    ObligationId,
    RuleVersionId,
    TenantId,
    UserId,
)
from notification import worker
from notification.application.dispatch import DeliveryOutcome, DispatchDue
from notification.application.enqueue import Enqueued, EnqueueNotifications
from notification.application.preferences import SetOptIn
from notification.application.receipts import InboundTime, ReconcileReceipts
from notification.application.recipients import (
    GetRecipient,
    RecipientRegistration,
    RegisterRecipient,
    RemoveRecipient,
)
from notification.application.resend import ResendNotification
from notification.application.retention import PurgeExpired
from notification.application.send import SendNow
from notification.domain.errors import RecipientNotFoundError, ResendNotAllowedError
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.model import NotificationRequest, Outcome
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import Occasion, OccasionKind
from notification.domain.policy import BatchPolicy
from notification.domain.ports import RuleVersionFacts
from notification.domain.preferences import (
    ChannelPreference,
    ConsentSource,
    QuietHours,
    Suppression,
    SuppressionReason,
)
from notification.domain.receipts import Receipt, ReceiptKind
from notification.domain.recipients import BusinessLink, DigestMode, RecipientRole
from notification.domain.repository import DirectoryEntry, PageAfter, WorkEntry
from notification.domain.routing import ObligationNotice
from notification.infrastructure.repository import PostgresUnitOfWorkFactory, SqlAlchemyUnitOfWork
from notification.infrastructure.work_index import PostgresWorkIndex, claim_rows
from notification.testing import NOON_IST, FakeChannel, FakeRuleVersionReader
from py_common.events import EventMessage, to_message
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    SyncProcessedStore,
    outbox_event,
    processed_event,
    sync_handler,
)
from py_common.outbox import Outcome as ConsumerOutcome
from py_common.outbox.testing import FakeProducer

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "notification"
TENANT_TABLES = ("recipient", "recipient_address", "recipient_business", "notification")
SHARED_TABLES = ("channel_preference", "suppression", "address_directory", "work_index")
TABLES = {*TENANT_TABLES, *SHARED_TABLES, "outbox_event", "processed_event", "alembic_version"}
APP_ROLE = "notification_app"
APP_PASSWORD = "app-role-for-tests"
GROUP = "notification.obligations"
LEASE = timedelta(seconds=60)


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
def migrated(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        config = Config(str(SERVICE_DIR / "alembic.ini"))
        command.upgrade(config, "head")
        yield config


@pytest.fixture(scope="module")
def engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    """An engine for a role that owns nothing and is not a superuser, so the policies apply."""
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
        connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "
                f"{SCHEMA} TO {APP_ROLE}"
            )
        )
    admin.dispose()
    url = database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@")
    engine = create_engine(url, pool_size=10)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(app_engine: Engine) -> PostgresUnitOfWorkFactory:
    return PostgresUnitOfWorkFactory(app_engine)


def item(
    n: int,
    tenant: TenantId,
    *,
    at: datetime = NOON_IST,
    business: BusinessId | None = None,
    recipient: RecipientId | None = None,
    **changes: object,
) -> Notification:
    values: dict[str, object] = {
        "tenant_id": tenant,
        "business_id": business or BusinessId.new(),
        "obligation_id": ObligationId.new(),
        "recipient_id": recipient or RecipientId.new(),
        "channel": Channel.WHATSAPP,
        "address": "+919876543210",
        "occasion": OccasionKind.REMINDER,
        "template_key": "obligation_due_soon",
        "language": "en",
        "params": {"title": f"obligation {n}", "steps": ["Reconcile", "File"]},
        "dedupe_key": DedupeKey(uuid4().hex * 2),
        "now": at,
    }
    values.update(changes)
    return Notification.queue(**values)  # type: ignore[arg-type]


def enqueue(factory: PostgresUnitOfWorkFactory, *items: Notification) -> None:
    for notification in items:
        with factory(notification.tenant_id) as unit:
            assert unit.notifications.add_if_absent(notification)
            unit.work.add(WorkEntry.of(notification))


def purge(factory: PostgresUnitOfWorkFactory, tenant: TenantId) -> None:
    with factory(tenant) as unit:
        unit.notifications.purge(datetime(2100, 1, 1, tzinfo=UTC))


def wrote(factory: PostgresUnitOfWorkFactory, phone: str, at: datetime) -> None:
    """The number wrote to us at ``at``: WhatsApp's 24-hour window is open from then."""
    reconcile = ReconcileReceipts(factory, factory.work_index)
    assert reconcile.run(Channel.WHATSAPP, inbound=[InboundTime(phone, at)]).inbound == 1


def test_migration_creates_the_tables_with_row_level_security_where_it_belongs(
    engine: Engine,
) -> None:
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == TABLES
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity, "
                "obj_description(oid, 'pg_class') AS comment FROM pg_class "
                "WHERE relkind = 'r' AND relnamespace = CAST(:schema AS regnamespace)"
            ),
            {"schema": SCHEMA},
        ).all()
        policies = {
            (row.tablename, row.policyname)
            for row in connection.execute(
                text("SELECT tablename, policyname FROM pg_policies WHERE schemaname = :schema"),
                {"schema": SCHEMA},
            )
        }
    by_table = {row.relname: row for row in rows}
    for table in TENANT_TABLES:
        assert (by_table[table].relrowsecurity, by_table[table].relforcerowsecurity) == (
            True,
            True,
        ), table
    assert policies == {(table, f"{table}_tenant_isolation") for table in TENANT_TABLES}
    for table in SHARED_TABLES:
        assert not by_table[table].relrowsecurity, table
        assert by_table[table].comment.startswith("No row-level security: "), table


def test_the_container_user_is_a_superuser_and_the_app_role_is_not(
    engine: Engine, app_engine: Engine
) -> None:
    query = text("SELECT usesuper FROM pg_user WHERE usename = current_user")
    with engine.connect() as connection:
        container_user_is_super: bool = connection.execute(query).scalar_one()
    with app_engine.connect() as connection:
        app_role_is_super: bool = connection.execute(query).scalar_one()
    assert container_user_is_super
    assert not app_role_is_super


def _as_tenant(connection: Connection, tenant: TenantId | None) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :value, true)"),
        {"value": "" if tenant is None else str(tenant)},
    )


def _seed_tenant_rows(connection: Connection, tenant: TenantId) -> None:
    values: dict[str, object] = {
        "tenant": tenant.value,
        "recipient": uuid4(),
        "business": uuid4(),
        "id": uuid4(),
        "key": uuid4().hex * 2,
    }
    connection.execute(
        text(
            "INSERT INTO recipient (id, tenant_id, role, created_at, updated_at) "
            "VALUES (:recipient, :tenant, 'owner', now(), now())"
        ),
        values,
    )
    connection.execute(
        text(
            "INSERT INTO recipient_address (tenant_id, recipient_id, channel, address, position) "
            "VALUES (:tenant, :recipient, 'whatsapp', '+919876543210', 0)"
        ),
        values,
    )
    connection.execute(
        text(
            "INSERT INTO recipient_business (tenant_id, recipient_id, business_id) "
            "VALUES (:tenant, :recipient, :business)"
        ),
        values,
    )
    connection.execute(
        text(
            "INSERT INTO notification (id, tenant_id, business_id, obligation_id, channel, "
            "address, occasion, template_key, language, dedupe_key, state, available_at, "
            "created_at, updated_at) VALUES (:id, :tenant, :business, gen_random_uuid(), "
            "'whatsapp', '+919876543210', 'manual', 'obligation_due_soon', 'en', :key, "
            "'queued', now(), now(), now())"
        ),
        values,
    )


def test_the_app_role_sees_only_the_rows_of_its_tenant(app_engine: Engine) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    with app_engine.begin() as connection:
        _as_tenant(connection, tenant)
        _seed_tenant_rows(connection, tenant)

    def counts(as_tenant: TenantId | None) -> dict[str, int]:
        with app_engine.begin() as connection:
            _as_tenant(connection, as_tenant)
            return {
                table: connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id IN (:a, :b)"),
                    {"a": tenant.value, "b": other.value},
                ).scalar_one()
                for table in TENANT_TABLES
            }

    assert counts(tenant) == dict.fromkeys(TENANT_TABLES, 1)
    assert counts(other) == dict.fromkeys(TENANT_TABLES, 0)
    assert counts(None) == dict.fromkeys(TENANT_TABLES, 0), "no setting, no rows"

    def write_as_the_other_tenant() -> None:
        with app_engine.begin() as connection:
            _as_tenant(connection, tenant)
            _seed_tenant_rows(connection, other)

    with pytest.raises(DBAPIError, match="row-level security"):
        write_as_the_other_tenant()


def test_the_repositories_round_trip_under_row_level_security(
    factory: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    base = datetime(2001, 3, 1, 6, 30, tzinfo=UTC)
    business, recipient, obligation = BusinessId.new(), RecipientId.new(), ObligationId.new()
    early = item(
        1, tenant, at=base, business=business, recipient=recipient, obligation_id=obligation
    )
    late = item(
        2,
        tenant,
        at=base + timedelta(minutes=10),
        business=business,
        recipient=recipient,
        obligation_id=obligation,
        params={"title": "newest"},
    )
    theirs = item(3, other, at=base, business=business)
    enqueue(factory, early, late, theirs)

    with factory(tenant) as unit:
        notifications = unit.notifications
        assert not notifications.add_if_absent(item(4, tenant, dedupe_key=early.dedupe_key))
        assert not notifications.add_if_absent(item(5, tenant, notification_id=early.id))
        assert not notifications.add_if_absent(item(6, tenant, dedupe_key=theirs.dedupe_key)), (
            "keys are unique across tenants"
        )
        assert notifications.get(early.id) == early
        assert notifications.get(theirs.id) is None, "row-level security hides the other tenant"
        assert notifications.by_dedupe_key(late.dedupe_key) == late
        due = notifications.due_for(recipient, Channel.WHATSAPP, base + timedelta(minutes=1))
        assert [n.id for n in due] == [early.id]
        assert notifications.latest_params(obligation) == {"title": "newest"}
        first_page = notifications.page(business, limit=1)
        assert [n.id for n in first_page] == [late.id]
        after = PageAfter(first_page[0].created_at, first_page[0].id)
        assert [n.id for n in notifications.page(business, limit=5, after=after)] == [early.id]
        assert notifications.page(business, state=DeliveryState.SENT, limit=5) == []

        dispatch = DispatchId.new()
        sent, _ = early.sent(dispatch, "wamid.round-trip", base + timedelta(minutes=2))
        notifications.save(sent)
        unit.work.complete(early.id, provider_message_id="wamid.round-trip")
        assert notifications.get(early.id) == sent
        assert [n.id for n in notifications.by_dispatch(dispatch)] == [early.id]
        assert [n.id for n in notifications.by_provider_message("wamid.round-trip")] == [early.id]
        assert notifications.by_provider_message("") == []
        assert notifications.page(business, state=DeliveryState.SENT, limit=5) == [sent]

    work = PostgresWorkIndex(factory.engine)
    assert work.tenant_for_provider_message("wamid.round-trip") == tenant
    assert work.tenant_for_provider_message("wamid.unknown") is None
    assert work.tenant_for_provider_message("") is None
    claimed = work.claim(limit=10, now=base + timedelta(minutes=30), lease=LEASE)
    assert {e.id for e in claimed} == {late.id, theirs.id}, "the index spans tenants"
    with factory(tenant) as unit:
        unit.work.reschedule(late.id, base + timedelta(hours=2))
    again = work.claim(limit=10, now=base + timedelta(minutes=30, seconds=30), lease=LEASE)
    assert again == [], "a rescheduled entry waits, a leased one is held"
    assert tenant in work.tenants()

    with factory(tenant) as unit:
        assert unit.notifications.strip_params(base + timedelta(minutes=5)) == 1
        assert unit.notifications.get(early.id) == replace(sent, params={})
        assert unit.notifications.purge(base + timedelta(minutes=5)) == 1
        assert unit.notifications.get(early.id) is None
    with engine.connect() as connection:
        left: int = connection.execute(
            text("SELECT count(*) FROM work_index WHERE id = :id"), {"id": early.id.value}
        ).scalar_one()
    assert left == 0, "the work entry goes with its notification"
    purge(factory, tenant)
    purge(factory, other)


def test_consents_inbound_times_and_suppressions(factory: PostgresUnitOfWorkFactory) -> None:
    phone, other_phone = "+919800000001", "+919800000002"
    preference = ChannelPreference(
        Channel.WHATSAPP,
        phone,
        True,
        ConsentSource.WHATSAPP_KEYWORD,
        NOON_IST,
        language="hi",
        quiet_hours=QuietHours.parse("22:00", "07:00"),
    )
    with factory.shared() as unit:
        unit.preferences.save(preference)
        unit.preferences.record_inbound(Channel.WHATSAPP, phone, NOON_IST)
        unit.preferences.record_inbound(Channel.WHATSAPP, phone, NOON_IST - LEASE)
        unit.preferences.record_inbound(Channel.WHATSAPP, other_phone, NOON_IST)
        unit.suppressions.add(
            Suppression(Channel.EMAIL, "gone@example.com", SuppressionReason.BOUNCE, NOON_IST)
        )
        unit.suppressions.add(
            Suppression(
                Channel.EMAIL, "gone@example.com", SuppressionReason.COMPLAINT, NOON_IST, "abuse"
            )
        )
    opted_out = ChannelPreference(
        Channel.WHATSAPP, phone, False, ConsentSource.WHATSAPP_KEYWORD, NOON_IST + LEASE
    )
    with factory(TenantId.new()) as unit:
        assert unit.preferences.get(Channel.WHATSAPP, phone) == preference
        assert unit.preferences.get(Channel.WHATSAPP, other_phone) is None, "inbound only"
        assert unit.preferences.last_inbound_at(Channel.WHATSAPP, phone) == NOON_IST
        assert unit.preferences.last_inbound_at(Channel.WHATSAPP, "+919800000003") is None
        unit.preferences.save(opted_out)
        assert unit.preferences.get(Channel.WHATSAPP, phone) == opted_out
        assert unit.preferences.last_inbound_at(Channel.WHATSAPP, phone) == NOON_IST
        found = unit.suppressions.get(Channel.EMAIL, "gone@example.com")
        assert found is not None
        assert (found.reason, found.detail) == (SuppressionReason.COMPLAINT, "abuse")
        assert unit.suppressions.remove(Channel.EMAIL, "gone@example.com")
        assert not unit.suppressions.remove(Channel.EMAIL, "gone@example.com")
        assert unit.suppressions.get(Channel.EMAIL, "gone@example.com") is None


def test_recipients_and_their_directory_entries_under_row_level_security(
    factory: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    tenant, other = TenantId.new(), TenantId.new()
    business, client = BusinessId.new(), BusinessId.new()
    register = RegisterRecipient(factory, clock=lambda: NOON_IST)
    owner_id = RecipientId.new()
    owner = register.run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=owner_id,
            role=RecipientRole.OWNER,
            user_id=UserId.new(),
            language="hi",
            addresses=[(Channel.WHATSAPP, "+91 98765 11111"), (Channel.EMAIL, "Owner@Acme.in")],
            businesses=[BusinessLink(business, "Acme Traders")],
        )
    )
    staff = register.run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=RecipientId.new(),
            role=RecipientRole.STAFF,
            addresses=[(Channel.WHATSAPP, "919876511111")],
            businesses=[BusinessLink(business), BusinessLink(client, "Client")],
        )
    )
    same_id = register.run(
        RecipientRegistration(
            tenant_id=other,
            recipient_id=owner_id,
            role=RecipientRole.CA_ADMIN,
            org_label="Sharma & Co",
            addresses=[(Channel.EMAIL, "desk@sharma.example")],
            businesses=[BusinessLink(business)],
        )
    )
    get = GetRecipient(factory)
    assert get.run(tenant, owner_id) == owner
    assert get.run(other, owner_id) == same_id, "one id in two tenants"
    assert same_id.by_digest
    with factory(tenant) as unit:
        followers = unit.recipients.for_business(business)
        assert sorted(r.id.value for r in followers) == sorted([owner_id.value, staff.id.value])
        assert unit.recipients.for_business(client) == [staff]
    with factory(other) as unit:
        assert unit.recipients.for_business(business) == [same_id]
        assert unit.recipients.for_business(client) == []
    with factory.shared() as unit:
        assert unit.directory.lookup(Channel.WHATSAPP, "+919876511111") == sorted(
            [DirectoryEntry(tenant, owner_id), DirectoryEntry(tenant, staff.id)],
            key=lambda entry: entry.recipient_id.value,
        )
    assert {tenant, other} <= set(PostgresWorkIndex(factory.engine).tenants())

    later = NOON_IST + timedelta(days=1)
    moved = RegisterRecipient(factory, clock=lambda: later).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=owner_id,
            role=RecipientRole.OWNER,
            digest_mode=DigestMode.DAILY,
            addresses=[(Channel.EMAIL, "owner@acme.in")],
            businesses=[BusinessLink(client, "Client")],
        )
    )
    assert (moved.created_at, moved.updated_at) == (NOON_IST, later)
    assert get.run(tenant, owner_id) == moved
    with factory.shared() as unit:
        assert unit.directory.lookup(Channel.WHATSAPP, "+919876511111") == [
            DirectoryEntry(tenant, staff.id)
        ]
        assert unit.directory.lookup(Channel.EMAIL, "owner@acme.in") == [
            DirectoryEntry(tenant, owner_id)
        ]

    RemoveRecipient(factory).run(tenant, owner_id)
    with pytest.raises(RecipientNotFoundError):
        get.run(tenant, owner_id)
    assert get.run(other, owner_id) == same_id, "the other tenant's recipient stays"
    with pytest.raises(RecipientNotFoundError):
        RemoveRecipient(factory).run(tenant, owner_id)
    with engine.connect() as connection:
        left: dict[str, int] = {
            table: connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t AND {column} = :id"),
                {"t": tenant.value, "id": owner_id.value},
            ).scalar_one()
            for table, column in (
                ("recipient", "id"),
                ("recipient_address", "recipient_id"),
                ("recipient_business", "recipient_id"),
                ("address_directory", "recipient_id"),
            )
        }
    assert left == dict.fromkeys(left, 0), "addresses, links and entries go with the recipient"


def test_concurrent_writes_of_one_dedupe_key_keep_one_row(
    factory: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    tenant = TenantId.new()
    key = DedupeKey(uuid4().hex * 2)
    writers = 8
    start = threading.Barrier(writers)
    results: list[bool] = []
    lock = threading.Lock()

    def write() -> None:
        candidate = item(0, tenant, dedupe_key=key)
        start.wait()
        with factory(tenant) as unit:
            added = unit.notifications.add_if_absent(candidate)
        with lock:
            results.append(added)

    threads = [threading.Thread(target=write) for _ in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(results) == [False] * (writers - 1) + [True]
    with engine.connect() as connection:
        rows: int = connection.execute(
            text("SELECT count(*) FROM notification WHERE dedupe_key = :key"), {"key": key.value}
        ).scalar_one()
    assert rows == 1
    purge(factory, tenant)


def test_two_dispatchers_never_claim_one_entry(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine
) -> None:
    tenant = TenantId.new()
    base = datetime(2000, 1, 1, tzinfo=UTC)
    entries = [item(n, tenant, at=base + timedelta(seconds=n)) for n in range(10)]
    enqueue(factory, *entries)
    now = base + timedelta(minutes=1)

    first = app_engine.connect()
    second = app_engine.connect()
    try:
        first.begin()
        mine = claim_rows(first, limit=4, now=now, lease=LEASE)
        second.begin()
        theirs = claim_rows(second, limit=10, now=now, lease=LEASE)
        first.commit()
        second.commit()
    finally:
        first.close()
        second.close()
    assert [e.id for e in mine] == [e.id for e in entries[:4]], "oldest first"
    assert {e.id for e in theirs} == {e.id for e in entries[4:]}, "locked rows are skipped"
    work = PostgresWorkIndex(app_engine)
    assert work.claim(limit=10, now=now, lease=LEASE) == [], "every entry is leased"

    racing: list[list[WorkEntry]] = []
    lock = threading.Lock()
    start = threading.Barrier(4)

    def claim() -> None:
        start.wait()
        got = list(work.claim(limit=3, now=now + LEASE, lease=LEASE))
        with lock:
            racing.append(got)

    threads = [threading.Thread(target=claim) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    claimed = [entry.id for batch in racing for entry in batch]
    assert len(claimed) == len(set(claimed)) == 10, "after the lease, each entry exactly once"
    with pytest.raises(ValueError, match="limit"):
        work.claim(limit=0, now=now, lease=LEASE)
    purge(factory, tenant)


def test_a_renewal_holds_only_what_the_dispatcher_still_holds(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine
) -> None:
    tenant = TenantId.new()
    base = datetime(1999, 1, 1, tzinfo=UTC)
    first, second = (item(n, tenant, at=base + timedelta(seconds=n)) for n in range(2))
    enqueue(factory, first, second)
    work = PostgresWorkIndex(app_engine)
    now = base + timedelta(minutes=1)
    claimed = work.claim(limit=10, now=now, lease=LEASE)
    assert [e.lease_until for e in claimed] == [now + LEASE] * 2, "a claim names its lease"
    later = now + timedelta(seconds=45)
    renewed = work.renew(claimed, now=later, lease=LEASE)
    assert renewed is not None
    assert [(e.id, e.lease_until) for e in renewed] == [(e.id, later + LEASE) for e in claimed]
    assert work.renew(claimed, now=later, lease=LEASE) is None, "that lease is not held any more"
    assert work.claim(limit=10, now=now + LEASE, lease=LEASE) == [], "renewed past it"

    lapsed = later + LEASE
    (taken,) = work.claim(limit=1, now=lapsed, lease=LEASE)
    assert work.renew(renewed, now=lapsed, lease=LEASE) is None, "another dispatcher took one"
    (rest,) = [e for e in renewed if e.id != taken.id]
    held = work.renew([rest], now=lapsed, lease=LEASE)
    assert held is not None, "a lease that ran out is renewed while nobody took the entry"
    with factory(tenant) as unit:
        unit.work.complete(taken.id)
    assert work.renew([taken], now=lapsed, lease=LEASE) is None, "completed"
    assert work.renew([], now=lapsed, lease=LEASE) == []

    # A renewal that waits on a claim's row lock finds the row under the claim's lease.
    expired = lapsed + LEASE
    outcome: list[Sequence[WorkEntry] | None] = []
    holder = app_engine.connect()
    try:
        holder.begin()
        assert [e.id for e in claim_rows(holder, limit=10, now=expired, lease=LEASE)] == [rest.id]
        renewal = threading.Thread(
            target=lambda: outcome.append(work.renew(held, now=expired, lease=LEASE))
        )
        renewal.start()
        renewal.join(timeout=1)
        assert renewal.is_alive(), "the renewal waits for the claim's transaction"
        holder.commit()
        renewal.join(timeout=30)
    finally:
        holder.close()
    assert outcome == [None]
    purge(factory, tenant)


def test_a_delay_keeps_the_planned_moment_the_pending_age_counts_from(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine
) -> None:
    tenant = TenantId.new()
    base = datetime(1990, 1, 1, tzinfo=UTC)
    first, second = (item(n, tenant, at=base + timedelta(seconds=n)) for n in range(2))
    upcoming = item(2, tenant, at=base, available_at=base + timedelta(hours=1))
    enqueue(factory, first, second, upcoming)
    work = PostgresWorkIndex(app_engine)
    assert work.oldest_due(base - timedelta(seconds=1)) is None, "nothing due yet"
    assert work.oldest_due(base + timedelta(minutes=5)) == base

    claimed = work.claim(limit=10, now=base + timedelta(minutes=1), lease=LEASE)
    assert [(e.id, e.planned_at) for e in claimed] == [
        (first.id, first.available_at),
        (second.id, second.available_at),
    ], "a claim names the planned moment"
    retry_at = base + timedelta(minutes=6)
    quiet_until = base + timedelta(hours=20)
    with factory(tenant) as unit:
        unit.work.reschedule(first.id, retry_at, delay=True)
        unit.work.reschedule(second.id, quiet_until)
    with app_engine.connect() as connection:
        rows = {
            row.id: (row.available_at, row.planned_at)
            for row in connection.execute(
                text(
                    "SELECT id, available_at, planned_at FROM work_index "
                    "WHERE id IN (:first, :second)"
                ),
                {"first": first.id.value, "second": second.id.value},
            )
        }
    assert rows == {
        first.id.value: (retry_at, base),
        second.id.value: (quiet_until, quiet_until),
    }, "a delay keeps the planned moment, quiet hours move it"
    later = base + timedelta(minutes=90)
    assert work.oldest_due(later) == base, "the retry still counts from its planned moment"
    (again,) = work.claim(limit=10, now=retry_at, lease=LEASE)
    assert (again.id, again.available_at, again.planned_at) == (first.id, retry_at, base)
    with factory(tenant) as unit:
        unit.work.complete(first.id)
    assert work.oldest_due(later) == upcoming.available_at, "done work is not pending"
    purge(factory, tenant)


def _record(message: EventMessage, offset: int) -> InboundRecord:
    return InboundRecord(
        topic="obligation.created",
        partition=0,
        offset=offset,
        key=b"k",
        value=message.model_dump_json().encode(),
    )


async def test_the_consumer_commits_the_notification_with_its_inbox_row(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine, engine: Engine
) -> None:
    tenant = TenantId.new()
    planned: dict[UUID, Notification] = {}

    def message_for(notification: Notification) -> EventMessage:
        """Any event of the tenant carries the message; the handler looks up what to write."""
        _, (event,) = notification.sent(DispatchId.new(), "", NOON_IST)
        message = to_message(event)
        planned[message.event_id] = notification
        return message

    def handle(message: EventMessage, connection: Connection) -> None:
        notification = planned[message.event_id]
        with SqlAlchemyUnitOfWork.on_connection(connection, notification.tenant_id) as unit:
            assert unit.notifications.add_if_absent(notification)
            unit.work.add(WorkEntry.of(notification))
            _, events = notification.sent(DispatchId.new(), "", NOON_IST)
            for event in events:
                unit.events.publish(event)

    def explode(message: EventMessage, connection: Connection) -> None:
        handle(message, connection)
        raise RuntimeError("cannot handle")

    producer = FakeProducer()

    def consumer(handler: object) -> IdempotentConsumer:
        return IdempotentConsumer(
            group_id=GROUP,
            store=SyncProcessedStore(app_engine, group_id=GROUP),
            handler=sync_handler(handler),  # type: ignore[arg-type]
            producer=producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        )

    kept, dropped = item(1, tenant), item(2, tenant)
    good, bad = message_for(kept), message_for(dropped)
    assert await consumer(handle).process(_record(good, 0)) is ConsumerOutcome.PROCESSED
    assert await consumer(handle).process(_record(good, 1)) is ConsumerOutcome.SKIPPED
    assert await consumer(explode).process(_record(bad, 2)) is ConsumerOutcome.DEAD

    with engine.connect() as connection:
        stored: set[UUID] = set(
            connection.execute(
                text("SELECT id FROM notification WHERE tenant_id = :tenant"),
                {"tenant": tenant.value},
            ).scalars()
        )
        work: set[UUID] = set(
            connection.execute(
                text("SELECT id FROM work_index WHERE tenant_id = :tenant"),
                {"tenant": tenant.value},
            ).scalars()
        )
        inbox: set[UUID] = set(
            connection.execute(
                select(processed_event.c.event_id).where(processed_event.c.consumer_group == GROUP)
            ).scalars()
        )
        outbox: Sequence[str] = (
            connection.execute(
                select(outbox_event.c.topic).where(outbox_event.c.tenant_id == tenant.value)
            )
            .scalars()
            .all()
        )
    assert stored == work == {kept.id.value}, "the failed handler's rows rolled back"
    assert good.event_id in inbox
    assert bad.event_id not in inbox, "the inbox row rolled back with them"
    assert list(outbox) == ["notification.sent"]
    assert producer.topics() == [f"obligation.created.{GROUP}.dlq"]
    with app_engine.connect() as idle, pytest.raises(ValueError, match="inside a transaction"):
        SqlAlchemyUnitOfWork.on_connection(idle, tenant).__enter__()
    purge(factory, tenant)


def outbox_topics(engine: Engine, tenant: TenantId) -> list[str]:
    with engine.connect() as connection:
        topics: Sequence[str] = (
            connection.execute(
                select(outbox_event.c.topic)
                .where(outbox_event.c.tenant_id == tenant.value)
                .order_by(outbox_event.c.topic)
            )
            .scalars()
            .all()
        )
    return list(topics)


def test_sends_write_their_outbox_rows_for_sent_and_failed(
    factory: PostgresUnitOfWorkFactory, engine: Engine
) -> None:
    tenant = TenantId.new()
    channel = FakeChannel(clock=lambda: NOON_IST)
    dispatch = DispatchDue(
        factory,
        factory.work_index,
        {Channel.WHATSAPP: channel},
        rules=FakeRuleVersionReader(),
        web_base_url="https://app.example",
        clock=lambda: NOON_IST,
    )
    send = SendNow(factory, dispatch, clock=lambda: NOON_IST)
    SetOptIn(factory, clock=lambda: NOON_IST).run(
        Channel.WHATSAPP, "+91 98765 00001", opted_in=True, source=ConsentSource.API
    )
    wrote(factory, "+919876500001", NOON_IST)

    def request(**changes: object) -> NotificationRequest:
        values: dict[str, object] = {
            "notification_id": NotificationId.new(),
            "tenant_id": tenant,
            "obligation_id": ObligationId.new(),
            "business_id": BusinessId.new(),
            "channel": Channel.WHATSAPP,
            "recipient": "919876500001",
            "template_key": "obligation_due_soon",
            "params": {"business_name": "Acme", "title": "T", "due_date": "D", "steps": "S"},
        }
        values.update(changes)
        return NotificationRequest(**values)  # type: ignore[arg-type]

    ok = request()
    assert send.run(ok).outcome is Outcome.SENT
    assert send.run(ok).outcome is Outcome.DUPLICATE
    channel.fail_next = 1
    retried = request()
    assert send.run(retried).outcome is Outcome.FAILED

    with factory(tenant) as unit:
        stored = unit.notifications.get(ok.notification_id)
        waiting = unit.notifications.get(retried.notification_id)
    assert stored is not None
    assert (stored.state, stored.address, stored.provider_message_id) == (
        DeliveryState.SENT,
        "+919876500001",
        "fake-1",
    )
    assert waiting is not None
    assert (waiting.state, waiting.attempts, waiting.available_at) == (
        DeliveryState.QUEUED,
        1,
        NOON_IST + timedelta(seconds=60),
    )
    with engine.connect() as connection:
        work = connection.execute(
            text("SELECT status, lease_until FROM work_index WHERE id = :id"),
            {"id": retried.notification_id.value},
        ).one()
    assert (work.status, work.lease_until) == ("pending", None), "the send's lease ended"
    assert PostgresWorkIndex(factory.engine).tenant_for_provider_message("fake-1") == tenant
    assert outbox_topics(engine, tenant) == ["notification.failed", "notification.sent"]
    purge(factory, tenant)


def test_queued_notifications_go_out_as_one_batch(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine, engine: Engine
) -> None:
    tenant, business, rule = TenantId.new(), BusinessId.new(), RuleVersionId.new()
    base = datetime(2003, 3, 3, 6, 30, tzinfo=UTC)
    clock = [base]
    RegisterRecipient(factory, clock=lambda: base).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=RecipientId.new(),
            role=RecipientRole.OWNER,
            addresses=[(Channel.WHATSAPP, "+91 98765 00003")],
            businesses=[BusinessLink(business, "Acme Traders")],
        )
    )
    SetOptIn(factory, clock=lambda: base).run(
        Channel.WHATSAPP, "+919876500003", opted_in=True, source=ConsentSource.API
    )
    wrote(factory, "+919876500003", base)
    enqueue = EnqueueNotifications(
        factory, batch=BatchPolicy(window_seconds=300), clock=lambda: clock[0]
    )

    def notice(occasion: Occasion, template_key: str, title: str) -> ObligationNotice:
        return ObligationNotice(
            tenant_id=tenant,
            business_id=business,
            occasion=occasion,
            template_key=template_key,
            params={
                "title": title,
                "rule_version_id": str(rule),
                "close_reason": "profile_changed",
            },
        )

    card = notice(Occasion.change_card(ObligationId.new(), rule), "change_card", "File GSTR-3B")
    assert enqueue.run(card) == Enqueued(queued=1)
    clock[0] = base + timedelta(seconds=60)
    closure = notice(Occasion.closure(ObligationId.new()), "obligation_closed", "File CMP-08")
    assert enqueue.run(closure) == Enqueued(queued=1)
    assert enqueue.run(card) == Enqueued(duplicates=1), "the store keeps the key unique"

    channel = FakeChannel(clock=lambda: base + timedelta(seconds=300))
    dispatch = DispatchDue(
        factory,
        PostgresWorkIndex(app_engine),
        {Channel.WHATSAPP: channel},
        rules=FakeRuleVersionReader(),
        web_base_url="https://app.example",
        clock=lambda: base + timedelta(seconds=300),
    )
    (delivery,) = dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SENT
    (message,) = channel.sent
    assert message.body.startswith(
        "Updates for Acme Traders. Changes to your compliance calendar: 2. New - File GSTR-3B; "
        "Closed - File CMP-08."
    )
    with factory(tenant) as unit:
        sent = unit.notifications.page(business, limit=10)
    assert {n.state for n in sent} == {DeliveryState.SENT}
    assert len({n.dispatch_id for n in sent}) == 1
    assert outbox_topics(engine, tenant) == ["notification.sent", "notification.sent"]
    assert PostgresWorkIndex(app_engine).tenant_for_provider_message("fake-1") == tenant

    leased = item(1, tenant, at=base + timedelta(days=1))
    with factory(tenant) as unit:
        assert unit.notifications.add_if_absent(leased)
        unit.work.add(WorkEntry.of(leased, lease_until=leased.available_at + LEASE))
    work = PostgresWorkIndex(app_engine)
    assert work.claim(limit=10, now=leased.available_at, lease=LEASE) == [], "leased when added"
    assert [e.id for e in work.claim(limit=10, now=leased.available_at + LEASE, lease=LEASE)] == [
        leased.id
    ]
    purge(factory, tenant)


def test_a_ca_firms_notifications_wait_for_one_digest(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine, engine: Engine
) -> None:
    tenant, acme, beta = TenantId.new(), BusinessId.new(), BusinessId.new()
    noon = datetime(2007, 7, 7, 6, 30, tzinfo=UTC)
    nine = datetime(2007, 7, 8, 3, 30, tzinfo=UTC)
    RegisterRecipient(factory, clock=lambda: noon).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=RecipientId.new(),
            role=RecipientRole.CA_ADMIN,
            org_label="Rao & Co",
            addresses=[(Channel.WHATSAPP, "+91 98765 00007")],
            businesses=[BusinessLink(acme, "Acme Traders"), BusinessLink(beta, "Beta Foods")],
        )
    )
    SetOptIn(factory, clock=lambda: noon).run(
        Channel.WHATSAPP, "+919876500007", opted_in=True, source=ConsentSource.API
    )
    wrote(factory, "+919876500007", noon)
    enqueue = EnqueueNotifications(factory, clock=lambda: noon)
    for business, title in ((acme, "File GSTR-3B"), (beta, "File FSSAI returns")):
        rule = RuleVersionId.new()
        notice = ObligationNotice(
            tenant_id=tenant,
            business_id=business,
            occasion=Occasion.change_card(ObligationId.new(), rule),
            template_key="change_card",
            params={"title": title, "rule_version_id": str(rule)},
        )
        assert enqueue.run(notice) == Enqueued(queued=1)
    with engine.connect() as connection:
        held = connection.execute(
            text(
                "SELECT n.state, w.kind, w.available_at FROM notification n "
                "JOIN work_index w ON w.id = n.id WHERE n.tenant_id = :tenant"
            ),
            {"tenant": tenant.value},
        ).all()
    assert {(row.state, row.kind, row.available_at) for row in held} == {
        ("digest_pending", "digest_item", nine)
    }

    channel = FakeChannel(clock=lambda: nine)
    dispatch = DispatchDue(
        factory,
        PostgresWorkIndex(app_engine),
        {Channel.WHATSAPP: channel},
        rules=FakeRuleVersionReader(),
        web_base_url="https://app.example",
        clock=lambda: nine,
    )
    (delivery,) = dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SENT
    (message,) = channel.sent
    assert message.body.startswith("Client digest for Rao & Co. Updates: 2. Clients: 2.")
    with factory(tenant) as unit:
        sent = [*unit.notifications.page(acme, limit=5), *unit.notifications.page(beta, limit=5)]
    assert {n.state for n in sent} == {DeliveryState.SENT}
    assert len({n.dispatch_id for n in sent}) == 1
    purge(factory, tenant)


def test_receipts_move_notifications_on_and_a_failed_one_is_resent(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine, engine: Engine
) -> None:
    tenant, business = TenantId.new(), BusinessId.new()
    now = datetime(2009, 9, 9, 6, 30, tzinfo=UTC)
    later = now + timedelta(minutes=5)
    RegisterRecipient(factory, clock=lambda: now).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=RecipientId.new(),
            role=RecipientRole.OWNER,
            addresses=[(Channel.WHATSAPP, "+91 98765 00009"), (Channel.EMAIL, "nine@example.com")],
            businesses=[BusinessLink(business, "Acme Traders")],
        )
    )
    for channel, address in (
        (Channel.WHATSAPP, "+919876500009"),
        (Channel.EMAIL, "nine@example.com"),
    ):
        SetOptIn(factory, clock=lambda: now).run(
            channel, address, opted_in=True, source=ConsentSource.API
        )
    wrote(factory, "+919876500009", now)
    whatsapp, email = FakeChannel(clock=lambda: now), FakeChannel(clock=lambda: later)
    dispatch = DispatchDue(
        factory,
        PostgresWorkIndex(app_engine),
        {Channel.WHATSAPP: whatsapp, Channel.EMAIL: email},
        rules=FakeRuleVersionReader(),
        web_base_url="https://app.example",
        clock=lambda: now,
    )
    enqueue = EnqueueNotifications(factory, batch=BatchPolicy(window_seconds=0), clock=lambda: now)

    def card(title: str) -> NotificationId:
        rule = RuleVersionId.new()
        obligation = ObligationId.new()
        enqueue.run(
            ObligationNotice(
                tenant_id=tenant,
                business_id=business,
                occasion=Occasion.change_card(obligation, rule),
                template_key="change_card",
                params={"title": title, "rule_version_id": str(rule)},
            )
        )
        (delivery,) = dispatch.run()
        assert delivery.outcome is DeliveryOutcome.SENT
        return delivery.notification_ids[0]

    read_one, failed_one = card("File GSTR-3B"), card("File GSTR-1")
    reconcile = ReconcileReceipts(factory, PostgresWorkIndex(app_engine), clock=lambda: later)
    reconciled = reconcile.run(
        Channel.WHATSAPP,
        [
            Receipt("fake-1", ReceiptKind.READ, later),
            Receipt("fake-2", ReceiptKind.FAILED, later, error="whatsapp 131026: Undeliverable"),
            Receipt("wamid.not-ours", ReceiptKind.DELIVERED, later),
        ],
    )
    assert (reconciled.applied, reconciled.unknown) == (2, 1)
    with factory(tenant) as unit:
        read = unit.notifications.get(read_one)
        failed = unit.notifications.get(failed_one)
        (fallback,) = unit.notifications.page(business, state=DeliveryState.QUEUED, limit=5)
    assert read is not None
    assert (read.state, read.read_at) == (DeliveryState.READ, later)
    assert failed is not None
    assert (failed.state, failed.error) == (DeliveryState.FAILED, "whatsapp 131026: Undeliverable")
    assert (fallback.channel, fallback.fallback_of) == (Channel.EMAIL, failed_one)
    assert outbox_topics(engine, tenant) == [
        "notification.failed",
        "notification.sent",
        "notification.sent",
    ]

    resent = ResendNotification(factory, clock=lambda: later).run(tenant, failed_one)
    assert (resent.state, resent.attempts) == (DeliveryState.QUEUED, 0)
    with engine.connect() as connection:
        work = connection.execute(
            text("SELECT status, available_at FROM work_index WHERE id = :id"),
            {"id": failed_one.value},
        ).one()
    assert (work.status, work.available_at) == ("pending", later), "due again with it"
    with pytest.raises(ResendNotAllowedError):
        ResendNotification(factory, clock=lambda: later).run(tenant, read_one)
    purge(factory, tenant)


def test_the_retention_sweep_visits_each_tenant_under_row_level_security(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine, engine: Engine
) -> None:
    first, second = TenantId.new(), TenantId.new()
    base = datetime(1999, 1, 1, 6, 30, tzinfo=UTC)
    ancient = [item(1, first, at=base), item(2, second, at=base)]
    month_old = base + timedelta(days=700)
    sent_long_ago = item(3, first, at=month_old)
    still_waiting = item(4, second, at=month_old)
    enqueue(factory, *ancient, sent_long_ago, still_waiting)
    with factory(first) as unit:
        sent, _ = sent_long_ago.sent(DispatchId.new(), "wamid.retention", month_old)
        unit.notifications.save(sent)
        unit.work.complete(sent.id, provider_message_id="wamid.retention")
    now = base + timedelta(days=740)

    swept = PurgeExpired(factory, PostgresWorkIndex(app_engine), clock=lambda: now).run()
    assert (swept.purged, swept.stripped) == (2, 1)
    assert swept.tenants >= 2, "the tenants come from the tables without row-level security"
    with factory(first) as unit:
        assert unit.notifications.get(ancient[0].id) is None
        kept = unit.notifications.get(sent_long_ago.id)
    assert kept is not None
    assert (kept.state, kept.params) == (DeliveryState.SENT, {})
    with factory(second) as unit:
        assert unit.notifications.get(ancient[1].id) is None
        waiting = unit.notifications.get(still_waiting.id)
    assert waiting is not None
    assert waiting.params == still_waiting.params, "a pending notification keeps its values"
    with engine.connect() as connection:
        left: int = connection.execute(
            text("SELECT count(*) FROM work_index WHERE id IN (:first, :second)"),
            {"first": ancient[0].id.value, "second": ancient[1].id.value},
        ).scalar_one()
    assert left == 0, "the work entries go with their notifications"
    purge(factory, first)
    purge(factory, second)


EXAMPLES = SERVICE_DIR.parents[1] / "packages" / "contracts" / "events" / "examples"


async def test_the_worker_queues_an_obligation_event_in_its_inbox_transaction(
    factory: PostgresUnitOfWorkFactory, app_engine: Engine, engine: Engine
) -> None:
    tenant, business = TenantId.new(), BusinessId.new()
    now = datetime(2005, 5, 5, 6, 30, tzinfo=UTC)
    RegisterRecipient(factory, clock=lambda: now).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=RecipientId.new(),
            role=RecipientRole.OWNER,
            addresses=[(Channel.WHATSAPP, "+91 98765 00005")],
            businesses=[BusinessLink(business, "Acme Traders")],
        )
    )
    SetOptIn(factory, clock=lambda: now).run(
        Channel.WHATSAPP, "+919876500005", opted_in=True, source=ConsentSource.API
    )
    wrote(factory, "+919876500005", now)
    data = json.loads(
        (EXAMPLES / "obligation.created" / "filing-with-due-date.json").read_text(encoding="utf-8")
    )
    data.update(event_id=str(uuid4()), tenant_id=str(tenant))
    data["payload"].update(obligation_id=str(uuid4()), business_id=str(business))
    message = EventMessage.model_validate(data)
    enqueue = EnqueueNotifications(factory, batch=BatchPolicy(window_seconds=0), clock=lambda: now)
    consumer = IdempotentConsumer(
        group_id=worker.GROUP_ID,
        store=SyncProcessedStore(app_engine, group_id=worker.GROUP_ID),
        handler=sync_handler(worker.obligation_handler(enqueue)),
        producer=FakeProducer(),
    )
    assert await consumer.process(_record(message, 10)) is ConsumerOutcome.PROCESSED
    assert await consumer.process(_record(message, 11)) is ConsumerOutcome.SKIPPED

    with factory(tenant) as unit:
        (queued,) = unit.notifications.page(business, limit=10)
    assert (queued.template_key, queued.state) == ("change_card", DeliveryState.QUEUED)
    with engine.connect() as connection:
        inbox = connection.execute(
            select(processed_event.c.event_id).where(
                processed_event.c.consumer_group == worker.GROUP_ID,
                processed_event.c.event_id == message.event_id,
            )
        ).all()
    assert len(inbox) == 1

    channel = FakeChannel(clock=lambda: now)
    facts = RuleVersionFacts(
        title="File FORM GSTR-3B every month",
        summary="A monthly filer furnishes FORM GSTR-3B.",
        effective_from=date(2026, 4, 1),
    )
    rule = RuleVersionId(UUID(data["payload"]["rule_version_id"]))
    dispatch = DispatchDue(
        factory,
        PostgresWorkIndex(app_engine),
        {Channel.WHATSAPP: channel},
        rules=FakeRuleVersionReader({rule: facts}),
        web_base_url="https://app.example",
        clock=lambda: now,
    )
    (delivery,) = dispatch.run()
    assert delivery.outcome is DeliveryOutcome.SENT
    (message_sent,) = channel.sent
    assert message_sent.body.startswith(
        "What changed for Acme Traders: A monthly filer furnishes FORM GSTR-3B. It applies to "
        "you from 1 Apr 2026."
    )
    assert outbox_topics(engine, tenant) == ["notification.sent"]
    purge(factory, tenant)


def test_downgrade_and_upgrade(migrated: Config, engine: Engine) -> None:
    command.downgrade(migrated, "base")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == {"alembic_version"}
    command.upgrade(migrated, "head")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == TABLES
