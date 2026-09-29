"""Publish pending outbox rows to Kafka.

Each pass claims a batch of pending rows in one transaction, sends them in order, and marks each
one published, scheduled for a retry, or dead. A send that fails schedules the row again after an
exponential backoff; after ``max_attempts`` the message is sent to ``<topic>.dlq`` and the row
is marked dead only when that send succeeds, so nothing is lost while the broker is down.
Delivery is at least once: a crash between the send and the commit republishes the row.

``python -m py_common.outbox`` runs it against ``CW_DATABASE_URL`` (whose ``search_path``
picks the service schema) and ``CW_KAFKA_BOOTSTRAP``, with the ``CW_KAFKA_*`` credentials of a
managed cluster, until SIGTERM or SIGINT. With
``CW_OTEL_ENDPOINT`` set it exports the published, retried and dead counters by topic and the
``outbox_relay_pending`` gauge by ``db_schema`` (``CW_DB_SCHEMA``), which ``OutboxBacklog``
alerts on.
"""

import asyncio
import dataclasses
import json
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from opentelemetry import metrics
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from domain_kernel.events import utc_now
from py_common import __version__
from py_common.events import CONTENT_TYPE
from py_common.kafka import KafkaClientConfig
from py_common.logging import configure_logging, get_logger
from py_common.outbox.producer import AiokafkaProducer, MessageProducer
from py_common.outbox.schema import OUTBOX_TABLE
from py_common.outbox.store import ClaimedMessage, OutboxBatch, OutboxStore, PostgresOutboxStore
from py_common.settings import Settings
from py_common.telemetry import configure_telemetry

SERVICE_NAME = "outbox-relay"
UNSET_SCHEMA = "unset"
"""The ``db_schema`` label when ``CW_DB_SCHEMA`` is not set."""
PENDING_GAUGE = "outbox_relay_pending"

log = get_logger(__name__)
meter = metrics.get_meter("py_common.outbox.relay")
published_counter = meter.create_counter(
    "outbox_relay_published_total", description="Outbox rows published to their topic"
)
retried_counter = meter.create_counter(
    "outbox_relay_retried_total", description="Outbox rows scheduled for another attempt"
)
dead_counter = meter.create_counter(
    "outbox_relay_dead_total", description="Outbox rows moved to a dead-letter topic"
)


@dataclass(frozen=True, slots=True)
class RelayConfig:
    batch_size: int = 100
    poll_interval_seconds: float = 0.5
    max_attempts: int = 8
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 300.0
    dlq_suffix: str = ".dlq"
    pending_interval_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.batch_size < 1 or self.max_attempts < 1:
            raise ValueError("batch_size and max_attempts must be at least 1")
        if (
            self.poll_interval_seconds <= 0
            or self.base_backoff_seconds <= 0
            or self.pending_interval_seconds <= 0
        ):
            raise ValueError(
                "poll_interval_seconds, base_backoff_seconds and pending_interval_seconds "
                "must be positive"
            )
        if self.max_backoff_seconds < self.base_backoff_seconds:
            raise ValueError("max_backoff_seconds must not be below base_backoff_seconds")


@dataclass(frozen=True, slots=True)
class RelayStats:
    claimed: int = 0
    published: int = 0
    retried: int = 0
    dead: int = 0

    def __add__(self, other: "RelayStats") -> "RelayStats":
        return RelayStats(
            claimed=self.claimed + other.claimed,
            published=self.published + other.published,
            retried=self.retried + other.retried,
            dead=self.dead + other.dead,
        )


DEFAULT_CONFIG = RelayConfig()


def backoff_seconds(attempts: int, config: RelayConfig = DEFAULT_CONFIG) -> float:
    """Delay before the next try after ``attempts`` failures: 1 s, 2 s, 4 s ... capped."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    delay: float = config.base_backoff_seconds * 2 ** (attempts - 1)
    return min(delay, config.max_backoff_seconds)


def message_bytes(message: ClaimedMessage) -> bytes:
    return json.dumps(
        message.message, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def message_headers(message: ClaimedMessage) -> list[tuple[str, bytes]]:
    return [
        ("event_id", str(message.id).encode("ascii")),
        ("topic", message.topic.encode("ascii")),
        ("schema_version", message.schema_version.encode("ascii")),
        ("content-type", CONTENT_TYPE.encode("ascii")),
    ]


class OutboxRelay:
    def __init__(
        self,
        *,
        store: OutboxStore,
        producer: MessageProducer,
        config: RelayConfig = DEFAULT_CONFIG,
        clock: Callable[[], datetime] = utc_now,
        db_schema: str = UNSET_SCHEMA,
        meter: metrics.Meter = meter,
    ) -> None:
        self._store = store
        self._producer = producer
        self._config = config
        self._clock = clock
        self._attributes = {"db_schema": db_schema}
        # No unit: the collector's Prometheus exporter would add a suffix to the name.
        self._pending_gauge = meter.create_gauge(
            PENDING_GAUGE, description="Outbox rows waiting to be published"
        )

    async def run_once(self) -> RelayStats:
        """Claim and publish one batch; returns what happened to each row."""
        stats = RelayStats()
        async with self._store.batch() as batch:
            now = self._clock()
            claimed = await batch.claim(limit=self._config.batch_size, now=now)
            stats = RelayStats(claimed=len(claimed))
            for message in claimed:
                stats += await self._publish(batch, message)
        return stats

    async def _publish(self, batch: OutboxBatch, message: ClaimedMessage) -> RelayStats:
        try:
            await self._producer.send(
                message.topic,
                key=message.partition_key.encode("utf-8"),
                value=message_bytes(message),
                headers=message_headers(message),
            )
        except Exception as exc:
            return await self._failed(batch, message, exc)
        await batch.mark_published(message.id, at=self._clock())
        published_counter.add(1, {"topic": message.topic})
        return RelayStats(published=1)

    async def _failed(
        self, batch: OutboxBatch, message: ClaimedMessage, exc: Exception
    ) -> RelayStats:
        attempts = message.attempts + 1
        error = f"{type(exc).__name__}: {exc}"
        if attempts >= self._config.max_attempts:
            dlq_topic = message.topic + self._config.dlq_suffix
            try:
                await self._producer.send(
                    dlq_topic,
                    key=message.partition_key.encode("utf-8"),
                    value=message_bytes(message),
                    headers=[
                        *message_headers(message),
                        ("origin_topic", message.topic.encode("ascii")),
                        ("attempts", str(attempts).encode("ascii")),
                        ("error", error.encode("utf-8", errors="replace")[:500]),
                    ],
                )
            except Exception as dlq_exc:
                log.warning(
                    "outbox.dlq_send_failed",
                    event_id=str(message.id),
                    topic=message.topic,
                    attempts=attempts,
                    error=f"{type(dlq_exc).__name__}: {dlq_exc}",
                )
            else:
                log.error(
                    "outbox.dead_lettered",
                    event_id=str(message.id),
                    topic=message.topic,
                    dlq_topic=dlq_topic,
                    attempts=attempts,
                    error=error,
                )
                await batch.mark_dead(message.id, attempts=attempts, error=error)
                dead_counter.add(1, {"topic": message.topic})
                return RelayStats(dead=1)
        available_at = self._clock() + timedelta(seconds=backoff_seconds(attempts, self._config))
        log.warning(
            "outbox.publish_failed",
            event_id=str(message.id),
            topic=message.topic,
            attempts=attempts,
            retry_at=available_at.isoformat(),
            error=error,
        )
        await batch.mark_retry(
            message.id, attempts=attempts, available_at=available_at, error=error
        )
        retried_counter.add(1, {"topic": message.topic})
        return RelayStats(retried=1)

    async def report_pending(self) -> int:
        """Set the pending gauge to the rows still to publish; returns the count."""
        count = await self._store.pending()
        self._pending_gauge.set(count, self._attributes)
        return count

    async def run_forever(self, stop: asyncio.Event) -> RelayStats:
        """Loop until ``stop`` is set; waits ``poll_interval_seconds`` after an empty pass and
        reports the pending count at the start and every ``pending_interval_seconds``."""
        total = RelayStats()
        report_at = self._clock()
        while not stop.is_set():
            if self._clock() >= report_at:
                await self.report_pending()
                report_at = self._clock() + timedelta(seconds=self._config.pending_interval_seconds)
            stats = await self.run_once()
            total += stats
            if stats.claimed == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._config.poll_interval_seconds)
                except TimeoutError:
                    continue
        return total


async def outbox_table_exists(engine: AsyncEngine) -> bool:
    """True when ``outbox_event`` is visible on the connection's ``search_path``."""

    def has_table(connection: Connection) -> bool:
        return inspect(connection).has_table(OUTBOX_TABLE)

    async with engine.connect() as connection:
        return await connection.run_sync(has_table)


async def run(
    settings: Settings,
    *,
    config: RelayConfig = DEFAULT_CONFIG,
    stop: asyncio.Event | None = None,
) -> bool:
    """Run until ``stop`` is set. Without a ``stop`` event of the caller's, SIGTERM and SIGINT
    set one; a process that runs the relay next to other work passes its own and keeps its
    signal handling. Returns False without starting when the table is missing."""
    if stop is None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop.set)
    return await run_relay(settings, stop, config=config)


async def run_relay(
    settings: Settings, stop: asyncio.Event, *, config: RelayConfig = DEFAULT_CONFIG
) -> bool:
    """Relay the schema on ``CW_DATABASE_URL`` until ``stop`` is set, the way a worker process
    runs it next to its other components (``py_common.runtime``). Returns False without starting
    when the table is missing."""
    engine = create_async_engine(settings.database_url)
    try:
        if not await outbox_table_exists(engine):
            log.error(
                "outbox.table_missing",
                table=OUTBOX_TABLE,
                db_schema=settings.db_schema,
                hint="the service's migration must call create_outbox_table(op) first",
            )
            return False
        async with AiokafkaProducer(
            KafkaClientConfig.from_settings(settings), client_id="cw-outbox-relay"
        ) as producer:
            relay = OutboxRelay(
                store=PostgresOutboxStore(engine),
                producer=producer,
                config=config,
                db_schema=settings.db_schema or UNSET_SCHEMA,
            )
            log.info(
                "outbox.relay_started",
                kafka_bootstrap=settings.kafka_bootstrap,
                db_schema=settings.db_schema,
            )
            total = await relay.run_forever(stop)
            log.info("outbox.relay_stopped", **dataclasses.asdict(total))
            return True
    finally:
        await engine.dispose()


def main() -> None:
    settings = Settings(service_name=SERVICE_NAME)
    configure_logging(
        service_name=SERVICE_NAME, log_level=settings.log_level, json_output=settings.log_json
    )
    telemetry = configure_telemetry(
        service_name=SERVICE_NAME, version=__version__, settings=settings
    )
    try:
        started = asyncio.run(run(settings))
    finally:
        telemetry.shutdown()
    if not started:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
