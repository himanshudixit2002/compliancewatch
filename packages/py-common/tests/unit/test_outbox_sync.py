"""The sync consumer store on a SQLite file: one transaction and one thread per unit of work.

Postgres and the broker are exercised in tests/integration/test_outbox_postgres.py; these tests
pin what the store promises whatever the engine: the handler's writes, its outbox rows and the
``processed_event`` row commit together or not at all, every step of a unit runs on one thread
that is not the event loop's, and a handler meant for this store refuses any other.
"""

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import pytest
from sqlalchemy import Column, Connection, Engine, MetaData, String, Table, create_engine, select
from sqlalchemy.pool import NullPool

from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from py_common.events import EventMessage, encode, to_message
from py_common.kafka import KafkaClientConfig
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    OutboxWriter,
    Outcome,
    SyncProcessedStore,
    SyncUnit,
    outbox_event,
    processed_event,
    read_first_store,
    read_then_write,
    run_consumer,
    sync_handler,
)
from py_common.outbox import sync as sync_module
from py_common.outbox.consumer import Handler
from py_common.outbox.store import ProcessedStore
from py_common.outbox.testing import FakeProducer, MemoryProcessedStore
from py_common.settings import Settings

TOPIC = "obligation.created"
GROUP = "notification.obligations"

handled = Table("handled", MetaData(), Column("title", String(80), primary_key=True))


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationCreated(DomainEvent):
    topic: ClassVar[str] = TOPIC
    title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationQueued(DomainEvent):
    topic: ClassVar[str] = "notification.queued"
    title: str


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'consumer.sqlite'}"


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url, poolclass=NullPool)
    for table in (processed_event, outbox_event, handled):
        table.create(engine)
    yield engine
    engine.dispose()


def message(title: str) -> EventMessage:
    return to_message(ObligationCreated(tenant_id=TenantId.new(), title=title))


def inbound(item: EventMessage, offset: int = 0) -> InboundRecord:
    return InboundRecord(
        topic=item.topic, partition=0, offset=offset, key=b"key", value=encode(item)
    )


async def no_sleep(_: float) -> None:
    return None


def consumer(
    store: Any, handler: Handler, producer: FakeProducer, attempts: int = 2
) -> IdempotentConsumer:
    return IdempotentConsumer(
        group_id=GROUP,
        store=store,
        handler=handler,
        producer=producer,
        config=ConsumerConfig(max_handler_attempts=attempts, retry_backoff_seconds=0),
        sleep=no_sleep,
    )


def insert_with_outbox(item: EventMessage, connection: Connection) -> None:
    connection.execute(handled.insert().values(title=item.payload["title"]))
    OutboxWriter().write(
        connection, NotificationQueued(tenant_id=TenantId.new(), title=item.payload["title"])
    )


def titles(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(connection.execute(select(handled.c.title).order_by("title")).scalars())


def processed(engine: Engine) -> list[tuple[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(processed_event.c.consumer_group, processed_event.c.topic)
        ).all()
    return [(row.consumer_group, row.topic) for row in rows]


def outbox_topics(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(connection.execute(select(outbox_event.c.topic)).scalars())


async def test_the_handler_writes_its_outbox_rows_and_the_inbox_row_commit_together(
    engine: Engine,
) -> None:
    producer = FakeProducer()
    run = consumer(
        SyncProcessedStore(engine, group_id=GROUP), sync_handler(insert_with_outbox), producer
    )
    first = message("first")
    assert await run.process(inbound(first)) is Outcome.PROCESSED
    assert await run.process(inbound(first, offset=1)) is Outcome.SKIPPED, "a redelivery"
    assert titles(engine) == ["first"]
    assert processed(engine) == [(GROUP, TOPIC)]
    assert outbox_topics(engine) == ["notification.queued"]
    assert producer.sent == []


async def test_a_failing_handler_rolls_back_its_writes_and_is_dead_lettered(
    engine: Engine,
) -> None:
    def explode(item: EventMessage, connection: Connection) -> None:
        insert_with_outbox(item, connection)
        raise RuntimeError("cannot handle")

    producer = FakeProducer()
    run = consumer(SyncProcessedStore(engine, group_id=GROUP), sync_handler(explode), producer)
    assert await run.process(inbound(message("poison"))) is Outcome.DEAD
    assert titles(engine) == []
    assert processed(engine) == []
    assert outbox_topics(engine) == []
    assert producer.topics() == [f"{TOPIC}.{GROUP}.dlq"]
    assert producer.sent[0].header("attempts") == b"2"


async def test_every_step_of_a_unit_runs_on_one_thread_off_the_loop(engine: Engine) -> None:
    threads: list[int] = []

    def remember(item: EventMessage, connection: Connection) -> None:
        threads.append(threading.get_ident())
        connection.execute(handled.insert().values(title=item.payload["title"]))

    store = SyncProcessedStore(engine, group_id=GROUP)
    async with store.unit() as unit:
        assert isinstance(unit, SyncUnit)
        assert not await unit.already_processed(message("x").event_id)
        await sync_handler(remember)(message("one"), unit)
        threads.append(await unit.run(lambda _: threading.get_ident()))
        await unit.mark_processed(message("y").event_id, topic=TOPIC)
        threads.append(await unit.run(lambda _: threading.get_ident()))
    assert len(set(threads)) == 1
    assert threads[0] != threading.get_ident(), "the loop's thread never touches the connection"
    assert titles(engine) == ["one"]


async def test_a_unit_left_by_an_error_rolls_back(engine: Engine) -> None:
    store = SyncProcessedStore(engine, group_id=GROUP)

    async def write_then_fail() -> None:
        async with store.unit() as unit:
            assert isinstance(unit, SyncUnit)
            await unit.run(lambda c: c.execute(handled.insert().values(title="lost")))
            raise RuntimeError("after the write")

    with pytest.raises(RuntimeError, match="after the write"):
        await write_then_fail()
    assert titles(engine) == []


async def test_the_sync_handler_refuses_another_store_and_the_message_is_dead_lettered() -> None:
    producer = FakeProducer()
    store = MemoryProcessedStore()
    run = consumer(store, sync_handler(insert_with_outbox), producer, attempts=1)
    assert await run.process(inbound(message("elsewhere"))) is Outcome.DEAD
    assert b"SyncProcessedStore" in (producer.sent[0].header("error") or b"")
    assert store.rolled_back == 1


def test_a_blank_group_is_refused(engine: Engine) -> None:
    with pytest.raises(ValueError, match="group_id"):
        SyncProcessedStore(engine, group_id=" ")
    assert SyncProcessedStore(engine, group_id=GROUP).group_id == GROUP


class StubProducer:
    """Stands in for AiokafkaProducer: an async context manager with send."""

    instances: ClassVar[list["StubProducer"]] = []

    def __init__(self, kafka: KafkaClientConfig | str, *, client_id: str) -> None:
        self.kafka = kafka
        self.client_id = client_id
        self.entered = False
        StubProducer.instances.append(self)

    async def __aenter__(self) -> "StubProducer":
        self.entered = True
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.entered = False

    async def send(
        self, topic: str, *, key: bytes, value: bytes, headers: Sequence[tuple[str, bytes]]
    ) -> None:
        raise AssertionError("nothing is dead-lettered here")


async def test_run_consumer_wires_the_store_and_the_producer(
    engine: Engine, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = message("from the broker")

    async def one_record(
        self: IdempotentConsumer, *, kafka: KafkaClientConfig, topics: Sequence[str], stop: Any
    ) -> int:
        assert (kafka, list(topics)) == (KafkaClientConfig("broker:9092"), [TOPIC])
        assert self.group_id == GROUP
        assert await self.process(inbound(item)) is Outcome.PROCESSED
        stop.set()
        return 1

    StubProducer.instances.clear()
    monkeypatch.setattr(sync_module, "AiokafkaProducer", StubProducer)
    monkeypatch.setattr(IdempotentConsumer, "run", one_record)
    settings = Settings(_env_file=None, database_url=database_url, kafka_bootstrap="broker:9092")
    stop = asyncio.Event()
    handled_count = await run_consumer(
        settings,
        group_id=GROUP,
        topics=[TOPIC],
        handler=sync_handler(insert_with_outbox),
        stop=stop,
    )
    assert handled_count == 1
    assert stop.is_set()
    assert titles(engine) == ["from the broker"]
    (producer,) = StubProducer.instances
    assert producer.client_id == f"cw-consumer-{GROUP}"
    assert producer.kafka == KafkaClientConfig("broker:9092")
    assert not producer.entered, "the producer is stopped when the consumer returns"


# ------------------------------------------------- units that begin on write (read_then_write)


class Reads:
    """A ``read`` that records whether the unit's connection had a transaction open."""

    def __init__(self, unit_connection: list[Connection]) -> None:
        self.unit_connection = unit_connection
        self.open_during_read: list[bool] = []
        self.threads: list[int] = []

    def __call__(self, item: EventMessage) -> str:
        self.threads.append(threading.get_ident())
        (connection,) = self.unit_connection
        self.open_during_read.append(connection.in_transaction())
        return str(item.payload["title"]).upper()


def write_plan(item: EventMessage, plan: str, connection: Connection) -> None:
    connection.execute(handled.insert().values(title=plan))
    assert connection.in_transaction(), "the first write begins the unit's transaction"


def remembering(store: ProcessedStore, seen: list[Connection]) -> Any:
    """``store`` whose units record their connection, so a read can look at it."""

    class Remembering:
        def unit(self) -> Any:
            return self._unit()

        @asynccontextmanager
        async def _unit(self) -> AsyncIterator[Any]:
            async with store.unit() as unit:
                assert isinstance(unit, SyncUnit)
                seen[:] = [unit.connection]
                yield unit

    return Remembering()


async def test_the_reads_run_with_no_transaction_open_and_the_writes_commit_with_the_inbox(
    engine: Engine,
) -> None:
    seen: list[Connection] = []
    reads = Reads(seen)
    producer = FakeProducer()
    store = remembering(read_first_store(engine, GROUP), seen)
    run = consumer(store, read_then_write(reads, write_plan), producer)
    first = message("first")
    assert await run.process(inbound(first)) is Outcome.PROCESSED
    assert await run.process(inbound(first, offset=1)) is Outcome.SKIPPED, "a redelivery"
    assert reads.open_during_read == [False]
    assert reads.threads[0] != threading.get_ident(), "the reads never block the loop"
    assert titles(engine) == ["FIRST"]
    assert processed(engine) == [(GROUP, TOPIC)]
    assert producer.sent == []


async def test_a_failing_write_rolls_back_and_is_dead_lettered(engine: Engine) -> None:
    def explode(item: EventMessage, plan: str, connection: Connection) -> None:
        write_plan(item, plan, connection)
        raise RuntimeError("cannot write")

    producer = FakeProducer()
    run = consumer(read_first_store(engine, GROUP), read_then_write(str, explode), producer)
    assert await run.process(inbound(message("poison"))) is Outcome.DEAD
    assert titles(engine) == []
    assert processed(engine) == []
    assert producer.topics() == [f"{TOPIC}.{GROUP}.dlq"]


async def test_a_failing_read_writes_nothing(engine: Engine) -> None:
    def unreachable(item: EventMessage) -> str:
        raise ConnectionError("the other service did not answer")

    producer = FakeProducer()
    run = consumer(
        read_first_store(engine, GROUP), read_then_write(unreachable, write_plan), producer
    )
    assert await run.process(inbound(message("later"))) is Outcome.DEAD
    assert titles(engine) == []
    assert processed(engine) == []
    assert b"did not answer" in (producer.sent[0].header("error") or b"")


@pytest.mark.parametrize(
    "store",
    [
        lambda engine: SyncProcessedStore(engine, group_id=GROUP),
        lambda engine: MemoryProcessedStore(),
    ],
    ids=["begins-at-open", "memory"],
)
async def test_read_then_write_refuses_a_unit_that_does_not_begin_on_write(
    engine: Engine, store: Any
) -> None:
    producer = FakeProducer()
    reads: list[EventMessage] = []

    def read(item: EventMessage) -> str:
        reads.append(item)
        return "read"

    run = consumer(store(engine), read_then_write(read, write_plan), producer, attempts=1)
    assert await run.process(inbound(message("eager"))) is Outcome.DEAD
    assert reads == [], "nothing is read inside a transaction"
    assert b"read_first_store" in (producer.sent[0].header("error") or b"")


async def test_a_unit_that_begins_on_write_is_not_in_a_transaction_after_the_inbox_check(
    engine: Engine,
) -> None:
    async with read_first_store(engine, GROUP).unit() as unit:
        assert isinstance(unit, SyncUnit)
        assert unit.begins_on_write
        assert not await unit.already_processed(message("x").event_id)
        assert not await unit.run(lambda connection: connection.in_transaction())
        await unit.run(lambda c: c.execute(handled.insert().values(title="kept")))
        assert await unit.run(lambda connection: connection.in_transaction())
    assert titles(engine) == ["kept"]
