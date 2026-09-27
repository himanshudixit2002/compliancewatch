from dataclasses import dataclass
from typing import ClassVar

import pytest

from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from py_common.events import EventMessage, encode, kafka_headers, to_message
from py_common.outbox.consumer import ConsumerConfig, IdempotentConsumer, InboundRecord, Outcome
from py_common.outbox.store import UnitOfWork
from py_common.outbox.testing import FakeProducer, MemoryProcessedStore, MemoryUnit


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationCreated(DomainEvent):
    topic: ClassVar[str] = "obligation.created"
    title: str


class Handler:
    def __init__(self, fail_times: int = 0) -> None:
        self.calls: list[EventMessage] = []
        self.fail_times = fail_times

    async def __call__(self, message: EventMessage, unit: UnitOfWork) -> None:
        self.calls.append(message)
        assert isinstance(unit, MemoryUnit)
        unit.writes.append(message.payload["title"])
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("handler exploded")


def record(message: EventMessage, *, offset: int = 0) -> InboundRecord:
    return InboundRecord(
        topic=message.topic,
        partition=0,
        offset=offset,
        key=str(message.tenant_id).encode(),
        value=encode(message),
        headers=tuple(kafka_headers(message)),
    )


async def noop_sleep(_: float) -> None:
    return None


def make_consumer(
    store: MemoryProcessedStore, handler: Handler, producer: FakeProducer, attempts: int = 3
) -> IdempotentConsumer:
    return IdempotentConsumer(
        group_id="obligation",
        store=store,
        handler=handler,
        producer=producer,
        config=ConsumerConfig(max_handler_attempts=attempts, retry_backoff_seconds=0),
        sleep=noop_sleep,
    )


def sample(title: str = "File") -> EventMessage:
    return to_message(ObligationCreated(tenant_id=TenantId.new(), title=title))


async def test_processes_a_message_once_and_records_it() -> None:
    store, handler, producer = MemoryProcessedStore(), Handler(), FakeProducer()
    consumer = make_consumer(store, handler, producer)
    message = sample()
    assert await consumer.process(record(message)) == Outcome.PROCESSED
    assert await consumer.process(record(message, offset=1)) == Outcome.SKIPPED
    assert [m.event_id for m in handler.calls] == [message.event_id]
    assert store.processed == {message.event_id}
    assert store.committed_writes == ["File"]
    assert producer.sent == []


async def test_a_handler_failure_rolls_back_then_succeeds_on_retry() -> None:
    store, handler, producer = MemoryProcessedStore(), Handler(fail_times=1), FakeProducer()
    consumer = make_consumer(store, handler, producer)
    message = sample()
    assert await consumer.process(record(message)) == Outcome.PROCESSED
    assert len(handler.calls) == 2
    assert store.rolled_back == 1
    assert store.committed_writes == ["File"]
    assert store.processed == {message.event_id}


async def test_a_poison_message_goes_to_the_consumer_dead_letter_topic() -> None:
    store, handler, producer = MemoryProcessedStore(), Handler(fail_times=99), FakeProducer()
    consumer = make_consumer(store, handler, producer, attempts=3)
    message = sample("bad")
    assert await consumer.process(record(message, offset=7)) == Outcome.DEAD
    assert len(handler.calls) == 3
    assert store.rolled_back == 3
    assert store.processed == set()
    assert store.committed_writes == []
    (dead,) = producer.sent
    assert dead.topic == "obligation.created.obligation.dlq"
    assert dead.value == encode(message)
    assert dead.key == str(message.tenant_id).encode()
    assert dead.header("origin_topic") == b"obligation.created"
    assert dead.header("consumer_group") == b"obligation"
    assert dead.header("attempts") == b"3"
    assert dead.header("error") == b"RuntimeError: handler exploded"
    assert dead.header("event_id") == str(message.event_id).encode()


async def test_undecodable_bytes_are_dead_lettered_without_calling_the_handler() -> None:
    store, handler, producer = MemoryProcessedStore(), Handler(), FakeProducer()
    consumer = make_consumer(store, handler, producer)
    bad = InboundRecord(topic="obligation.created", partition=0, offset=0, key=None, value=b"{")
    assert await consumer.process(bad) == Outcome.DEAD
    assert handler.calls == []
    assert store.units == 0
    (dead,) = producer.sent
    assert dead.topic == "obligation.created.obligation.dlq"
    assert dead.key == b""
    assert dead.value == b"{"
    assert dead.header("error") is not None
    assert dead.header("error").startswith(b"DecodeError")  # type: ignore[union-attr]


async def test_sleeps_between_attempts_with_doubling_backoff() -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    store, handler, producer = MemoryProcessedStore(), Handler(fail_times=2), FakeProducer()
    consumer = IdempotentConsumer(
        group_id="g",
        store=store,
        handler=handler,
        producer=producer,
        config=ConsumerConfig(max_handler_attempts=3, retry_backoff_seconds=0.5),
        sleep=sleep,
    )
    assert await consumer.process(record(sample())) == Outcome.PROCESSED
    assert slept == [0.5, 1.0]


def test_config_and_group_are_checked() -> None:
    with pytest.raises(ValueError, match="max_handler_attempts"):
        ConsumerConfig(max_handler_attempts=0)
    with pytest.raises(ValueError, match="retry_backoff_seconds"):
        ConsumerConfig(retry_backoff_seconds=-1)
    with pytest.raises(ValueError, match="group_id"):
        IdempotentConsumer(
            group_id=" ", store=MemoryProcessedStore(), handler=Handler(), producer=FakeProducer()
        )
