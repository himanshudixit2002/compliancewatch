"""The worker's components and its consumer handler, on a SQLite inbox and the memory store.

The handler decodes the golden obligation.* examples and queues their notifications; what it
cannot read is dead-lettered through ``FakeProducer``. Postgres, where the queued rows and the
inbox row commit together, is covered by tests/integration/test_notification_schema.py.
"""

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.channels import Channel
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from notification import worker
from notification.application.dispatch import DispatchDue
from notification.application.enqueue import EnqueueNotifications
from notification.application.preferences import SetOptIn
from notification.application.recipients import RecipientRegistration, RegisterRecipient
from notification.application.retention import PurgeExpired
from notification.application.send import SendNow
from notification.domain.ids import RecipientId
from notification.domain.model import NotificationRequest
from notification.domain.notification import DeliveryState
from notification.domain.policy import BatchPolicy
from notification.domain.preferences import ConsentSource
from notification.domain.recipients import BusinessLink, RecipientRole
from notification.domain.repository import UnitOfWork
from notification.infrastructure.memory import MemoryStore
from notification.testing import (
    NOON_IST,
    FakeChannel,
    FakeClock,
    FakeRuleVersionReader,
    notification_settings,
)
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
    sync_handler,
)
from py_common.outbox.testing import FakeProducer

EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
TENANTS = {
    "5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a",
    "9d8c7b6a-5f4e-4d3c-8b2a-1a0f9e8d7c6b",
}
BUSINESS = BusinessId(UUID("6a7b8c9d-0e1f-4a2b-9c3d-4e5f6a7b8c9d"))
PHONE = "+919876543210"
DLQ = "obligation.created.notification.obligations.dlq"


@pytest.fixture
def inbox(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine)
    yield engine
    engine.dispose()


class Setup:
    def __init__(self, inbox: Engine) -> None:
        self.clock = FakeClock()
        self.store = MemoryStore()
        self.producer = FakeProducer()
        for tenant in TENANTS:
            RegisterRecipient(self.store, clock=self.clock).run(
                RecipientRegistration(
                    tenant_id=TenantId(UUID(tenant)),
                    recipient_id=RecipientId.new(),
                    role=RecipientRole.OWNER,
                    addresses=[(Channel.WHATSAPP, PHONE)],
                    businesses=[BusinessLink(BUSINESS, "Acme Traders")],
                )
            )
        SetOptIn(self.store, clock=self.clock).run(
            Channel.WHATSAPP, PHONE, opted_in=True, source=ConsentSource.API
        )
        enqueue = EnqueueNotifications(
            self.store, batch=BatchPolicy(window_seconds=0), clock=self.clock
        )
        handler = worker.obligation_handler(enqueue, unit_on=self.unit_on)
        self.consumer = IdempotentConsumer(
            group_id=worker.GROUP_ID,
            store=SyncProcessedStore(inbox, group_id=worker.GROUP_ID),
            handler=sync_handler(handler),
            producer=self.producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        )

    def unit_on(
        self, connection: Connection, tenant_id: TenantId
    ) -> AbstractContextManager[UnitOfWork]:
        assert connection.in_transaction(), "the handler runs in the inbox transaction"
        return self.store(tenant_id)

    def notifications(self) -> list[Any]:
        return [
            n for tenant in TENANTS for n in self.store.notifications_of(TenantId(UUID(tenant)))
        ]


def record(topic: str, name: str, offset: int = 0, **payload: Any) -> InboundRecord:
    data = json.loads((EXAMPLES / topic / f"{name}.json").read_text(encoding="utf-8"))
    data["payload"].update(payload)
    data["event_id"] = str(uuid4())  # the examples of different topics share their event ids
    return InboundRecord(
        topic=topic, partition=0, offset=offset, key=b"k", value=json.dumps(data).encode()
    )


async def test_the_handler_queues_the_golden_examples_once(inbox: Engine) -> None:
    setup = Setup(inbox)
    queued = [
        record("obligation.created", "filing-with-due-date"),
        record("obligation.due_soon", "seven-days-first-reminder"),
        record("obligation.rescheduled", "deadline-extended-by-notification"),
        record("obligation.closed", "profile-changed"),
    ]
    for item in queued:
        assert await setup.consumer.process(item) is Outcome.PROCESSED, item.topic
    assert await setup.consumer.process(queued[0]) is Outcome.SKIPPED, "a redelivery"
    templates = sorted(n.template_key for n in setup.notifications())
    assert templates == [
        "change_card",
        "obligation_closed",
        "obligation_deadline_extended",
        "obligation_due_soon",
    ]
    assert {n.state for n in setup.notifications()} == {DeliveryState.QUEUED}
    assert setup.producer.sent == []


async def test_events_that_send_nothing_are_marked_processed(inbox: Engine) -> None:
    setup = Setup(inbox)
    for item in (
        record("obligation.rescheduled", "manual"),
        record("obligation.closed", "completed-by-user"),
    ):
        assert await setup.consumer.process(item) is Outcome.PROCESSED
        assert await setup.consumer.process(item) is Outcome.SKIPPED
    assert setup.notifications() == []


async def test_a_malformed_payload_is_dead_lettered(inbox: Engine) -> None:
    setup = Setup(inbox)
    untitled = record("obligation.created", "filing-with-due-date", title="")
    assert await setup.consumer.process(untitled) is Outcome.DEAD
    unreadable = InboundRecord(
        topic="obligation.created", partition=0, offset=1, key=b"k", value=b"not json"
    )
    assert await setup.consumer.process(unreadable) is Outcome.DEAD
    assert setup.producer.topics() == [DLQ, DLQ]
    assert setup.notifications() == []


def test_the_components_are_the_consumer_the_dispatcher_loop_and_the_sweep() -> None:
    settings = notification_settings(
        notification_store="postgres", notification_dispatch_interval_seconds=2.5
    )
    components = worker.components(settings, rules=FakeRuleVersionReader())
    (consumer,) = components.consumers
    assert consumer.group_id == "notification.obligations"
    assert consumer.topics == (
        "obligation.created",
        "obligation.due_soon",
        "obligation.rescheduled",
        "obligation.closed",
    )
    assert consumer.dead_letter_topics()[0] == DLQ
    dispatch, retention = components.periodic
    assert (dispatch.name, dispatch.interval_seconds) == ("notification-dispatch", 2.5)
    assert (retention.name, retention.interval_seconds) == ("notification-retention", None)
    assert retention.next_run is not None
    assert retention.next_run(NOON_IST) == datetime(2026, 9, 28, 21, 30, tzinfo=UTC), "03:00 IST"
    assert components.relays == ()
    assert components.temporal == ()
    with pytest.raises(ValueError, match="postgres"):
        worker.components(notification_settings())


def test_the_dispatch_job_sends_what_is_due() -> None:
    clock = FakeClock()
    store = MemoryStore()
    channel = FakeChannel(clock=clock)
    SetOptIn(store, clock=clock).run(
        Channel.WHATSAPP, PHONE, opted_in=True, source=ConsentSource.API
    )
    dispatch = DispatchDue(
        store,
        store.work_index,
        {Channel.WHATSAPP: channel},
        rules=FakeRuleVersionReader(),
        web_base_url="https://app.example",
        clock=clock,
    )
    job = worker.dispatch_job(dispatch)
    job()
    clock.now = NOON_IST.replace(hour=16)  # 21:30 IST: queued for the morning
    SendNow(store, dispatch, clock=clock).run(
        NotificationRequest(
            notification_id=NotificationId.new(),
            tenant_id=TenantId.new(),
            obligation_id=ObligationId.new(),
            business_id=BUSINESS,
            channel=Channel.WHATSAPP,
            recipient=PHONE,
            template_key="obligation_due_soon",
            params={"business_name": "Acme", "title": "T", "due_date": "D", "steps": "S"},
        )
    )
    clock.advance(12 * 3600)
    job()
    assert len(channel.sent) == 1


def test_the_retention_job_sweeps_every_tenant(caplog: pytest.LogCaptureFixture) -> None:
    store = MemoryStore()
    tenant = TenantId.new()
    RegisterRecipient(store, clock=lambda: NOON_IST).run(
        RecipientRegistration(
            tenant_id=tenant,
            recipient_id=RecipientId.new(),
            role=RecipientRole.OWNER,
            addresses=[(Channel.WHATSAPP, PHONE)],
        )
    )
    purge = PurgeExpired(store, store.work_index, clock=lambda: NOON_IST)
    job = worker.retention_job(purge)
    with caplog.at_level("INFO"):
        job()
    assert "notification.retention_swept" in caplog.text


def test_main_runs_the_components_as_a_worker_process(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(settings: Any, components: Any, *, version: str) -> None:
        seen.update(settings=settings, components=components, version=version)

    monkeypatch.setattr(worker, "run_worker_process", fake_run)
    worker.main()
    assert seen["components"] is worker.components
    assert seen["settings"].service_name == "notification-worker"
