"""Publish pending outbox rows to Kafka.

Each pass claims a batch of pending rows in one transaction, sends them in order, and marks each
one published, scheduled for a retry, or dead. A send that fails schedules the row again after an
exponential backoff; after ``max_attempts`` the message is sent to ``<topic>.dlq`` and the row
is marked dead only when that send succeeds, so nothing is lost while the broker is down.
Delivery is at least once: a crash between the send and the commit republishes the row.

``python -m py_common.outbox.relay`` runs it against ``CW_DATABASE_URL`` (whose ``search_path``
picks the service schema) and ``CW_KAFKA_BOOTSTRAP`` until SIGTERM or SIGINT.
"""

import asyncio
import dataclasses
import json
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import create_async_engine

from domain_kernel.events import utc_now
from py_common.events import CONTENT_TYPE
from py_common.logging import configure_logging, get_logger
from py_common.outbox.producer import AiokafkaProducer, MessageProducer
from py_common.outbox.store import ClaimedMessage, OutboxBatch, OutboxStore, PostgresOutboxStore
from py_common.settings import Settings

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RelayConfig:
    batch_size: int = 100
    poll_interval_seconds: float = 0.5
    max_attempts: int = 8
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 300.0
    dlq_suffix: str = ".dlq"

    def __post_init__(self) -> None:
        if self.batch_size < 1 or self.max_attempts < 1:
            raise ValueError("batch_size and max_attempts must be at least 1")
        if self.poll_interval_seconds <= 0 or self.base_backoff_seconds <= 0:
            raise ValueError("poll_interval_seconds and base_backoff_seconds must be positive")
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
    ) -> None:
        self._store = store
        self._producer = producer
        self._config = config
        self._clock = clock

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
        return RelayStats(retried=1)

    async def run_forever(self, stop: asyncio.Event) -> RelayStats:
        """Loop until ``stop`` is set; waits ``poll_interval_seconds`` after an empty pass."""
        total = RelayStats()
        while not stop.is_set():
            stats = await self.run_once()
            total += stats
            if stats.claimed == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self._config.poll_interval_seconds)
                except TimeoutError:
                    continue
        return total


async def run(settings: Settings, *, config: RelayConfig = DEFAULT_CONFIG) -> None:
    engine = create_async_engine(settings.database_url)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        async with AiokafkaProducer(
            settings.kafka_bootstrap, client_id="cw-outbox-relay"
        ) as producer:
            relay = OutboxRelay(store=PostgresOutboxStore(engine), producer=producer, config=config)
            log.info(
                "outbox.relay_started",
                kafka_bootstrap=settings.kafka_bootstrap,
                db_schema=settings.db_schema,
            )
            total = await relay.run_forever(stop)
            log.info("outbox.relay_stopped", **dataclasses.asdict(total))
    finally:
        await engine.dispose()


def main() -> None:
    settings = Settings(service_name="outbox-relay")
    configure_logging(
        service_name="outbox-relay", log_level=settings.log_level, json_output=settings.log_json
    )
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
