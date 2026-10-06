"""Store protocols the relay and the consumer work against, and their Postgres implementations.

The protocols keep the relay and consumer logic testable with in-memory fakes; the Postgres
classes hold the SQL. A relay batch is one transaction: rows are claimed with
``FOR UPDATE SKIP LOCKED`` so several relay processes can share a table, and every mark inside
the batch commits together. A row marked dead keeps the moment it went dead in ``available_at``
(``py_common.outbox.admin`` reads it as ``dead_at``). A consumer unit of work is one transaction
too: the handler's own writes, the ``processed_event`` row and the inbox check commit or roll
back as one.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from py_common.outbox.schema import (
    STATUS_DEAD,
    STATUS_PENDING,
    STATUS_PUBLISHED,
    outbox_event,
    processed_event,
)

MAX_ERROR_LENGTH = 2000


@dataclass(frozen=True, slots=True)
class ClaimedMessage:
    """A pending outbox row the relay is about to publish."""

    id: UUID
    topic: str
    schema_version: str
    partition_key: str
    attempts: int
    message: dict[str, Any]


class OutboxBatch(Protocol):
    async def claim(self, *, limit: int, now: datetime) -> Sequence[ClaimedMessage]: ...

    async def mark_published(self, event_id: UUID, *, at: datetime) -> None: ...

    async def mark_retry(
        self, event_id: UUID, *, attempts: int, available_at: datetime, error: str
    ) -> None: ...

    async def mark_dead(self, event_id: UUID, *, attempts: int, error: str, at: datetime) -> None:
        """The row went dead at ``at``: its ``available_at`` keeps that moment, since the relay
        never claims a dead row."""
        ...


class OutboxStore(Protocol):
    def batch(self) -> AbstractAsyncContextManager[OutboxBatch]: ...

    async def pending(self) -> int:
        """Rows still to publish: due now or backing off after a failed send."""
        ...


class UnitOfWork(Protocol):
    """One consumer transaction. Handlers that need the database narrow it to the concrete type."""

    async def already_processed(self, event_id: UUID) -> bool: ...

    async def mark_processed(self, event_id: UUID, *, topic: str) -> None: ...


class ProcessedStore(Protocol):
    def unit(self) -> AbstractAsyncContextManager[UnitOfWork]: ...


def truncate_error(error: str) -> str:
    return error if len(error) <= MAX_ERROR_LENGTH else error[: MAX_ERROR_LENGTH - 3] + "..."


class PostgresOutboxBatch:
    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection

    async def claim(self, *, limit: int, now: datetime) -> Sequence[ClaimedMessage]:
        statement = (
            select(
                outbox_event.c.id,
                outbox_event.c.topic,
                outbox_event.c.schema_version,
                outbox_event.c.partition_key,
                outbox_event.c.attempts,
                outbox_event.c.message,
            )
            .where(outbox_event.c.status == STATUS_PENDING, outbox_event.c.available_at <= now)
            .order_by(outbox_event.c.available_at, outbox_event.c.created_at, outbox_event.c.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self.connection.execute(statement)).all()
        return [
            ClaimedMessage(
                id=row.id,
                topic=row.topic,
                schema_version=row.schema_version,
                partition_key=row.partition_key,
                attempts=row.attempts,
                message=row.message,
            )
            for row in rows
        ]

    async def mark_published(self, event_id: UUID, *, at: datetime) -> None:
        await self.connection.execute(
            update(outbox_event)
            .where(outbox_event.c.id == event_id)
            .values(status=STATUS_PUBLISHED, published_at=at, last_error="")
        )

    async def mark_retry(
        self, event_id: UUID, *, attempts: int, available_at: datetime, error: str
    ) -> None:
        await self.connection.execute(
            update(outbox_event)
            .where(outbox_event.c.id == event_id)
            .values(attempts=attempts, available_at=available_at, last_error=truncate_error(error))
        )

    async def mark_dead(self, event_id: UUID, *, attempts: int, error: str, at: datetime) -> None:
        await self.connection.execute(
            update(outbox_event)
            .where(outbox_event.c.id == event_id)
            .values(
                status=STATUS_DEAD,
                attempts=attempts,
                available_at=at,
                last_error=truncate_error(error),
            )
        )


class PostgresOutboxStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def _batch(self) -> AsyncIterator[OutboxBatch]:
        async with self._engine.begin() as connection:
            yield PostgresOutboxBatch(connection)

    def batch(self) -> AbstractAsyncContextManager[OutboxBatch]:
        return self._batch()

    async def pending(self) -> int:
        statement = (
            select(func.count())
            .select_from(outbox_event)
            .where(outbox_event.c.status == STATUS_PENDING)
        )
        async with self._engine.connect() as connection:
            return int((await connection.execute(statement)).scalar_one())


class PostgresUnitOfWork:
    """Exposes the transaction's connection so a handler writes its own tables in it."""

    def __init__(self, connection: AsyncConnection, group_id: str) -> None:
        self.connection = connection
        self.group_id = group_id

    async def already_processed(self, event_id: UUID) -> bool:
        statement = select(processed_event.c.event_id).where(
            processed_event.c.consumer_group == self.group_id,
            processed_event.c.event_id == event_id,
        )
        return (await self.connection.execute(statement)).first() is not None

    async def mark_processed(self, event_id: UUID, *, topic: str) -> None:
        await self.connection.execute(
            insert(processed_event).values(
                consumer_group=self.group_id, event_id=event_id, topic=topic
            )
        )


class PostgresProcessedStore:
    def __init__(self, engine: AsyncEngine, *, group_id: str) -> None:
        self._engine = engine
        self._group_id = group_id

    @asynccontextmanager
    async def _unit(self) -> AsyncIterator[UnitOfWork]:
        async with self._engine.begin() as connection:
            yield PostgresUnitOfWork(connection, self._group_id)

    def unit(self) -> AbstractAsyncContextManager[UnitOfWork]:
        return self._unit()
