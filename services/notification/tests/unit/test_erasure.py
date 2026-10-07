"""Notification's erasure consumer on the memory store: with the flag on it deletes the tenant's
notifications with their work, its recipients and directory rows, and the opt-ins of the
addresses no other tenant holds; keeps the opt-outs, the shared ones and those another tenant's
user set, without the tenant's reference, and answers tenant.data.erased; off, it only logs.
An event identity did not send erases nothing, and a late obligation event of an erased tenant
queues nothing. The handler runs through a consumer on a SQLite
inbox, as the worker runs it; tests/integration/test_erasure_postgres.py runs the Postgres
eraser on the same scenario."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.erasure import TenantDataErased
from domain_kernel.ids import BusinessId, EventId, ObligationId, TenantId, UserId
from notification.application.enqueue import EnqueueNotifications
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.domain.ids import RecipientId
from notification.domain.notification import Notification
from notification.domain.occasions import OccasionKind
from notification.domain.preferences import ConsentSource
from notification.domain.recipients import BusinessLink, RecipientRole
from notification.domain.repository import UnitOfWorkFactory, WorkEntry
from notification.infrastructure.erasure import MemoryNotificationEraser
from notification.infrastructure.memory import MemoryStore
from notification.worker import GROUP_ID, obligation_handler
from py_common.erasure import erasure_component
from py_common.erasure_testing import FakeIdentity
from py_common.events import EventMessage, encode
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
    read_first_store,
    sync_handler,
)
from py_common.outbox.testing import FakeProducer

SENT = EventId(UUID("a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d"))
EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
CREATED = EXAMPLES / "obligation.created" / "filing-with-due-date.json"
EXAMPLE_BUSINESS = BusinessId(UUID("6a7b8c9d-0e1f-4a2b-9c3d-4e5f6a7b8c9d"))
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


def deletion(tenant: TenantId) -> InboundRecord:
    message = EventMessage.model_validate(
        {
            "event_id": str(SENT),
            "topic": "tenant.deletion.requested",
            "schema_version": "1.0.1",
            "occurred_at": WHEN.isoformat(),
            "tenant_id": str(tenant),
            "correlation_id": "c2d3e4f5-a6b7-4c8d-8e9f-0a1b2c3d4e5f",
            "causation_id": None,
            "payload": {
                "requested_by": None,
                "requested_at": WHEN.isoformat(),
                "deadline_at": (WHEN + timedelta(days=30)).isoformat(),
                "retain_audit": True,
            },
        }
    )
    return InboundRecord(
        topic=message.topic, partition=0, offset=0, key=b"k", value=encode(message)
    )


def consume(
    store: MemoryStore,
    tenant: TenantId,
    tmp_path: Path,
    *,
    on: bool,
    identity: FakeIdentity | None = None,
) -> Outcome:
    component = erasure_component(
        "notification",
        lambda _: MemoryNotificationEraser(store),
        enabled=lambda _: on,
        verifier=identity or FakeIdentity(SENT),
        clock=lambda: WHEN,
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine, checkfirst=True)
    consumer = IdempotentConsumer(
        group_id=component.group_id,
        store=read_first_store(engine, component.group_id),
        handler=component.handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    return asyncio.run(consumer.process(deletion(tenant)))


def held(store: MemoryStore, tenant: TenantId) -> dict[str, int]:
    state = store.state
    return {
        "notification": len(store.notifications_of(tenant)),
        "work": sum(row.entry.tenant_id == tenant for row in state.work.values()),
        "recipient": sum(key[0] == tenant for key in state.recipients),
        "directory": sum(key[2] == tenant for key in state.directory),
    }


def test_with_the_flag_on_the_tenant_s_notifications_go_and_shared_preferences_stay(
    tmp_path: Path,
) -> None:
    store = MemoryStore()
    tenant, other = scenario(store)
    theirs = held(store, other)
    assert consume(store, tenant, tmp_path, on=True) is Outcome.PROCESSED
    assert held(store, tenant) == dict.fromkeys(
        ("notification", "work", "recipient", "directory"), 0
    )
    assert held(store, other) == theirs, "another tenant's notifications stay"
    preferences = store.state.preferences
    assert (Channel.WHATSAPP, OWN_PHONE) not in preferences, "no one else holds the address"
    opt_out = preferences[(Channel.EMAIL, OWN_MAIL)]
    assert (opt_out.opted_in, opt_out.set_for_tenant) == (False, None), "the opt-out stays"
    shared = preferences[(Channel.WHATSAPP, SHARED_PHONE)]
    assert (shared.opted_in, shared.set_for_tenant) == (True, None), "kept, without the tenant"
    (answer,) = [e for e in store.events if isinstance(e, TenantDataErased)]
    assert (answer.service, answer.tenant_id) == ("notification", tenant)
    assert answer.tables["notification"] == 2
    assert answer.tables["recipient"] == 2
    assert answer.tables["channel_preference"] == 3, "one deleted, two without the tenant"
    assert {item.table for item in answer.retained} == {
        "suppression",
        "channel_preference",
        "erased_tenant",
        "outbox_event",
    }
    assert store.erased.is_erased(tenant)
    (entry,) = [e for e in store.audit if e.action == "tenant.erased"]
    assert entry.actor.label == "system:notification"


def test_a_preference_another_tenant_s_user_set_stays(tmp_path: Path) -> None:
    """The review's case: B's user opts in on the web for a number only A holds in the
    directory; A's erasure keeps B's preference."""
    store = MemoryStore()
    first, second = TenantId.new(), TenantId.new()
    register(store, first, [(Channel.WHATSAPP, SHARED_PHONE)])
    register(store, second, [(Channel.WHATSAPP, OWN_PHONE)])
    SetOptIn(store, clock=lambda: WHEN).run(
        Channel.WHATSAPP,
        SHARED_PHONE,
        opted_in=True,
        source=ConsentSource.WEB_ONBOARDING,
        set_for_tenant=second,
    )
    assert consume(store, first, tmp_path, on=True) is Outcome.PROCESSED
    kept = store.state.preferences[(Channel.WHATSAPP, SHARED_PHONE)]
    assert (kept.opted_in, kept.set_for_tenant) == (True, second), "B's preference stays B's"
    (answer,) = [e for e in store.events if isinstance(e, TenantDataErased)]
    assert answer.tables["channel_preference"] == 0
    assert "channel_preference" in {item.table for item in answer.retained}


def test_a_keyword_opt_out_no_tenant_set_stays(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant = TenantId.new()
    register(store, tenant, [(Channel.WHATSAPP, OWN_PHONE)])
    SetOptIn(store, clock=lambda: WHEN).run(
        Channel.WHATSAPP, OWN_PHONE, opted_in=False, source=ConsentSource.WHATSAPP_KEYWORD
    )
    assert consume(store, tenant, tmp_path, on=True) is Outcome.PROCESSED
    stop = store.state.preferences[(Channel.WHATSAPP, OWN_PHONE)]
    assert (stop.opted_in, stop.set_for_tenant) == (False, None), "STOP outlives the account"


def test_an_event_identity_did_not_send_erases_nothing(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant, _ = scenario(store)
    before = held(store, tenant)
    refused = consume(store, tenant, tmp_path, on=True, identity=FakeIdentity(EventId.new()))
    assert refused is Outcome.REFUSED
    assert held(store, tenant) == before
    assert len(store.state.preferences) == 3
    assert [e.action for e in store.audit if e.tenant_id == tenant][-1] == "tenant.erasure_refused"


def test_a_late_obligation_event_of_an_erased_tenant_queues_nothing(tmp_path: Path) -> None:
    store = MemoryStore()
    erased, kept = TenantId.new(), TenantId.new()
    for tenant, phone in ((erased, OWN_PHONE), (kept, SHARED_PHONE)):
        RegisterRecipient(store, clock=lambda: WHEN).run(
            RecipientRegistration(
                tenant_id=tenant,
                recipient_id=RecipientId.new(),
                role=RecipientRole.OWNER,
                user_id=UserId.new(),
                addresses=[(Channel.WHATSAPP, phone)],
                businesses=[BusinessLink(EXAMPLE_BUSINESS, "Example Traders")],
            )
        )
        SetOptIn(store, clock=lambda: WHEN).run(
            Channel.WHATSAPP, phone, opted_in=True, source=ConsentSource.API
        )
    store.erased.mark(
        TenantDataErased(
            tenant_id=erased,
            service="notification",
            deletion_event_id=EventId.new(),
            erased_at=WHEN,
        )
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'obligations.sqlite'}", poolclass=NullPool)
    processed_event.create(engine, checkfirst=True)
    handler = obligation_handler(
        EnqueueNotifications(store, clock=lambda: WHEN),
        unit_on=lambda _, tenant_id: store(tenant_id),
        erased_on=lambda _: store.erased,
    )
    consumer = IdempotentConsumer(
        group_id=GROUP_ID,
        store=SyncProcessedStore(engine, group_id=GROUP_ID),
        handler=sync_handler(handler),
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )

    def created(tenant: TenantId) -> InboundRecord:
        message = json.loads(CREATED.read_text(encoding="utf-8"))
        message.update(tenant_id=str(tenant), event_id=str(uuid4()))
        return InboundRecord(
            topic="obligation.created",
            partition=0,
            offset=0,
            key=b"k",
            value=json.dumps(message).encode(),
        )

    assert asyncio.run(consumer.process(created(kept))) is Outcome.PROCESSED
    assert len(store.notifications_of(kept)) == 1, "the handler queues for a tenant not erased"
    assert asyncio.run(consumer.process(created(erased))) is Outcome.PROCESSED, "marked processed"
    assert store.notifications_of(erased) == [], "nothing of the erased tenant is queued"
