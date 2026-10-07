"""The rulebook's erasure consumer: the rulebook holds regulatory data of no tenant, so with the
flag on it erases nothing, lists what it keeps, and answers tenant.data.erased with its audit
entry, so the deletion request can complete; off, it only logs."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.erasure import TenantDataErased
from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from py_common.erasure import erasure_component
from py_common.events import EventMessage, encode, payload_of
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
)
from py_common.outbox.testing import FakeProducer
from rulebook.infrastructure.erasure import MemoryRulebookEraser
from rulebook.infrastructure.memory import MemoryKnowledgeStore

NOW = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)


def consume(
    store: MemoryKnowledgeStore,
    outbox: list[DomainEvent],
    tenant: TenantId,
    path: Path,
    *,
    on: bool,
) -> Outcome:
    component = erasure_component(
        "rulebook",
        lambda _: MemoryRulebookEraser(store, outbox),
        enabled=lambda _: on,
        clock=lambda: NOW,
    )
    engine = create_engine(f"sqlite:///{path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine, checkfirst=True)
    consumer = IdempotentConsumer(
        group_id=component.group_id,
        store=SyncProcessedStore(engine, group_id=component.group_id),
        handler=component.handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
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
    record = InboundRecord(
        topic=message.topic, partition=0, offset=0, key=b"k", value=encode(message)
    )
    return asyncio.run(consumer.process(record))


def test_with_the_flag_on_it_answers_with_what_it_keeps(tmp_path: Path) -> None:
    store, outbox = MemoryKnowledgeStore(), list[DomainEvent]()
    tenant = TenantId.new()
    assert consume(store, outbox, tenant, tmp_path, on=True) is Outcome.PROCESSED
    (answer,) = outbox
    assert isinstance(answer, TenantDataErased)
    assert (answer.service, answer.tenant_id, dict(answer.tables)) == ("rulebook", tenant, {})
    payload = payload_of(answer)
    kept = {item["table"] for item in payload["retained"]}
    assert {"rule_candidate", "review_task", "rule_version_decision"} <= kept
    assert all("no tenant" in item["reason"] for item in payload["retained"][:-1])
    (entry,) = store.audit_entries("tenant.erased")
    assert (entry.tenant_id, entry.actor.label) == (tenant, "system:rulebook")


def test_with_the_flag_off_it_only_logs(tmp_path: Path) -> None:
    store, outbox = MemoryKnowledgeStore(), list[DomainEvent]()
    assert consume(store, outbox, TenantId.new(), tmp_path, on=False) is Outcome.PROCESSED
    assert outbox == []
    assert store.audit_entries("tenant.erased") == []
