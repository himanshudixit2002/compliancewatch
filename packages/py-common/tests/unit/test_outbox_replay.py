"""Dead letters listed and replayed with the fake producer and consumer: a consumer's dead letter
goes back to its origin without the dead-letter headers and is taken in; the relay's too; an
unknown event id or topic answers clearly; the command line lists, sends and dry-runs."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import UUID

import pytest

from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId
from py_common.events import EventMessage, decode, encode, kafka_headers, to_message
from py_common.outbox.consumer import ConsumerConfig, IdempotentConsumer, InboundRecord, Outcome
from py_common.outbox.relay import OutboxRelay, RelayConfig
from py_common.outbox.replay import (
    DEAD_LETTER_HEADERS,
    DeadLetter,
    DeadLetters,
    ReplayRefusedError,
    UnknownDeadLetterError,
    UnknownTopicError,
    run,
)
from py_common.outbox.store import UnitOfWork
from py_common.outbox.testing import (
    FakeConsumer,
    FakeProducer,
    MemoryOutboxStore,
    MemoryProcessedStore,
)

TOPIC = "rule.candidate.created"
GROUP = "rulebook.rule-candidates"
CONSUMER_DLQ = f"{TOPIC}.{GROUP}.dlq"
RELAY_DLQ = f"{TOPIC}.dlq"
T0 = datetime(2000, 1, 3, 6, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class CandidateCreated(DomainEvent):
    topic: ClassVar[str] = TOPIC
    title: str


class Handler:
    """Fails while ``away`` (the consumer's database is away), then takes the event in."""

    def __init__(self, *, away: bool) -> None:
        self.away = away
        self.taken: list[EventMessage] = []

    async def __call__(self, message: EventMessage, unit: UnitOfWork) -> None:
        if self.away:
            raise ConnectionError("the example database is away")
        self.taken.append(message)


async def no_sleep(_: float) -> None:
    return None


def consumer(
    handler: Handler, producer: FakeProducer, store: MemoryProcessedStore
) -> IdempotentConsumer:
    return IdempotentConsumer(
        group_id=GROUP,
        store=store,
        handler=handler,
        producer=producer,
        config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        sleep=no_sleep,
    )


def message(title: str = "Example candidate") -> EventMessage:
    return to_message(CandidateCreated(tenant_id=TenantId.new(), title=title))


def inbound(found: EventMessage, offset: int = 0) -> InboundRecord:
    return InboundRecord(
        topic=found.topic,
        partition=0,
        offset=offset,
        key=b"example-key",
        value=encode(found),
        headers=tuple(kafka_headers(found)),
    )


async def dead_lettered() -> tuple[EventMessage, FakeProducer, Handler, IdempotentConsumer]:
    """A candidate the consumer could not take in while its database was away."""
    producer, handler, store = FakeProducer(), Handler(away=True), MemoryProcessedStore()
    group = consumer(handler, producer, store)
    found = message()
    assert await group.process(inbound(found)) is Outcome.DEAD
    return found, producer, handler, group


async def test_a_consumer_dead_letter_is_listed_with_its_origin_and_why() -> None:
    found, producer, _, _ = await dead_lettered()
    letters = DeadLetters(FakeConsumer.of(producer), FakeProducer())
    (letter,) = await letters.list(CONSUMER_DLQ)
    assert (letter.event_id, letter.origin_topic, letter.consumer_group, letter.attempts) == (
        found.event_id,
        TOPIC,
        GROUP,
        2,
    )
    assert "the example database is away" in letter.error
    assert (letter.topic, letter.partition, letter.offset, letter.key) == (
        CONSUMER_DLQ,
        0,
        0,
        b"example-key",
    )
    assert letter.as_json()["event_id"] == str(found.event_id)


async def test_a_replay_sends_it_back_without_the_dead_letter_headers_and_it_is_taken_in() -> None:
    found, producer, handler, group = await dead_lettered()
    reader, sender = FakeConsumer.of(producer), FakeProducer()
    replayed = await DeadLetters(reader, sender).replay(CONSUMER_DLQ, found.event_id)
    assert (replayed.to, replayed.sent) == (TOPIC, True)
    (sent,) = sender.sent
    assert (sent.topic, sent.key) == (TOPIC, b"example-key")
    assert decode(sent.value) == found
    assert not {name for name, _ in sent.headers} & DEAD_LETTER_HEADERS
    assert sent.header("event_id") == str(found.event_id).encode()
    assert reader.reads == [CONSUMER_DLQ], "the dead-letter topic is only read"

    handler.away = False
    again = InboundRecord(TOPIC, 0, 1, sent.key, sent.value, tuple(sent.headers))
    assert await group.process(again) is Outcome.PROCESSED
    assert [taken.event_id for taken in handler.taken] == [found.event_id]
    assert await group.process(again) is Outcome.SKIPPED, "a second replay changes nothing"


async def test_a_relay_dead_letter_goes_back_to_its_topic() -> None:
    store, producer = MemoryOutboxStore(), FakeProducer()
    found = message()
    store.add(found, partition_key="example-source", available_at=T0)
    producer.fail_times[TOPIC] = 2
    moments = iter(T0 + timedelta(minutes=minute) for minute in range(100))
    relay = OutboxRelay(
        store=store,
        producer=producer,
        config=RelayConfig(max_attempts=2, base_backoff_seconds=1),
        clock=lambda: next(moments),
    )
    await relay.run_once()
    await relay.run_once()
    (row,) = store.rows.values()
    assert row.status == "dead"
    assert T0 < row.available_at < T0 + timedelta(hours=1), "when it went dead"
    sender = FakeProducer()
    letters = DeadLetters(FakeConsumer.of(producer), sender)
    (letter,) = await letters.list(RELAY_DLQ)
    assert (letter.origin_topic, letter.consumer_group, letter.attempts) == (TOPIC, "", 2)
    await letters.replay(RELAY_DLQ, found.event_id)
    (sent,) = sender.sent
    assert (sent.topic, sent.key, decode(sent.value)) == (TOPIC, b"example-source", found)


async def test_the_last_copy_of_an_event_is_the_one_replayed() -> None:
    found, producer, _, group = await dead_lettered()
    assert await group.process(inbound(found, offset=1)) is Outcome.DEAD
    reader = FakeConsumer.of(producer)
    replayed = await DeadLetters(reader, FakeProducer()).replay(CONSUMER_DLQ, found.event_id)
    assert replayed.letter.offset == 1


async def test_an_unknown_event_id_and_an_unknown_topic_answer_clearly() -> None:
    _, producer, _, _ = await dead_lettered()
    letters = DeadLetters(FakeConsumer.of(producer), FakeProducer())
    nobody = UUID(int=7)
    with pytest.raises(UnknownDeadLetterError, match=f"holds no message with event id {nobody}"):
        await letters.replay(CONSUMER_DLQ, nobody)
    with pytest.raises(UnknownDeadLetterError, match=r"\(1 message read\)"):
        await letters.replay(CONSUMER_DLQ, nobody)
    with pytest.raises(UnknownTopicError, match=r"no topic example\.dlq"):
        await letters.list("example.dlq")


async def test_a_message_never_goes_to_a_dead_letter_topic_or_nowhere() -> None:
    found, producer, _, _ = await dead_lettered()
    letters = DeadLetters(FakeConsumer.of(producer), FakeProducer())
    with pytest.raises(ReplayRefusedError, match="is a dead-letter topic"):
        await letters.replay(CONSUMER_DLQ, found.event_id, to=RELAY_DLQ)
    bare = FakeConsumer()
    bare.append("bare.dlq", None, encode(found), [])
    with pytest.raises(ReplayRefusedError, match="names no origin topic"):
        await DeadLetters(bare, FakeProducer()).replay("bare.dlq", found.event_id)
    sender = FakeProducer()
    replayed = await DeadLetters(bare, sender).replay("bare.dlq", found.event_id, to=TOPIC)
    assert (replayed.letter.event_id, sender.topics()) == (found.event_id, [TOPIC]), (
        "the envelope gives the event id when no header does"
    )
    assert sender.sent[0].key == b""


def test_a_letter_without_an_event_id_or_attempts_reads_as_unknown() -> None:
    letter = DeadLetter.of(InboundRecord("x.dlq", 0, 3, None, b"not json", (("attempts", b"x"),)))
    assert (letter.event_id, letter.attempts, letter.origin_topic) == (None, None, "")


async def test_the_command_lists_sends_and_dry_runs(capsys: pytest.CaptureFixture[str]) -> None:
    found, producer, _, _ = await dead_lettered()
    reader, sender = FakeConsumer.of(producer), FakeProducer()

    def made() -> FakeProducer:
        return sender

    assert await run(["list", "--topic", CONSUMER_DLQ], reader=reader, producer=made) == 0
    listed = capsys.readouterr().out
    assert f"{CONSUMER_DLQ}: 1 message(s)" in listed
    assert f"event {found.event_id} from {TOPIC} group {GROUP}, 2 attempt(s)" in listed
    assert await run(["list", "--topic", CONSUMER_DLQ, "--json"], reader=reader, producer=made) == 0
    assert f'"event_id": "{found.event_id}"' in capsys.readouterr().out

    args = ["send", "--topic", CONSUMER_DLQ, "--event-id", str(found.event_id)]
    assert await run([*args, "--dry-run"], reader=reader, producer=made) == 0
    assert capsys.readouterr().out.startswith(f"would send event {found.event_id}")
    assert sender.sent == []
    assert await run(args, reader=reader, producer=made) == 0
    assert capsys.readouterr().out.startswith(f"sent event {found.event_id}")
    assert sender.topics() == [TOPIC]

    unknown = ["send", "--topic", CONSUMER_DLQ, "--event-id", str(UUID(int=9))]
    assert await run(unknown, reader=reader, producer=made) == 1
    assert "holds no message with event id" in capsys.readouterr().err
    assert await run(["list", "--topic", "nothing.dlq"], reader=reader, producer=made) == 1
    assert "no topic nothing.dlq" in capsys.readouterr().err


async def test_a_broker_that_does_not_answer_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    class Away:
        async def read(self, topic: str) -> list[InboundRecord]:
            raise ConnectionRefusedError("example broker away")

    assert await run(["list", "--topic", RELAY_DLQ], reader=Away(), producer=FakeProducer) == 2
    assert "the broker did not answer" in capsys.readouterr().err
