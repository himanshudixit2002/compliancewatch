"""The composed worker relays a service's outbox to Kafka. Needs Docker.

Postgres holds a ``profile`` schema with the outbox table, as profile's migration leaves it, and
an ``obligation`` schema that has not been migrated. The worker finds the table where it is,
starts one relay for it, and the row it publishes arrives on the topic.
"""

import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from testcontainers.community.kafka import RedpandaContainer
from testcontainers.community.postgres import PostgresContainer

from cw_mvp.registry import entry_named
from cw_mvp.testing import mvp_settings
from cw_mvp.worker import build_registry, has_table, run_worker, worker_settings
from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from py_common.events import EventMessage
from py_common.outbox import OutboxWriter, create_outbox_table
from py_common.outbox.schema import OUTBOX_TABLE
from py_common.settings import with_search_path

pytestmark = pytest.mark.integration

POSTGRES_IMAGE = "pgvector/pgvector:0.8.6-pg16"
REDPANDA_IMAGE = "docker.redpanda.com/redpandadata/redpanda:v26.2.3"
TOPIC = "profile.updated"
READ_SECONDS = 30


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileTouched(DomainEvent):
    topic: ClassVar[str] = TOPIC
    note: str


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        url = container.get_connection_url()
        engine = create_engine(url, poolclass=NullPool)
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA profile"))
        engine.dispose()
        engine = create_engine(with_search_path(url, "profile"), poolclass=NullPool)
        with engine.begin() as connection:
            create_outbox_table(Operations(MigrationContext.configure(connection)))
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


def write_event(url: str) -> EventMessage:
    engine = create_engine(with_search_path(url, "profile"), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            event = ProfileTouched(tenant_id=TenantId.new(), note="relayed by the worker")
            return OutboxWriter().write(connection, event).message
    finally:
        engine.dispose()


async def read_one(bootstrap: str) -> list[ConsumerRecord[bytes, bytes]]:
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=bootstrap,
        group_id=f"reader-{uuid.uuid4().hex}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    records: list[ConsumerRecord[bytes, bytes]] = []
    try:
        deadline = asyncio.get_running_loop().time() + READ_SECONDS
        while not records and asyncio.get_running_loop().time() < deadline:
            for batch in (await consumer.getmany(timeout_ms=1000)).values():
                records.extend(batch)
    finally:
        await consumer.stop()
    return records


async def test_the_worker_relays_the_schemas_that_have_an_outbox(
    database_url: str, bootstrap: str
) -> None:
    root = mvp_settings(
        database_url=database_url,
        kafka_bootstrap=bootstrap,
        worker_kafka_enabled=True,
        mvp_host="127.0.0.1",
        log_level="WARNING",
    )
    profile, obligation = entry_named("profile"), entry_named("obligation")
    url = root.mvp_internal_url
    assert await has_table(worker_settings(profile, root, internal_url=url), OUTBOX_TABLE)
    assert not await has_table(worker_settings(obligation, root, internal_url=url), OUTBOX_TABLE)

    hosted = await build_registry(root, registry=(profile, obligation))
    assert hosted.loops() == ("profile/outbox-relay",)

    message = write_event(database_url)
    stop = asyncio.Event()
    worker = asyncio.create_task(run_worker(root, stop, hosted=hosted, health_port=0))
    try:
        records = await read_one(bootstrap)
    finally:
        stop.set()
        await asyncio.wait_for(worker, timeout=30)
    assert len(records) == 1
    headers = dict(records[0].headers)
    assert headers["event_id"].decode() == str(message.event_id)
    assert headers["topic"].decode() == TOPIC
