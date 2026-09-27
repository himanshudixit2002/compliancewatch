import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest

from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from py_common.events import decode, to_message
from py_common.outbox.relay import OutboxRelay, RelayConfig, RelayStats, backoff_seconds
from py_common.outbox.testing import FakeProducer, MemoryOutboxStore


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationCreated(DomainEvent):
    topic: ClassVar[str] = "obligation.created"
    title: str


T0 = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def seed(store: MemoryOutboxStore, count: int, *, at: datetime = T0) -> list[str]:
    keys = []
    for index in range(count):
        tenant = TenantId.new()
        message = to_message(ObligationCreated(tenant_id=tenant, title=f"t{index}"))
        store.add(message, partition_key=str(tenant), available_at=at)
        keys.append(str(tenant))
    return keys


def make_relay(
    store: MemoryOutboxStore, producer: FakeProducer, clock: Clock, **config: object
) -> OutboxRelay:
    return OutboxRelay(
        store=store,
        producer=producer,
        config=RelayConfig(max_attempts=3, base_backoff_seconds=1.0, **config),  # type: ignore[arg-type]
        clock=clock,
    )


async def test_publishes_pending_rows_in_order_with_key_headers_and_body() -> None:
    store, producer, clock = MemoryOutboxStore(), FakeProducer(), Clock()
    keys = seed(store, 3)
    stats = await make_relay(store, producer, clock).run_once()
    assert stats == RelayStats(claimed=3, published=3)
    assert [item.key.decode() for item in producer.sent] == keys
    assert producer.topics() == ["obligation.created"] * 3
    first = producer.sent[0]
    message = decode(first.value)
    assert message.payload == {"title": "t0"}
    assert first.header("event_id") == str(message.event_id).encode()
    assert first.header("schema_version") == b"1.0.0"
    assert first.header("content-type") == b"application/json"
    assert (
        first.value
        == json.dumps(json.loads(first.value), sort_keys=True, separators=(",", ":")).encode()
    )
    assert store.statuses() == {"published": 3}
    assert all(row.published_at == T0 for row in store.rows.values())
    assert await make_relay(store, producer, clock).run_once() == RelayStats()


async def test_rows_not_yet_available_are_left_alone() -> None:
    store, producer, clock = MemoryOutboxStore(), FakeProducer(), Clock()
    seed(store, 1, at=T0 + timedelta(seconds=30))
    assert await make_relay(store, producer, clock).run_once() == RelayStats()
    clock.advance(30)
    assert await make_relay(store, producer, clock).run_once() == RelayStats(claimed=1, published=1)


async def test_batch_size_limits_a_pass() -> None:
    store, producer, clock = MemoryOutboxStore(), FakeProducer(), Clock()
    seed(store, 5)
    relay = make_relay(store, producer, clock, batch_size=2)
    assert await relay.run_once() == RelayStats(claimed=2, published=2)
    assert await relay.run_once() == RelayStats(claimed=2, published=2)
    assert await relay.run_once() == RelayStats(claimed=1, published=1)


async def test_a_failed_send_is_retried_with_backoff() -> None:
    store, producer, clock = MemoryOutboxStore(), FakeProducer(), Clock()
    seed(store, 1)
    producer.fail_times["obligation.created"] = 2
    relay = make_relay(store, producer, clock)
    (row,) = store.rows.values()

    assert await relay.run_once() == RelayStats(claimed=1, retried=1)
    assert row.attempts == 1
    assert row.available_at == T0 + timedelta(seconds=1)
    assert "broker unavailable" in row.last_error
    assert await relay.run_once() == RelayStats()  # not due yet

    clock.advance(1)
    assert await relay.run_once() == RelayStats(claimed=1, retried=1)
    assert row.attempts == 2
    assert row.available_at == clock.now + timedelta(seconds=2)

    clock.advance(2)
    assert await relay.run_once() == RelayStats(claimed=1, published=1)
    assert row.status == "published"
    assert row.last_error == ""
    assert producer.topics() == ["obligation.created"]


async def test_max_attempts_sends_to_the_dead_letter_topic() -> None:
    store, producer, clock = MemoryOutboxStore(), FakeProducer(), Clock()
    seed(store, 1)
    producer.fail_times["obligation.created"] = 10
    relay = make_relay(store, producer, clock)
    (row,) = store.rows.values()
    for _ in range(2):
        await relay.run_once()
        clock.advance(600)
    assert await relay.run_once() == RelayStats(claimed=1, dead=1)
    assert row.status == "dead"
    assert row.attempts == 3
    (dead,) = producer.sent
    assert dead.topic == "obligation.created.dlq"
    assert dead.header("origin_topic") == b"obligation.created"
    assert dead.header("attempts") == b"3"
    assert dead.header("error") is not None
    assert b"broker unavailable" in dead.header("error")  # type: ignore[operator]
    assert dead.key == row.partition_key.encode()
    assert decode(dead.value).event_id == row.message.event_id
    assert await relay.run_once() == RelayStats()


async def test_a_failed_dead_letter_send_keeps_the_row_pending() -> None:
    store, producer, clock = MemoryOutboxStore(), FakeProducer(), Clock()
    seed(store, 1)
    producer.fail_times["obligation.created"] = 10
    producer.fail_times["obligation.created.dlq"] = 1
    relay = make_relay(store, producer, clock)
    (row,) = store.rows.values()
    for _ in range(2):
        await relay.run_once()
        clock.advance(600)
    assert await relay.run_once() == RelayStats(claimed=1, retried=1)
    assert row.status == "pending"
    assert row.attempts == 3
    clock.advance(600)
    assert await relay.run_once() == RelayStats(claimed=1, dead=1)
    assert row.status == "dead"
    assert row.attempts == 4


async def test_one_failure_does_not_stop_the_rest_of_the_batch() -> None:
    store, producer, clock = MemoryOutboxStore(), FakeProducer(), Clock()
    seed(store, 3)
    producer.fail_times["obligation.created"] = 1
    stats = await make_relay(store, producer, clock).run_once()
    assert stats == RelayStats(claimed=3, published=2, retried=1)
    assert store.statuses() == {"published": 2, "pending": 1}


async def test_run_forever_stops_when_asked() -> None:
    store, producer, clock = MemoryOutboxStore(), FakeProducer(), Clock()
    seed(store, 2)
    relay = make_relay(store, producer, clock, poll_interval_seconds=0.01)
    stop = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    total, _ = await asyncio.gather(relay.run_forever(stop), stop_soon())
    assert total == RelayStats(claimed=2, published=2)
    assert store.batches >= 2


def test_backoff_doubles_and_caps() -> None:
    config = RelayConfig(base_backoff_seconds=1.0, max_backoff_seconds=300.0)
    assert [backoff_seconds(n, config) for n in (1, 2, 3, 8, 9, 20)] == [1, 2, 4, 128, 256, 300]
    assert backoff_seconds(1) == 1.0
    with pytest.raises(ValueError, match="attempts"):
        backoff_seconds(0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"batch_size": 0},
        {"max_attempts": 0},
        {"poll_interval_seconds": 0},
        {"base_backoff_seconds": 0},
        {"base_backoff_seconds": 10, "max_backoff_seconds": 5},
    ],
)
def test_config_rejects_nonsense(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="must"):
        RelayConfig(**kwargs)  # type: ignore[arg-type]


def test_stats_add() -> None:
    assert RelayStats(1, 1) + RelayStats(2, 0, 1, 1) == RelayStats(3, 1, 1, 1)
