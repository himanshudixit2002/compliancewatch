"""The outbox against Postgres and Redpanda through the real stores and aiokafka. Needs Docker.

Tables are created in a service-style schema through the alembic helpers, exactly as a service
migration would call them, with the schema on the connection's ``search_path``. The consumer runs
on both stores: ``PostgresProcessedStore`` for async handlers, and ``SyncProcessedStore`` with
``sync_handler`` for handlers written against a sync connection, whose writes join the unit's
transaction.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from aiokafka import AIOKafkaConsumer
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    Column,
    Connection,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.kafka import RedpandaContainer
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.events import DomainEvent
from domain_kernel.ids import ObligationId, TenantId
from py_common.events import EventMessage, decode
from py_common.kafka import KafkaClientConfig
from py_common.outbox import (
    AiokafkaProducer,
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    OutboxAdmin,
    OutboxRelay,
    OutboxWriter,
    Outcome,
    PostgresOutboxStore,
    PostgresProcessedStore,
    PostgresUnitOfWork,
    RelayConfig,
    RelayStats,
    SyncProcessedStore,
    UnitOfWork,
    create_outbox_table,
    create_processed_event_table,
    outbox_event,
    processed_event,
    run_consumer,
    sync_handler,
)
from py_common.outbox.replay import AiokafkaTopicReader, DeadLetters, UnknownTopicError
from py_common.outbox.testing import FakeProducer
from py_common.settings import Settings

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
REDPANDA_IMAGE = "docker.redpanda.com/redpandadata/redpanda:v26.2.3"
SCHEMA = "outbox_test"
TOPIC = "obligation.created"
GROUP = "notification"

handled = Table("handled", MetaData(), Column("title", String(80), primary_key=True))


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationCreated(DomainEvent):
    topic: ClassVar[str] = TOPIC
    obligation_id: ObligationId
    title: str


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        base_url = container.get_connection_url()
        engine = create_engine(base_url, poolclass=NullPool)
        with engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        engine.dispose()
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        engine = create_engine(url, poolclass=NullPool)
        with engine.begin() as connection:
            op = Operations(MigrationContext.configure(connection))
            create_outbox_table(op)
            create_processed_event_table(op)
            handled.create(connection)
        engine.dispose()
        yield url


@pytest.fixture(scope="module")
def bootstrap() -> Iterator[str]:
    container = RedpandaContainer(image=REDPANDA_IMAGE)
    container.start(timeout=60)
    try:
        yield container.get_bootstrap_server()
    finally:
        container.stop()


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(outbox_event.delete())
        await connection.execute(processed_event.delete())
        await connection.execute(handled.delete())
    yield engine
    await engine.dispose()


def write_events(
    database_url: str, titles: Sequence[str], *, rollback: Sequence[str] = ()
) -> list[EventMessage]:
    engine = create_engine(database_url, poolclass=NullPool)
    writer = OutboxWriter()
    written: list[EventMessage] = []
    tenant = TenantId.new()
    try:
        with engine.begin() as connection:
            for title in titles:
                event = ObligationCreated(
                    tenant_id=tenant, obligation_id=ObligationId.new(), title=title
                )
                written.append(writer.write(connection, event).message)
        if rollback:
            with engine.connect() as connection:
                transaction = connection.begin()
                for title in rollback:
                    writer.write(
                        connection,
                        ObligationCreated(
                            tenant_id=tenant, obligation_id=ObligationId.new(), title=title
                        ),
                    )
                transaction.rollback()
    finally:
        engine.dispose()
    return written


async def read_topic(bootstrap: str, topic: str, count: int) -> list[object]:
    """Up to ``count`` records from the start of ``topic``, giving up after thirty seconds."""
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        group_id=f"reader-{uuid.uuid4().hex}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    records: list[object] = []
    try:
        deadline = asyncio.get_running_loop().time() + 30
        while len(records) < count and asyncio.get_running_loop().time() < deadline:
            batches = await consumer.getmany(timeout_ms=1000)
            for items in batches.values():
                records.extend(items)
    finally:
        await consumer.stop()
    return records


def test_tables_landed_in_the_service_schema(database_url: str) -> None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        inspector = inspect(engine)
        assert {"outbox_event", "processed_event"} <= set(inspector.get_table_names(schema=SCHEMA))
        assert inspector.get_table_comment("outbox_event", schema=SCHEMA)["text"]
        indexes = {index["name"] for index in inspector.get_indexes("outbox_event", schema=SCHEMA)}
        assert indexes == {"ix_outbox_event_pending", "ix_outbox_event_published_at"}
        checks = {c["name"] for c in inspector.get_check_constraints("outbox_event", schema=SCHEMA)}
        assert "ck_outbox_event_status" in checks
        with engine.connect() as connection:
            jsonb: str = connection.execute(
                text(
                    "select data_type from information_schema.columns where table_schema = :s "
                    "and table_name = 'outbox_event' and column_name = 'message'"
                ),
                {"s": SCHEMA},
            ).scalar_one()
        assert jsonb == "jsonb"
    finally:
        engine.dispose()


async def test_relay_publishes_committed_rows_only(
    database_url: str, bootstrap: str, engine: AsyncEngine
) -> None:
    written = write_events(database_url, ["first", "second"], rollback=["never"])
    store = PostgresOutboxStore(engine)
    assert await store.pending() == 2, "the rolled back row was never written"
    async with AiokafkaProducer(bootstrap, client_id="test-relay") as producer:
        relay = OutboxRelay(store=store, producer=producer)
        assert await relay.run_once() == RelayStats(claimed=2, published=2)
        assert await relay.run_once() == RelayStats()
    assert await store.pending() == 0

    records = await read_topic(bootstrap, TOPIC, 2)
    assert len(records) == 2
    messages = [decode(record.value) for record in records]  # type: ignore[attr-defined]
    assert [message.payload["title"] for message in messages] == ["first", "second"]
    assert messages == written
    first = records[0]
    assert first.key == str(written[0].tenant_id).encode()  # type: ignore[attr-defined]
    headers = dict(first.headers)  # type: ignore[attr-defined]
    assert headers["event_id"] == str(written[0].event_id).encode()
    assert headers["schema_version"] == b"1.0.0"
    assert headers["content-type"] == b"application/json"

    async with engine.connect() as connection:
        rows = (
            await connection.execute(
                select(outbox_event.c.status, outbox_event.c.published_at, outbox_event.c.attempts)
            )
        ).all()
    assert len(rows) == 2
    assert all(row.status == "published" and row.published_at is not None for row in rows)
    assert all(row.attempts == 0 for row in rows)


class FlakyProducer:
    """Fails the first ``failures`` sends to the main topic, then delegates."""

    def __init__(self, inner: AiokafkaProducer, failures: int) -> None:
        self._inner = inner
        self.failures = failures

    async def send(
        self, topic: str, *, key: bytes, value: bytes, headers: Sequence[tuple[str, bytes]]
    ) -> None:
        if topic == TOPIC and self.failures > 0:
            self.failures -= 1
            raise ConnectionError("simulated broker outage")
        await self._inner.send(topic, key=key, value=value, headers=headers)


async def test_relay_retries_then_dead_letters(
    database_url: str, bootstrap: str, engine: AsyncEngine
) -> None:
    (written,) = write_events(database_url, ["doomed"])
    offset = timedelta()

    def clock() -> datetime:
        return datetime.now(UTC) + offset

    store = PostgresOutboxStore(engine)
    async with AiokafkaProducer(bootstrap, client_id="test-flaky") as inner:
        producer = FlakyProducer(inner, failures=5)
        relay = OutboxRelay(
            store=store,
            producer=producer,
            config=RelayConfig(max_attempts=2, base_backoff_seconds=60),
            clock=clock,
        )
        assert await relay.run_once() == RelayStats(claimed=1, retried=1)
        assert await relay.run_once() == RelayStats(), "not due until the backoff passes"
        assert await store.pending() == 1, "a row backing off is still pending"
        offset += timedelta(seconds=61)
        assert await relay.run_once() == RelayStats(claimed=1, dead=1)
    assert await store.pending() == 0, "a dead row is not pending"

    async with engine.connect() as connection:
        row = (await connection.execute(select(outbox_event))).one()
    assert row.status == "dead"
    assert row.attempts == 2
    assert "simulated broker outage" in row.last_error
    assert row.published_at is None

    (dead,) = await read_topic(bootstrap, TOPIC + ".dlq", 1)
    headers = dict(dead.headers)  # type: ignore[attr-defined]
    assert headers["origin_topic"] == TOPIC.encode()
    assert headers["attempts"] == b"2"
    assert b"simulated broker outage" in headers["error"]
    assert decode(dead.value) == written  # type: ignore[attr-defined]


async def insert_handled(message: EventMessage, unit: UnitOfWork) -> None:
    assert isinstance(unit, PostgresUnitOfWork)
    await unit.connection.execute(handled.insert().values(title=message.payload["title"]))


async def test_consumer_processes_each_event_once_in_one_transaction(
    database_url: str, bootstrap: str, engine: AsyncEngine
) -> None:
    (written,) = write_events(database_url, ["once"])
    record = InboundRecord(
        topic=TOPIC, partition=0, offset=0, key=b"k", value=written.model_dump_json().encode()
    )
    async with AiokafkaProducer(bootstrap, client_id="test-consumer") as producer:
        consumer = IdempotentConsumer(
            group_id=GROUP,
            store=PostgresProcessedStore(engine, group_id=GROUP),
            handler=insert_handled,
            producer=producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        )
        assert await consumer.process(record) == Outcome.PROCESSED
        assert await consumer.process(record) == Outcome.SKIPPED

        async def explode(message: EventMessage, unit: UnitOfWork) -> None:
            await insert_handled(message, unit)
            raise RuntimeError("cannot handle")

        (poison,) = write_events(database_url, ["poison"])
        poison_record = InboundRecord(
            topic=TOPIC, partition=0, offset=1, key=b"k", value=poison.model_dump_json().encode()
        )
        failing = IdempotentConsumer(
            group_id=GROUP,
            store=PostgresProcessedStore(engine, group_id=GROUP),
            handler=explode,
            producer=producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        )
        assert await failing.process(poison_record) == Outcome.DEAD

    async with engine.connect() as connection:
        titles: Sequence[str] = (await connection.execute(select(handled.c.title))).scalars().all()
        processed = (
            await connection.execute(
                select(
                    processed_event.c.consumer_group,
                    processed_event.c.event_id,
                    processed_event.c.topic,
                )
            )
        ).all()
    assert titles == ["once"], "the failed handler's insert rolled back with the unit of work"
    assert [(row.consumer_group, row.event_id, row.topic) for row in processed] == [
        (GROUP, written.event_id, TOPIC)
    ]
    (dead,) = await read_topic(bootstrap, f"{TOPIC}.{GROUP}.dlq", 1)
    assert dict(dead.headers)["consumer_group"] == GROUP.encode()  # type: ignore[attr-defined]


async def test_consumer_run_reads_from_the_broker_and_commits_offsets(
    database_url: str, bootstrap: str, engine: AsyncEngine
) -> None:
    run_topic = f"obligation.run_{uuid.uuid4().hex[:8]}"

    @dataclass(frozen=True, slots=True, kw_only=True)
    class Created(DomainEvent):
        topic: ClassVar[str] = run_topic
        title: str

    sync_engine = create_engine(database_url, poolclass=NullPool)
    with sync_engine.begin() as connection:
        for title in ("a", "b"):
            OutboxWriter().write(connection, Created(tenant_id=TenantId.new(), title=title))
    sync_engine.dispose()

    seen: list[str] = []
    stop = asyncio.Event()

    async def handler(message: EventMessage, unit: UnitOfWork) -> None:
        seen.append(message.payload["title"])
        if len(seen) == 2:
            stop.set()

    group = f"runner-{uuid.uuid4().hex[:8]}"
    async with AiokafkaProducer(bootstrap, client_id="test-run") as producer:
        relay = OutboxRelay(store=PostgresOutboxStore(engine), producer=producer)
        assert (await relay.run_once()).published == 2
        consumer = IdempotentConsumer(
            group_id=group,
            store=PostgresProcessedStore(engine, group_id=group),
            handler=handler,
            producer=producer,
        )
        handled_count = await asyncio.wait_for(
            consumer.run(kafka=KafkaClientConfig(bootstrap), topics=[run_topic], stop=stop),
            timeout=60,
        )
        assert handled_count == 2
        assert seen == ["a", "b"]

        stop_again = asyncio.Event()
        asyncio.get_running_loop().call_later(3, stop_again.set)
        again = await asyncio.wait_for(
            consumer.run(kafka=KafkaClientConfig(bootstrap), topics=[run_topic], stop=stop_again),
            timeout=60,
        )
        assert again == 0, "committed offsets mean nothing is redelivered"
        assert seen == ["a", "b"]


SYNC_GROUP = "notification.obligations"


@dataclass(frozen=True, slots=True, kw_only=True)
class Handled(DomainEvent):
    topic: ClassVar[str] = "notification.handled"
    title: str


def handle_sync(message: EventMessage, connection: Connection) -> None:
    """A sync handler: its own row and an outbox row, on the unit's connection."""
    title = message.payload["title"]
    connection.execute(handled.insert().values(title=title))
    tenant = None if message.tenant_id is None else TenantId(message.tenant_id)
    OutboxWriter().write(connection, Handled(tenant_id=tenant, title=title))


async def test_sync_handler_joins_the_unit_transaction(
    database_url: str, engine: AsyncEngine
) -> None:
    sync_engine = create_engine(database_url, poolclass=NullPool)
    (written,) = write_events(database_url, ["joined"])
    (poison,) = write_events(database_url, ["poison"])
    async with engine.begin() as connection:
        await connection.execute(outbox_event.delete())

    def explode(message: EventMessage, connection: Connection) -> None:
        handle_sync(message, connection)
        raise RuntimeError("cannot handle")

    producer = FakeProducer()

    def make(handler: object) -> IdempotentConsumer:
        return IdempotentConsumer(
            group_id=SYNC_GROUP,
            store=SyncProcessedStore(sync_engine, group_id=SYNC_GROUP),
            handler=sync_handler(handler),  # type: ignore[arg-type]
            producer=producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        )

    def as_record(message: EventMessage, offset: int) -> InboundRecord:
        return InboundRecord(
            topic=TOPIC,
            partition=0,
            offset=offset,
            key=b"k",
            value=message.model_dump_json().encode(),
        )

    try:
        assert await make(handle_sync).process(as_record(written, 0)) == Outcome.PROCESSED
        assert await make(handle_sync).process(as_record(written, 1)) == Outcome.SKIPPED
        assert await make(explode).process(as_record(poison, 2)) == Outcome.DEAD
    finally:
        sync_engine.dispose()

    async with engine.connect() as connection:
        titles: Sequence[str] = (await connection.execute(select(handled.c.title))).scalars().all()
        inbox = (
            await connection.execute(
                select(processed_event.c.consumer_group, processed_event.c.event_id)
            )
        ).all()
        outbox = (
            await connection.execute(select(outbox_event.c.topic, outbox_event.c.message))
        ).all()
    assert list(titles) == ["joined"], "the failed handler's row rolled back with its unit"
    assert [(row.consumer_group, row.event_id) for row in inbox] == [(SYNC_GROUP, written.event_id)]
    assert [(row.topic, row.message["payload"]["title"]) for row in outbox] == [
        ("notification.handled", "joined")
    ], "the handler's outbox row committed with it, the failed one did not"
    assert producer.topics() == [f"{TOPIC}.{SYNC_GROUP}.dlq"]


async def test_run_consumer_reads_the_broker_through_the_sync_store(
    database_url: str, bootstrap: str, engine: AsyncEngine
) -> None:
    run_topic = f"obligation.sync_{uuid.uuid4().hex[:8]}"

    @dataclass(frozen=True, slots=True, kw_only=True)
    class Created(DomainEvent):
        topic: ClassVar[str] = run_topic
        title: str

    sync_engine = create_engine(database_url, poolclass=NullPool)
    with sync_engine.begin() as writing:
        for title in ("c", "d"):
            OutboxWriter().write(writing, Created(tenant_id=TenantId.new(), title=title))
    sync_engine.dispose()
    async with AiokafkaProducer(bootstrap, client_id="test-sync-run") as producer:
        relay = OutboxRelay(store=PostgresOutboxStore(engine), producer=producer)
        assert (await relay.run_once()).published == 2

    stop = asyncio.Event()
    seen: list[str] = []

    def record(message: EventMessage, connection: Connection) -> None:
        connection.execute(handled.insert().values(title=message.payload["title"]))
        seen.append(message.payload["title"])
        if len(seen) == 2:
            stop.set()

    group = f"notification.sync-{uuid.uuid4().hex[:8]}"
    settings = Settings(_env_file=None, database_url=database_url, kafka_bootstrap=bootstrap)
    count = await asyncio.wait_for(
        run_consumer(
            settings, group_id=group, topics=[run_topic], handler=sync_handler(record), stop=stop
        ),
        timeout=60,
    )
    assert count == 2
    async with engine.connect() as connection:
        titles: Sequence[str] = (await connection.execute(select(handled.c.title))).scalars().all()
        inbox: int = (
            await connection.execute(
                select(func.count())
                .select_from(processed_event)
                .where(processed_event.c.consumer_group == group)
            )
        ).scalar_one()
    assert sorted(titles) == ["c", "d"]
    assert inbox == 2


async def test_a_dead_row_is_requeued_and_its_dead_letter_listed_and_replayed(
    database_url: str, bootstrap: str, engine: AsyncEngine
) -> None:
    """The relay's dead row, as an operator recovers it: listed with when it went dead, put back
    to pending and published; its copy on <topic>.dlq listed read only and sent back to its
    topic through the broker."""
    replay_topic = f"obligation.replayed_{uuid.uuid4().hex[:8]}"

    @dataclass(frozen=True, slots=True, kw_only=True)
    class Replayed(DomainEvent):
        topic: ClassVar[str] = replay_topic
        title: str

    sync_engine = create_engine(database_url, poolclass=NullPool)
    with sync_engine.begin() as writing:
        written = OutboxWriter().write(writing, Replayed(tenant_id=TenantId.new(), title="late"))

    class Away:
        def __init__(self, inner: AiokafkaProducer) -> None:
            self.inner, self.away = inner, True

        async def send(
            self, to: str, *, key: bytes, value: bytes, headers: Sequence[tuple[str, bytes]]
        ) -> None:
            if to == replay_topic and self.away:
                raise ConnectionError("simulated broker outage")
            await self.inner.send(to, key=key, value=value, headers=headers)

    before = datetime.now(UTC)
    async with AiokafkaProducer(bootstrap, client_id="test-replay") as inner:
        producer = Away(inner)
        relay = OutboxRelay(
            store=PostgresOutboxStore(engine), producer=producer, config=RelayConfig(max_attempts=1)
        )
        assert await relay.run_once() == RelayStats(claimed=1, dead=1)
        with sync_engine.begin() as connection:
            admin = OutboxAdmin(connection)
            (dead,) = admin.dead(topic=replay_topic)
            assert dead.event_id == written.event_id
            assert dead.dead_at is not None
            assert dead.dead_at >= before - timedelta(seconds=5), "when it went dead"
            assert admin.requeue(written.event_id, at=datetime.now(UTC))
        producer.away = False
        assert await relay.run_once() == RelayStats(claimed=1, published=1)
        with sync_engine.connect() as connection:
            published = OutboxAdmin(connection).get(written.event_id)
        assert published is not None
        assert (published.status, published.attempts) == ("published", 0)

        reader = AiokafkaTopicReader(bootstrap)
        letters = DeadLetters(reader, inner)
        (letter,) = await letters.list(f"{replay_topic}.dlq")
        assert (letter.event_id, letter.origin_topic, letter.attempts) == (
            written.event_id,
            replay_topic,
            1,
        )
        assert len(await letters.list(f"{replay_topic}.dlq")) == 1, "listing commits nothing"
        replayed = await letters.replay(f"{replay_topic}.dlq", written.event_id)
        assert replayed.to == replay_topic
        with pytest.raises(UnknownTopicError):
            await reader.read(f"{replay_topic}.nothing.dlq")
        missing = f"{replay_topic}.misspelt"
        with pytest.raises(UnknownTopicError, match="nothing is sent"):
            await letters.replay(f"{replay_topic}.dlq", written.event_id, to=missing)
        assert not await reader.has_topic(missing), "the send never created it"
    sync_engine.dispose()
    records = await read_topic(bootstrap, replay_topic, 2)
    assert [decode(record.value).event_id for record in records] == [  # type: ignore[attr-defined]
        written.event_id,
        written.event_id,
    ], "the requeued row's publication, then the replayed copy"
    replayed_headers = dict(records[1].headers)  # type: ignore[attr-defined]
    assert "origin_topic" not in replayed_headers
    assert replayed_headers["event_id"] == str(written.event_id).encode()
