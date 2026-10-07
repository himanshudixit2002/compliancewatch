"""Obligation's erasure consumer on the memory store: with the flag on it deletes the tenant's
obligations with their changes, comments and reminders and its applied decisions, keeps the
rule-level cache, and answers tenant.data.erased; off, it only logs. The handler runs through a
consumer on a SQLite inbox, as the worker runs it; tests/integration/test_erasure_postgres.py
runs the Postgres eraser."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.erasure import TenantDataErased
from domain_kernel.ids import TenantId
from obligation.infrastructure.erasure import MemoryObligationEraser
from obligation.infrastructure.memory import MemoryStore
from obligation.testing import tenant_records
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

NOW = datetime(2000, 1, 5, 4, 30, tzinfo=UTC)


def keep(store: MemoryStore, tenant: TenantId, count: int) -> None:
    for index in range(count):
        records = tenant_records(tenant, NOW + timedelta(minutes=index))
        with store(tenant) as uow:
            uow.obligations.add(records.obligation)
            for change in records.changes:
                uow.history.append(change)
            uow.comments.add(records.comment)


def deletion(tenant: TenantId) -> InboundRecord:
    message = EventMessage.model_validate(
        {
            "event_id": "a0b1c2d3-e4f5-4a6b-8c7d-9e0f1a2b3c4d",
            "topic": "tenant.deletion.requested",
            "schema_version": "1.0.1",
            "occurred_at": NOW.isoformat(),
            "tenant_id": str(tenant),
            "correlation_id": "c2d3e4f5-a6b7-4c8d-8e9f-0a1b2c3d4e5f",
            "causation_id": None,
            "payload": {
                "requested_by": None,
                "requested_at": NOW.isoformat(),
                "deadline_at": (NOW + timedelta(days=30)).isoformat(),
                "retain_audit": True,
            },
        }
    )
    return InboundRecord(
        topic=message.topic, partition=0, offset=0, key=b"k", value=encode(message)
    )


def consume(store: MemoryStore, tenant: TenantId, tmp_path: Path, *, on: bool) -> Outcome:
    component = erasure_component(
        "obligation",
        lambda _: MemoryObligationEraser(store),
        enabled=lambda _: on,
        clock=lambda: NOW,
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


def rows_of(store: MemoryStore, tenant: TenantId) -> int:
    return (
        len(store.of_tenant(tenant))
        + sum(change.tenant_id == tenant for change in store.changes)
        + sum(comment.tenant_id == tenant for comment in store.comments)
        + sum(reminder.tenant_id == tenant for reminder in store.reminders)
        + sum(decision.tenant_id == tenant for decision in store.decisions.values())
    )


def test_with_the_flag_on_the_tenant_s_obligations_go(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant, other = TenantId.new(), TenantId.new()
    keep(store, tenant, 3)
    keep(store, other, 2)
    other_rows = rows_of(store, other)
    assert consume(store, tenant, tmp_path, on=True) is Outcome.PROCESSED
    assert rows_of(store, tenant) == 0
    assert tenant not in store.tenants()
    assert rows_of(store, other) == other_rows, "another tenant's obligations stay"
    (answer,) = [e for e in store.events if isinstance(e, TenantDataErased)]
    assert (answer.service, answer.tenant_id) == ("obligation", tenant)
    assert (answer.tables["obligation"], answer.tables["obligation_comment"]) == (3, 3)
    assert answer.tables["obligation_change"] == 3
    assert [item.table for item in answer.retained] == ["rule_version_ref", "outbox_event"]
    (entry,) = [e for e in store.audit if e.action == "tenant.erased"]
    assert entry.actor.label == "system:obligation"


def test_with_the_flag_off_it_only_logs(tmp_path: Path) -> None:
    store = MemoryStore()
    tenant = TenantId.new()
    keep(store, tenant, 1)
    before = rows_of(store, tenant)
    assert consume(store, tenant, tmp_path, on=False) is Outcome.PROCESSED
    assert rows_of(store, tenant) == before
    assert not [e for e in store.events if isinstance(e, TenantDataErased)]
