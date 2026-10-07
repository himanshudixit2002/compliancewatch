"""The erasure consumers' common handler: it reads the deletion request, erases through the
service's eraser and records the answer, or only logs while the flag is off for the tenant."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import NullPool

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import (
    DELETION_REQUESTED_TOPIC,
    Erased,
    TenantDataErased,
    retained,
)
from domain_kernel.ids import TenantId
from py_common.erasure import (
    ErasureSwitch,
    MalformedDeletionRequestError,
    deletion_request_from,
    erasure_component,
    erasure_handler,
)
from py_common.events import EventMessage, encode, payload_of
from py_common.flags import reset_flags
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
)
from py_common.outbox.testing import FakeProducer
from py_common.settings import Settings

AT = datetime(2000, 1, 12, 4, 30, tzinfo=UTC)
TENANT = TenantId.new()


def message(tenant: TenantId | None = TENANT, **payload: Any) -> EventMessage:
    body: dict[str, Any] = {
        "requested_by": None,
        "requested_at": "2000-01-11T10:00:00+05:30",
        "deadline_at": "2000-02-10T10:00:00+05:30",
        "retain_audit": True,
        "reason": "",
    }
    body.update(payload)
    return EventMessage(
        event_id=uuid4(),
        topic=DELETION_REQUESTED_TOPIC,
        schema_version="1.0.1",
        occurred_at=AT,
        tenant_id=None if tenant is None else tenant.value,
        correlation_id=uuid4(),
        causation_id=None,
        payload=body,
    )


@dataclass
class FakeEraser:
    erased: Erased = field(default_factory=lambda: Erased({"widget": 2}, retained(("log", "x"))))
    tenants: list[TenantId] = field(default_factory=list)
    recorded: list[tuple[TenantDataErased, AuditEntry]] = field(default_factory=list)

    def erase(self, tenant_id: TenantId) -> Erased:
        self.tenants.append(tenant_id)
        return self.erased

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        self.recorded.append((event, entry))


def test_it_reads_the_request_the_message_carries() -> None:
    sent = message()
    request = deletion_request_from(sent)
    assert request.tenant_id == TENANT
    assert request.event_id.value == sent.event_id
    assert request.correlation_id.value == sent.correlation_id
    assert request.deadline_at - request.requested_at == timedelta(days=30)
    assert request.retain_audit


@pytest.mark.parametrize(
    "sent",
    [
        message(tenant=None),
        message(retain_audit="yes"),
        message(deadline_at="soon"),
        message(requested_at="2000-01-11T10:00:00"),
    ],
    ids=["no tenant", "retain_audit", "deadline", "naive"],
)
def test_a_malformed_request_raises(sent: EventMessage) -> None:
    with pytest.raises(MalformedDeletionRequestError):
        deletion_request_from(sent)


def test_with_the_flag_on_it_erases_and_records_the_answer() -> None:
    eraser = FakeEraser()
    handle = erasure_handler("profile", lambda _: eraser, enabled=lambda _: True, clock=lambda: AT)
    sent = message()
    handle(sent, None)  # type: ignore[arg-type]
    assert eraser.tenants == [TENANT]
    [(event, entry)] = eraser.recorded
    assert (event.service, event.tenant_id, event.erased_at) == ("profile", TENANT, AT)
    assert event.causation_id is not None
    assert event.causation_id.value == sent.event_id
    assert payload_of(event)["tables"] == {"widget": 2}
    assert payload_of(event)["retained"] == [{"table": "log", "reason": "x"}]
    assert (entry.action, entry.tenant_id) == ("tenant.erased", TENANT)


def test_with_the_flag_off_it_only_logs() -> None:
    eraser = FakeEraser()
    asked: list[TenantId] = []

    def enabled(tenant: TenantId) -> bool:
        asked.append(tenant)
        return False

    handle = erasure_handler("profile", lambda _: eraser, enabled=enabled)
    handle(message(), None)  # type: ignore[arg-type]
    assert asked == [TENANT]
    assert (eraser.tenants, eraser.recorded) == ([], [])


def test_another_topic_is_ignored() -> None:
    eraser = FakeEraser()
    handle = erasure_handler("profile", lambda _: eraser, enabled=lambda _: True)
    other = message().model_copy(update={"topic": "tenant.created"})
    handle(other, None)  # type: ignore[arg-type]
    assert eraser.tenants == []


def test_the_component_is_the_service_s_erasure_group(tmp_path: Path) -> None:
    eraser = FakeEraser()
    component = erasure_component("obligation", lambda _: eraser, enabled=lambda _: True)
    assert component.group_id == "obligation.erasure"
    assert component.topics == (DELETION_REQUESTED_TOPIC,)
    assert component.dead_letter_topics() == ("tenant.deletion.requested.obligation.erasure.dlq",)
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine)
    consumer = IdempotentConsumer(
        group_id=component.group_id,
        store=SyncProcessedStore(engine, group_id=component.group_id),
        handler=component.handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
    )
    record = InboundRecord(
        topic=DELETION_REQUESTED_TOPIC, partition=0, offset=0, key=b"k", value=encode(message())
    )
    assert asyncio.run(consumer.process(record)) is Outcome.PROCESSED
    assert asyncio.run(consumer.process(record)) is Outcome.SKIPPED, "a redelivery erases once"
    assert len(eraser.tenants) == 1
    with engine.connect() as connection:
        assert connection.execute(select(processed_event.c.consumer_group)).scalars().all() == [
            "obligation.erasure"
        ]


@pytest.fixture
def flags() -> Iterator[None]:
    yield
    reset_flags()


@pytest.mark.usefixtures("flags")
def test_the_switch_reads_the_flag_per_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    other = TenantId.new()
    monkeypatch.setenv("CW_TENANT_ERASURE_ENABLED", "true")
    monkeypatch.setenv("CW_TENANT_ERASURE_TENANTS", str(TENANT))
    switch = ErasureSwitch(Settings(_env_file=None, service_name="profile-worker"))
    assert switch(TENANT)
    assert not switch(other)


@pytest.mark.usefixtures("flags")
def test_the_switch_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CW_TENANT_ERASURE_ENABLED", raising=False)
    monkeypatch.delenv("CW_FLAG_IDENTITY_TENANT_ERASURE", raising=False)
    switch = ErasureSwitch(Settings(_env_file=None, service_name="profile-worker"))
    assert not switch(TENANT)
