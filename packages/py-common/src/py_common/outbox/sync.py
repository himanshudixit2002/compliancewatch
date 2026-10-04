"""Consumer handlers that write through a synchronous SQLAlchemy connection.

Service repositories are synchronous (a ``Session`` on a sync ``Engine``) while
``IdempotentConsumer`` runs on asyncio. ``SyncProcessedStore`` joins the two without running
database work on the event loop: each unit of work owns one connection and one thread for its
whole life. The transaction begins on that thread, the inbox check, the handler's writes (its
own tables and any outbox rows written with ``OutboxWriter``) and the ``processed_event`` row
run there, and the commit or the rollback happens there. A handler that also calls another
service over HTTP blocks its unit's thread, never the loop, which in a combined worker also
serves Temporal and the other consumers.

- ``SyncProcessedStore(engine, group_id=...)``: the ``ProcessedStore`` a consumer takes. Its unit
  is a ``SyncUnit``; ``await unit.run(fn)`` calls ``fn(connection)`` on the unit's thread, inside
  the unit's transaction, and returns what ``fn`` returns.
- ``sync_handler(fn)``: turns ``fn(message, connection)`` into the handler ``IdempotentConsumer``
  takes, so the handler's writes and the ``processed_event`` row commit together.
- ``SyncProcessedStore(engine, group_id=..., begin_on_write=True)`` (``read_first_store``) and
  ``read_then_write(read, write)``: for a handler that reads other services over HTTP before it
  writes, so no transaction is open while it waits on the network. The inbox check commits on
  its own, ``read(message)`` runs on a thread of its own with no transaction open on the unit's
  connection, and ``write(message, plan, connection)`` begins the transaction that the
  ``processed_event`` row then commits with. Two deliveries of one event that race both pass
  the check; the second one's ``processed_event`` row breaks its unique key, so its writes roll
  back and the retry skips it, and handlers that insert idempotently stay correct even before
  that.
- ``run_consumer(settings, group_id=..., topics=..., handler=..., stop=...)``: a standalone
  consumer process: the engine from ``CW_DATABASE_URL``, the store, and the aiokafka producer for
  the dead-letter topic ``<topic>.<group_id>.dlq``; it returns when ``stop`` is set.
  ``store_factory`` builds the store from the engine and the group, ``SyncProcessedStore`` by
  default (``sync_store``).

Any SQLAlchemy engine works, SQLite included, so tests of a handler can run the store on a file
database without a broker or Postgres.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import partial
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, insert, select

from py_common.events import EventMessage
from py_common.kafka import KafkaClientConfig
from py_common.logging import get_logger
from py_common.outbox.consumer import DEFAULT_CONFIG, ConsumerConfig, Handler, IdempotentConsumer
from py_common.outbox.producer import AiokafkaProducer
from py_common.outbox.schema import processed_event
from py_common.outbox.store import ProcessedStore, UnitOfWork
from py_common.settings import Settings

log = get_logger(__name__)

SyncHandler = Callable[[EventMessage, Connection], None]
"""A handler that writes through the unit's connection; it must not commit or roll back."""
StoreFactory = Callable[[Engine, str], ProcessedStore]
"""The processed-event store of a consumer group on an engine."""


class SyncUnit:
    """One consumer transaction on one connection, confined to one thread.

    ``begins_on_write`` units begin no transaction when they open: the inbox check ends the one
    its query began, and the first statement after it begins the transaction the unit commits.
    """

    def __init__(
        self,
        connection: Connection,
        group_id: str,
        executor: ThreadPoolExecutor,
        *,
        begins_on_write: bool = False,
    ) -> None:
        self.connection = connection
        self.group_id = group_id
        self.begins_on_write = begins_on_write
        self._executor = executor

    async def run[T](self, fn: Callable[[Connection], T]) -> T:
        """``fn(connection)`` on the unit's thread, inside its transaction."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn, self.connection)

    async def already_processed(self, event_id: UUID) -> bool:
        check = partial(_already_processed, group_id=self.group_id, event_id=event_id)
        if self.begins_on_write:
            return await self.run(partial(_then_commit, check))
        return await self.run(check)

    async def mark_processed(self, event_id: UUID, *, topic: str) -> None:
        await self.run(
            partial(_mark_processed, group_id=self.group_id, event_id=event_id, topic=topic)
        )


def _already_processed(connection: Connection, *, group_id: str, event_id: UUID) -> bool:
    statement = select(processed_event.c.event_id).where(
        processed_event.c.consumer_group == group_id,
        processed_event.c.event_id == event_id,
    )
    return connection.execute(statement).first() is not None


def _mark_processed(connection: Connection, *, group_id: str, event_id: UUID, topic: str) -> None:
    connection.execute(
        insert(processed_event).values(consumer_group=group_id, event_id=event_id, topic=topic)
    )


def _then_commit[T](fn: Callable[[Connection], T], connection: Connection) -> T:
    """``fn(connection)``, then the end of the transaction its statements began."""
    try:
        return fn(connection)
    finally:
        connection.commit()


class SyncProcessedStore:
    """Units of work on a sync engine, each with its own connection and its own thread.

    With ``begin_on_write`` a unit begins its transaction at its first statement after the
    inbox check rather than when it opens (``read_then_write``)."""

    def __init__(self, engine: Engine, *, group_id: str, begin_on_write: bool = False) -> None:
        if not group_id.strip():
            raise ValueError("group_id must not be blank")
        self._engine = engine
        self._group_id = group_id
        self._begin_on_write = begin_on_write

    @property
    def group_id(self) -> str:
        return self._group_id

    @asynccontextmanager
    async def _unit(self) -> AsyncIterator[UnitOfWork]:
        # One worker thread: every step of the unit, the rollback after a cancelled step
        # included, runs on it in order, so the connection never changes threads.
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cw-consumer-unit")
        loop = asyncio.get_running_loop()
        try:
            connection = await loop.run_in_executor(executor, self._engine.connect)
            try:
                if not self._begin_on_write:
                    await loop.run_in_executor(executor, connection.begin)
                try:
                    yield SyncUnit(
                        connection,
                        self._group_id,
                        executor,
                        begins_on_write=self._begin_on_write,
                    )
                except BaseException:
                    await loop.run_in_executor(executor, connection.rollback)
                    raise
                await loop.run_in_executor(executor, connection.commit)
            finally:
                await loop.run_in_executor(executor, connection.close)
        finally:
            executor.shutdown(wait=False)

    def unit(self) -> AbstractAsyncContextManager[UnitOfWork]:
        return self._unit()


def sync_store(engine: Engine, group_id: str) -> ProcessedStore:
    """The default ``StoreFactory``: a ``SyncProcessedStore`` of the group on the engine."""
    return SyncProcessedStore(engine, group_id=group_id)


def read_first_store(engine: Engine, group_id: str) -> ProcessedStore:
    """The ``StoreFactory`` of a ``read_then_write`` handler: units that begin their transaction
    at the first write."""
    return SyncProcessedStore(engine, group_id=group_id, begin_on_write=True)


def sync_handler(fn: SyncHandler) -> Handler:
    """The consumer handler that runs ``fn(message, connection)`` in the unit's transaction.

    The unit must come from ``SyncProcessedStore``; any other store is a wiring mistake and
    raises ``TypeError``, which the consumer retries and then dead-letters like any failure.
    """

    async def handle(message: EventMessage, unit: UnitOfWork) -> None:
        if not isinstance(unit, SyncUnit):
            raise TypeError(
                f"sync_handler needs a SyncProcessedStore unit, got {type(unit).__name__}"
            )
        await unit.run(partial(fn, message))

    return handle


def _in_transaction(connection: Connection) -> bool:
    return connection.in_transaction()


def read_then_write[P](
    read: Callable[[EventMessage], P], write: Callable[[EventMessage, P, Connection], None]
) -> Handler:
    """The consumer handler that runs ``read(message)`` with no transaction open, on a thread of
    its own, then ``write(message, plan, connection)`` in the transaction the unit commits with
    the ``processed_event`` row. ``read`` calls other services and must not touch the database;
    ``write`` must not commit or roll back.

    The unit must come from ``read_first_store`` (``SyncProcessedStore`` with
    ``begin_on_write``); any other is a wiring mistake and raises ``TypeError``, which the
    consumer retries and then dead-letters like any failure.
    """

    async def handle(message: EventMessage, unit: UnitOfWork) -> None:
        if not isinstance(unit, SyncUnit) or not unit.begins_on_write:
            raise TypeError(
                "read_then_write needs a unit that begins on write (read_first_store), got "
                f"{type(unit).__name__}"
            )
        if await unit.run(_in_transaction):
            raise RuntimeError("a transaction is open before the reads; nothing was read")
        plan = await asyncio.to_thread(read, message)
        await unit.run(partial(write, message, plan))

    return handle


async def run_consumer(
    settings: Settings,
    *,
    group_id: str,
    topics: Sequence[str],
    handler: Handler,
    stop: asyncio.Event,
    config: ConsumerConfig = DEFAULT_CONFIG,
    store_factory: StoreFactory = sync_store,
) -> int:
    """Consume ``topics`` as ``group_id`` until ``stop`` is set; returns the records handled.

    The engine reads ``CW_DATABASE_URL`` (its ``search_path`` picks the service schema, where
    the migration created ``processed_event``); records come from and dead letters go to the
    cluster at ``CW_KAFKA_BOOTSTRAP``, with the ``CW_KAFKA_*`` credentials.
    """
    kafka = KafkaClientConfig.from_settings(settings)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with AiokafkaProducer(kafka, client_id=f"cw-consumer-{group_id}") as producer:
            consumer = IdempotentConsumer(
                group_id=group_id,
                store=store_factory(engine, group_id),
                handler=handler,
                producer=producer,
                config=config,
            )
            log.info("consumer.started", group=group_id, topics=list(topics))
            handled = await consumer.run(kafka=kafka, topics=topics, stop=stop)
            log.info("consumer.stopped", group=group_id, handled=handled)
            return handled
    finally:
        await asyncio.to_thread(engine.dispose)
