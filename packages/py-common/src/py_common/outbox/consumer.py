"""Consume events once per consumer group.

``IdempotentConsumer.process`` holds the logic and is unit-tested with fakes: decode the message,
open a unit of work, skip the event if this group already processed it, otherwise run the handler
and record the event id in the same transaction. A handler failure is retried in process; after
``max_handler_attempts`` the message goes to ``<topic>.<group_id>.dlq`` and the offset is
committed, so one bad message never blocks a partition. ``run`` wires that to an aiokafka
consumer with manual offset commits.

A handler that must never process an event raises ``EventRefusedError`` instead: what it wrote
before raising (the record of the refusal) commits, the event is not marked processed, and the
message goes to the dead-letter topic at once, without the retries a failure gets
(``Outcome.REFUSED``). Replayed from there, it is checked again.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from aiokafka import AIOKafkaConsumer, TopicPartition

from py_common.events import DecodeError, EventMessage, decode
from py_common.kafka import KafkaClientConfig
from py_common.logging import get_logger
from py_common.outbox.producer import MessageProducer
from py_common.outbox.store import ProcessedStore, UnitOfWork

log = get_logger(__name__)

Handler = Callable[[EventMessage, UnitOfWork], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ConsumerConfig:
    max_handler_attempts: int = 3
    retry_backoff_seconds: float = 0.5
    dlq_suffix: str = ".dlq"
    poll_timeout_ms: int = 1000

    def __post_init__(self) -> None:
        if self.max_handler_attempts < 1:
            raise ValueError("max_handler_attempts must be at least 1")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class InboundRecord:
    """What the broker delivered, independent of the client library."""

    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: Sequence[tuple[str, bytes]] = ()


DEFAULT_CONFIG = ConsumerConfig()


class Outcome(StrEnum):
    PROCESSED = "processed"
    SKIPPED = "skipped"
    DEAD = "dead"
    REFUSED = "refused"
    """The handler refused the event for good: dead-lettered at once, never processed."""


class EventRefusedError(Exception):
    """A handler's verdict that an event must never be processed, with why. Unlike any other
    exception it is not retried: the handler's writes so far commit (the record of the refusal),
    the event is not marked processed, and the message is dead-lettered at once."""


class IdempotentConsumer:
    def __init__(
        self,
        *,
        group_id: str,
        store: ProcessedStore,
        handler: Handler,
        producer: MessageProducer,
        config: ConsumerConfig = DEFAULT_CONFIG,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not group_id.strip():
            raise ValueError("group_id must not be blank")
        self.group_id = group_id
        self._store = store
        self._handler = handler
        self._producer = producer
        self._config = config
        self._sleep = sleep

    async def process(self, record: InboundRecord) -> Outcome:
        try:
            message = decode(record.value)
        except DecodeError as exc:
            await self._dead_letter(record, error=f"{type(exc).__name__}: {exc}", attempts=1)
            return Outcome.DEAD
        last_error = ""
        for attempt in range(1, self._config.max_handler_attempts + 1):
            refused: EventRefusedError | None = None
            try:
                async with self._store.unit() as unit:
                    if await unit.already_processed(message.event_id):
                        log.info(
                            "consumer.skipped_duplicate",
                            event_id=str(message.event_id),
                            topic=message.topic,
                            group=self.group_id,
                        )
                        return Outcome.SKIPPED
                    try:
                        await self._handler(message, unit)
                    except EventRefusedError as exc:
                        refused = exc
                    else:
                        await unit.mark_processed(message.event_id, topic=message.topic)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "consumer.handler_failed",
                    event_id=str(message.event_id),
                    topic=message.topic,
                    group=self.group_id,
                    attempt=attempt,
                    error=last_error,
                )
                if attempt < self._config.max_handler_attempts:
                    await self._sleep(self._config.retry_backoff_seconds * 2 ** (attempt - 1))
            else:
                if refused is None:
                    return Outcome.PROCESSED
                await self._refuse(record, message, refused, attempts=attempt)
                return Outcome.REFUSED
        await self._dead_letter(
            record, error=last_error, attempts=self._config.max_handler_attempts
        )
        return Outcome.DEAD

    async def _refuse(
        self,
        record: InboundRecord,
        message: EventMessage,
        refused: EventRefusedError,
        *,
        attempts: int,
    ) -> None:
        log.warning(
            "consumer.refused",
            event_id=str(message.event_id),
            topic=message.topic,
            group=self.group_id,
            reason=str(refused),
        )
        await self._dead_letter(
            record, error=f"{type(refused).__name__}: {refused}", attempts=attempts
        )

    async def _dead_letter(self, record: InboundRecord, *, error: str, attempts: int) -> None:
        dlq_topic = f"{record.topic}.{self.group_id}{self._config.dlq_suffix}"
        await self._producer.send(
            dlq_topic,
            key=record.key or b"",
            value=record.value,
            headers=[
                *record.headers,
                ("origin_topic", record.topic.encode("ascii")),
                ("consumer_group", self.group_id.encode("utf-8")),
                ("attempts", str(attempts).encode("ascii")),
                ("error", error.encode("utf-8", errors="replace")[:500]),
            ],
        )
        log.error(
            "consumer.dead_lettered",
            topic=record.topic,
            dlq_topic=dlq_topic,
            group=self.group_id,
            offset=record.offset,
            error=error,
        )

    async def run(
        self, *, kafka: KafkaClientConfig, topics: Sequence[str], stop: asyncio.Event
    ) -> int:
        """Consume ``topics`` from the cluster ``kafka`` names until ``stop`` is set; returns
        how many records were handled."""
        consumer = AIOKafkaConsumer(
            *topics,
            **kafka.aiokafka_kwargs(),
            group_id=self.group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        handled = 0
        try:
            while not stop.is_set():
                batches = await consumer.getmany(timeout_ms=self._config.poll_timeout_ms)
                for partition, records in batches.items():
                    for raw in records:
                        await self.process(
                            InboundRecord(
                                topic=raw.topic,
                                partition=raw.partition,
                                offset=raw.offset,
                                key=raw.key,
                                value=raw.value,
                                headers=tuple(raw.headers or ()),
                            )
                        )
                        handled += 1
                        await consumer.commit(
                            {TopicPartition(raw.topic, raw.partition): raw.offset + 1}
                        )
                        if stop.is_set():
                            break
                    _ = partition
        finally:
            await consumer.stop()
        return handled
