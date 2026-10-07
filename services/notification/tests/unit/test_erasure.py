"""Notification's erasure consumer on the memory store: with the flag on it deletes the tenant's
notifications with their work, its recipients and directory rows, and the preferences of the
addresses no other tenant holds, keeps the shared ones without the tenant's reference, and
answers tenant.data.erased; off, it only logs. The handler runs through a consumer on a SQLite
inbox, as the worker runs it; tests/integration/test_erasure_postgres.py runs the Postgres
eraser on the same scenario."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.erasure import TenantDataErased
from domain_kernel.ids import BusinessId, ObligationId, TenantId, UserId
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
from py_common.erasure import erasure_component
from py_common.events import EventMessage, encode
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
)
from py_common.outbox.testing import FakeProducer

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
            "event_id": "a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d",
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


def consume(store: MemoryStore, tenant: TenantId, tmp_path: Path, *, on: bool) -> Outcome:
    component = erasure_component(
        "notification",
        lambda _: MemoryNotificationEraser(store),
        enabled=lambda _: on,
        clock=lambda: WHEN,
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine, checkfirst=True)
    consumer = IdempotentConsumer(
        group_id=component.group_id,
        store=SyncProcessedStore(engine, group_id=component.group_id),
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
    assert (Channel.EMAIL, OWN_MAIL) not in preferences, "no one else holds the address"
    assert (Channel.WHATSAPP, OWN_PHONE) not in preferences
    shared = preferences[(Channel.WHATSAPP, SHARED_PHONE)]
    assert (shared.opted_in, shared.set_for_tenant) == (True, None), "kept, without the tenant"
    (answer,) = [e for e in store.events if isinstance(e, TenantDataErased)]
    assert (answer.service, answer.tenant_id) == ("notification", tenant)
    assert answer.tables["notification"] == 2
    assert answer.tables["recipient"] == 2
    assert answer.tables["channel_preference"] == 2
    assert {item.table for item in answer.retained} == {
        "suppression",
        "channel_preference",
        "outbox_event",
    }
    (entry,) = [e for e in store.audit if e.action == "tenant.erased"]
    assert entry.actor.label == "system:notification"


def test_with_the_flag_off_it_only_logs(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant, _ = scenario(store)
    before = held(store, tenant)
    assert consume(store, tenant, tmp_path, on=False) is Outcome.PROCESSED
    assert held(store, tenant) == before
    assert len(store.state.preferences) == 3
