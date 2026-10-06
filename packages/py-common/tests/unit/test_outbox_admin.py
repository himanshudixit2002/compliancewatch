"""Dead outbox rows as an operator sees them, on a SQLite outbox table and in memory: the newest
dead first a page at a time, one row, a dead row put back to pending (and nothing else), and the
payload's summary without its body."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar
from uuid import UUID

import pytest
from sqlalchemy import Connection, Engine, create_engine, update
from sqlalchemy.pool import NullPool

from domain_kernel.events import DomainEvent
from py_common.events import EventMessage, to_message
from py_common.outbox import OutboxWriter, outbox_event
from py_common.outbox.admin import (
    DeadKey,
    DeadRows,
    OutboxAdmin,
    OutboxRow,
    payload_summary,
)
from py_common.outbox.testing import MemoryOutboxStore

T0 = datetime(2000, 1, 3, 6, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentParsed(DomainEvent):
    topic: ClassVar[str] = "document.parsed"
    document_id: str
    title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentDiscovered(DomainEvent):
    topic: ClassVar[str] = "document.discovered"
    document_id: str


def events() -> list[DomainEvent]:
    return [
        *(DocumentParsed(document_id=f"doc-{n}", title="Example " * 50) for n in range(3)),
        DocumentDiscovered(document_id="doc-9"),
    ]


def messages(found: list[DomainEvent]) -> list[EventMessage]:
    return [to_message(event) for event in found]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.sqlite'}", poolclass=NullPool)
    outbox_event.create(engine)
    return engine


class SqlOutbox:
    """The outbox table on SQLite: written as a service writes it, then marked as the relay
    marks it."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(self, found: DomainEvent) -> None:
        with self.engine.begin() as connection:
            OutboxWriter(clock=lambda: T0).write(connection, found, partition_key="example-source")

    def died(self, event_id: UUID, at: datetime) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(outbox_event)
                .where(outbox_event.c.id == event_id)
                .values(status="dead", attempts=8, available_at=at, last_error="Example: away")
            )


def filled_memory(found: list[EventMessage]) -> MemoryOutboxStore:
    store = MemoryOutboxStore()
    for one in found:
        store.add(one, partition_key="example-source", available_at=T0)
    return store


def die_in_memory(store: MemoryOutboxStore, event_id: UUID, at: datetime) -> None:
    row = store.rows[event_id]
    row.status, row.attempts, row.available_at, row.last_error = "dead", 8, at, "Example: away"


def check_rows(admin: DeadRows, found: list[EventMessage]) -> None:
    """What both stores answer once the first three went dead an hour apart (the last one,
    document.discovered, is still pending)."""
    parsed = [one.event_id for one in found[:3]]
    newest = admin.dead(limit=2)
    assert [row.event_id for row in newest] == [parsed[2], parsed[1]], "the newest dead first"
    assert all(row.is_dead and row.dead_at is not None for row in newest)
    after = DeadKey.of(newest[-1])
    assert [row.event_id for row in admin.dead(after=after, limit=2)] == [parsed[0]]
    assert admin.dead(topic="document.discovered") == []
    assert len(admin.dead(topic="document.parsed")) == 3

    row = admin.get(parsed[0])
    assert row is not None
    assert (row.topic, row.partition_key, row.attempts, row.last_error) == (
        "document.parsed",
        "example-source",
        8,
        "Example: away",
    )
    assert row.dead_at == T0 + timedelta(hours=1)
    assert row.payload["document_id"] == "doc-0"
    assert admin.get(UUID(int=1)) is None

    pending = admin.get(found[3].event_id)
    assert pending is not None
    assert (pending.is_dead, pending.dead_at) == (False, None)
    with pytest.raises(ValueError, match="is not dead"):
        DeadKey.of(pending)
    assert not admin.requeue(found[3].event_id, at=T0), "a pending row is not requeued"
    assert not admin.requeue(UUID(int=1), at=T0)

    later = T0 + timedelta(days=1)
    assert admin.requeue(parsed[0], at=later)
    requeued = admin.get(parsed[0])
    assert requeued is not None
    assert (requeued.status, requeued.attempts, requeued.available_at, requeued.last_error) == (
        "pending",
        0,
        later,
        "Example: away",
    ), "due now, its attempts reset, its last error kept until a send succeeds"
    assert not admin.requeue(parsed[0], at=later), "requeued once"
    assert [row.event_id for row in admin.dead()] == [parsed[2], parsed[1]]


def test_the_table_lists_reads_and_requeues_dead_rows(engine: Engine) -> None:
    written = events()
    found = messages(written)
    table = SqlOutbox(engine)
    for event in written:
        table.add(event)
    for hours, message in enumerate(found[:3], start=1):
        table.died(message.event_id, T0 + timedelta(hours=hours))
    with engine.begin() as connection:
        check_rows(OutboxAdmin(connection), found)


def test_memory_answers_the_same() -> None:
    found = messages(events())
    store = filled_memory(found)
    for hours, one in enumerate(found[:3], start=1):
        die_in_memory(store, one.event_id, T0 + timedelta(hours=hours))
    check_rows(store, found)


def test_a_requeue_rolls_back_with_the_callers_transaction(engine: Engine) -> None:
    (written, *_) = events()
    found = to_message(written)
    table = SqlOutbox(engine)
    table.add(written)
    table.died(found.event_id, T0)

    def requeue_then_fail(connection: Connection) -> None:
        assert OutboxAdmin(connection).requeue(found.event_id, at=T0)
        raise RuntimeError("the audit row could not be written")

    with pytest.raises(RuntimeError), engine.begin() as connection:
        requeue_then_fail(connection)
    with engine.connect() as connection:
        row = OutboxAdmin(connection).get(found.event_id)
    assert row is not None
    assert row.status == "dead", "nothing changed"


def test_a_summary_keeps_what_the_event_is_about_and_never_its_body() -> None:
    summary = payload_summary(
        {
            "document_id": "doc-1",
            "source_key": "cbic_notifications",
            "candidate_id": None,
            "outcome": "extracted",
            "doc_type": "x" * 201,
            "title": "Example title",
            "candidate": {"title": "Example"},
            "needs_review": True,
        }
    )
    assert summary == {
        "document_id": "doc-1",
        "source_key": "cbic_notifications",
        "outcome": "extracted",
    }


def test_a_row_of_another_payload_shape_has_an_empty_payload() -> None:
    row = OutboxRow(
        event_id=UUID(int=3),
        topic="document.parsed",
        schema_version="1.1.0",
        partition_key="k",
        tenant_id=None,
        occurred_at=T0,
        created_at=T0,
        status="dead",
        attempts=8,
        available_at=T0,
        published_at=None,
        last_error="",
        message={"payload": "not an object"},
    )
    assert row.payload == {}
