"""In-memory stores, a scripted producer and a topic reader for tests of code that uses the
outbox.

Services test their handlers and producers against these instead of a broker: ``FakeProducer``
records sends and fails on demand, ``FakeConsumer`` reads topics from the start as a reader with
no consumer group would (what a ``FakeProducer`` sent, or records given to it), and
``MemoryOutboxStore`` and ``MemoryProcessedStore`` behave like the Postgres stores including
rollback of a failed unit of work. ``MemoryOutboxStore`` also answers ``DeadRows``
(``py_common.outbox.admin``): its dead rows, one row, and a dead row put back to pending.
"""

from collections import defaultdict
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from py_common.events import EventMessage
from py_common.outbox.admin import DeadKey, OutboxRow
from py_common.outbox.consumer import InboundRecord
from py_common.outbox.replay import UnknownTopicError
from py_common.outbox.store import ClaimedMessage, OutboxBatch, UnitOfWork


@dataclass
class Sent:
    topic: str
    key: bytes
    value: bytes
    headers: list[tuple[str, bytes]]

    def header(self, name: str) -> bytes | None:
        return next((value for key, value in self.headers if key == name), None)


class FakeProducer:
    """Records sends; fails the next ``fail_times[topic]`` sends to a topic."""

    def __init__(self) -> None:
        self.sent: list[Sent] = []
        self.fail_times: dict[str, int] = defaultdict(int)

    async def send(
        self, topic: str, *, key: bytes, value: bytes, headers: Sequence[tuple[str, bytes]]
    ) -> None:
        if self.fail_times[topic] > 0:
            self.fail_times[topic] -= 1
            raise ConnectionError(f"broker unavailable for {topic}")
        self.sent.append(Sent(topic, key, value, list(headers)))

    def topics(self) -> list[str]:
        return [item.topic for item in self.sent]


class FakeConsumer:
    """Topics held in memory, read from their first offset by a reader with no consumer group
    (``py_common.outbox.replay.TopicReader``): each record on partition 0, offsets in the order
    they came. ``of(producer)`` holds what a ``FakeProducer`` sent; ``append`` adds one more and
    ``create`` adds empty topics. A topic it does not hold is ``UnknownTopicError``, as on a
    broker that has no such topic."""

    def __init__(self, records: Iterable[InboundRecord] = ()) -> None:
        self.topics: dict[str, list[InboundRecord]] = {}
        self.reads: list[str] = []
        for record in records:
            self.topics.setdefault(record.topic, []).append(record)

    @classmethod
    def of(cls, producer: FakeProducer) -> "FakeConsumer":
        consumer = cls()
        for sent in producer.sent:
            consumer.append(sent.topic, sent.key, sent.value, sent.headers)
        return consumer

    def append(
        self, topic: str, key: bytes | None, value: bytes, headers: Sequence[tuple[str, bytes]]
    ) -> InboundRecord:
        held = self.topics.setdefault(topic, [])
        record = InboundRecord(
            topic=topic,
            partition=0,
            offset=len(held),
            key=key,
            value=value,
            headers=tuple(headers),
        )
        held.append(record)
        return record

    def create(self, *topics: str) -> "FakeConsumer":
        """These topics exist on the broker, empty unless something was sent to them."""
        for topic in topics:
            self.topics.setdefault(topic, [])
        return self

    async def read(self, topic: str) -> list[InboundRecord]:
        self.reads.append(topic)
        if topic not in self.topics:
            raise UnknownTopicError(f"no topic {topic} on the broker")
        return list(self.topics[topic])

    async def has_topic(self, topic: str) -> bool:
        return topic in self.topics


@dataclass
class Row:
    message: EventMessage
    partition_key: str
    available_at: datetime
    seq: int
    status: str = "pending"
    attempts: int = 0
    published_at: datetime | None = None
    last_error: str = ""
    created_at: datetime | None = None

    def view(self) -> OutboxRow:
        """The row as ``py_common.outbox.admin`` reads one."""
        message = self.message
        return OutboxRow(
            event_id=message.event_id,
            topic=message.topic,
            schema_version=message.schema_version,
            partition_key=self.partition_key,
            tenant_id=message.tenant_id,
            occurred_at=message.occurred_at,
            created_at=self.created_at or self.available_at,
            status=self.status,
            attempts=self.attempts,
            available_at=self.available_at,
            published_at=self.published_at,
            last_error=self.last_error,
            message=message.model_dump(mode="json"),
        )


class MemoryOutboxStore:
    """A dict of rows; each batch is a snapshot that is applied on a clean exit."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Row] = {}
        self.batches = 0
        self._seq = 0

    def add(self, message: EventMessage, *, partition_key: str, available_at: datetime) -> Row:
        self._seq += 1
        row = Row(message, partition_key, available_at, self._seq, created_at=available_at)
        self.rows[message.event_id] = row
        return row

    def dead(
        self, *, topic: str | None = None, after: DeadKey | None = None, limit: int = 50
    ) -> Sequence[OutboxRow]:
        """The dead rows, the newest dead first, then by id from the highest, after ``after``."""
        found = sorted(
            (
                row.view()
                for row in self.rows.values()
                if row.status == "dead" and topic in (None, row.message.topic)
            ),
            key=lambda row: (row.available_at, row.event_id.int),
            reverse=True,
        )
        if after is not None:
            start = (after.dead_at, after.event_id.int)
            found = [row for row in found if (row.available_at, row.event_id.int) < start]
        return found[:limit]

    def get(self, event_id: UUID, *, for_update: bool = False) -> OutboxRow | None:
        """One row; ``for_update`` changes nothing in memory, where nothing runs beside."""
        row = self.rows.get(event_id)
        return None if row is None else row.view()

    def requeue(self, event_id: UUID, *, at: datetime) -> bool:
        """A dead row back to pending with its attempts reset and due at ``at``."""
        row = self.rows.get(event_id)
        if row is None or row.status != "dead":
            return False
        row.status, row.attempts, row.available_at = "pending", 0, at
        return True

    @asynccontextmanager
    async def _batch(self) -> AsyncIterator[OutboxBatch]:
        self.batches += 1
        yield MemoryBatch(self.rows)

    def batch(self) -> AbstractAsyncContextManager[OutboxBatch]:
        return self._batch()

    async def pending(self) -> int:
        return sum(1 for row in self.rows.values() if row.status == "pending")

    def statuses(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for row in self.rows.values():
            counts[row.status] += 1
        return dict(counts)


class MemoryBatch:
    def __init__(self, rows: dict[UUID, Row]) -> None:
        self._rows = rows

    async def claim(self, *, limit: int, now: datetime) -> Sequence[ClaimedMessage]:
        due = sorted(
            (
                row
                for row in self._rows.values()
                if row.status == "pending" and row.available_at <= now
            ),
            key=lambda row: (row.available_at, row.seq),
        )
        return [
            ClaimedMessage(
                id=row.message.event_id,
                topic=row.message.topic,
                schema_version=row.message.schema_version,
                partition_key=row.partition_key,
                attempts=row.attempts,
                message=row.message.model_dump(mode="json"),
            )
            for row in due[:limit]
        ]

    async def mark_published(self, event_id: UUID, *, at: datetime) -> None:
        row = self._rows[event_id]
        row.status, row.published_at, row.last_error = "published", at, ""

    async def mark_retry(
        self, event_id: UUID, *, attempts: int, available_at: datetime, error: str
    ) -> None:
        row = self._rows[event_id]
        row.attempts, row.available_at, row.last_error = attempts, available_at, error

    async def mark_dead(self, event_id: UUID, *, attempts: int, error: str, at: datetime) -> None:
        row = self._rows[event_id]
        row.status, row.attempts, row.last_error = "dead", attempts, error
        row.available_at = at


@dataclass
class MemoryUnit:
    """A transaction: marks are staged and committed only when the block exits cleanly."""

    committed: set[UUID]
    staged: set[UUID] = field(default_factory=set)
    writes: list[Any] = field(default_factory=list)

    async def already_processed(self, event_id: UUID) -> bool:
        return event_id in self.committed

    async def mark_processed(self, event_id: UUID, *, topic: str) -> None:
        self.staged.add(event_id)


class MemoryProcessedStore:
    def __init__(self) -> None:
        self.processed: set[UUID] = set()
        self.units = 0
        self.rolled_back = 0
        self.committed_writes: list[Any] = []

    @asynccontextmanager
    async def _unit(self) -> AsyncIterator[UnitOfWork]:
        self.units += 1
        unit = MemoryUnit(self.processed)
        try:
            yield unit
        except BaseException:
            self.rolled_back += 1
            raise
        self.processed |= unit.staged
        self.committed_writes.extend(unit.writes)

    def unit(self) -> AbstractAsyncContextManager[UnitOfWork]:
        return self._unit()
