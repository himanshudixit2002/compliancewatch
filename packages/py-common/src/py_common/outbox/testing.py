"""In-memory stores and a scripted producer for tests of code that uses the outbox.

Services test their handlers and producers against these instead of a broker: ``FakeProducer``
records sends and fails on demand, ``MemoryOutboxStore`` and ``MemoryProcessedStore`` behave
like the Postgres stores including rollback of a failed unit of work.
"""

from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from py_common.events import EventMessage
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


class MemoryOutboxStore:
    """A dict of rows; each batch is a snapshot that is applied on a clean exit."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Row] = {}
        self.batches = 0
        self._seq = 0

    def add(self, message: EventMessage, *, partition_key: str, available_at: datetime) -> Row:
        self._seq += 1
        row = Row(message, partition_key, available_at, self._seq)
        self.rows[message.event_id] = row
        return row

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

    async def mark_dead(self, event_id: UUID, *, attempts: int, error: str) -> None:
        row = self._rows[event_id]
        row.status, row.attempts, row.last_error = "dead", attempts, error


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
