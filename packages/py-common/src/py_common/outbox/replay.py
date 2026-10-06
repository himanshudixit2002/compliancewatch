"""Dead letters: list a dead-letter topic, and send one of its messages back to where it came from.

Two kinds of dead letter reach Kafka, both with the message's own key and value:

- the relay's, on ``<topic>.dlq``: an outbox row whose sends failed ``max_attempts`` times
  (``py_common.outbox.relay``); the row is ``dead`` in its service's outbox;
- a consumer's, on ``<topic>.<group>.dlq``: a message the group's handler could not process
  (``py_common.outbox.consumer``); it was delivered, so the fix lives in the consumer.

Each carries the relay's headers (``event_id``, ``topic``, ``schema_version``, ``content-type``)
and the dead-letter ones: ``origin_topic``, ``attempts`` and ``error``, and a consumer's also
``consumer_group``.

``DeadLetters.list(topic)`` reads every message of a dead-letter topic from its first offset to
its end as it stands when the call starts, as a reader with no consumer group: nothing is
committed and no group sees the read, so listing changes nothing. ``DeadLetters.replay(topic,
event_id)`` sends the last message with that event id back to its origin topic (the
``origin_topic`` header; ``to`` names another) with the same key and value and its headers less
the dead-letter ones. Every consumer group of the origin topic then reads it again: the groups
that took it in skip it, since they deduplicate on the event id, and the one that failed runs its
handler again. An event id the topic does not hold is ``UnknownDeadLetterError``, a topic the
broker does not have ``UnknownTopicError``; a message is never sent to a dead-letter topic.

For a relay's dead letter, the outbox row is the source of truth: putting the row back to pending
(``py_common.outbox.admin.OutboxAdmin.requeue``, the pipeline's
``POST /v1/pipeline/outbox/{event_id}/requeue``) has the relay send it again and marks it
published. Replaying the message works too, but leaves the row dead.

``python -m py_common.outbox.replay`` (``make replay``) is the command line, on the cluster
``CW_KAFKA_BOOTSTRAP`` and the ``CW_KAFKA_*`` credentials name::

    python -m py_common.outbox.replay list --topic <dead-letter topic> [--json]
    python -m py_common.outbox.replay send --topic <dead-letter topic> --event-id <uuid> \
        [--to <topic>] [--dry-run]

``list`` prints one line per message (``--json`` for JSON); ``send`` prints what it sent, or with
``--dry-run`` what it would send. Exit status: 0 done, 1 an unknown event id or topic, or a
message that cannot go back, 2 the broker did not answer.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol
from uuid import UUID

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.errors import KafkaError

from py_common.kafka import KafkaClientConfig
from py_common.outbox.consumer import InboundRecord
from py_common.outbox.producer import AiokafkaProducer, MessageProducer

DLQ_SUFFIX: Final = ".dlq"
DEAD_LETTER_HEADERS: Final = frozenset({"origin_topic", "consumer_group", "attempts", "error"})
"""The headers a dead-letter send adds; a replay sends the message without them."""
READ_TIMEOUT_SECONDS: Final = 30.0
MAX_ERROR_CHARS: Final = 300


class UnknownTopicError(LookupError):
    """The broker has no topic of this name."""


class UnknownDeadLetterError(LookupError):
    """The dead-letter topic holds no message with this event id."""


class ReplayRefusedError(ValueError):
    """The message cannot go back: it names no origin topic and none was given, or the topic it
    would go to is itself a dead-letter topic."""


class TopicReader(Protocol):
    """Reads a whole topic, from its first offset to its end when the call starts, with no
    consumer group."""

    async def read(self, topic: str) -> Sequence[InboundRecord]: ...


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """One message of a dead-letter topic, as its headers and envelope describe it."""

    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes
    headers: tuple[tuple[str, bytes], ...]
    event_id: UUID | None
    event_topic: str
    origin_topic: str
    consumer_group: str
    attempts: int | None
    error: str

    @classmethod
    def of(cls, record: InboundRecord) -> "DeadLetter":
        headers = tuple(record.headers)
        named = dict(headers)

        def text(name: str) -> str:
            return named.get(name, b"").decode("utf-8", errors="replace")

        attempts = text("attempts")
        return cls(
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
            key=record.key,
            value=record.value,
            headers=headers,
            event_id=_event_id(text("event_id"), record.value),
            event_topic=text("topic"),
            origin_topic=text("origin_topic"),
            consumer_group=text("consumer_group"),
            attempts=int(attempts) if attempts.isdigit() else None,
            error=text("error")[:MAX_ERROR_CHARS],
        )

    def replayed_headers(self) -> list[tuple[str, bytes]]:
        """The headers the message is sent back with: its own, less the dead-letter ones."""
        return [(name, value) for name, value in self.headers if name not in DEAD_LETTER_HEADERS]

    def as_json(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "partition": self.partition,
            "offset": self.offset,
            "event_id": None if self.event_id is None else str(self.event_id),
            "event_topic": self.event_topic,
            "origin_topic": self.origin_topic,
            "consumer_group": self.consumer_group or None,
            "attempts": self.attempts,
            "error": self.error,
            "key": None if self.key is None else self.key.decode("utf-8", errors="replace"),
            "bytes": len(self.value),
        }


def _event_id(header: str, value: bytes) -> UUID | None:
    """The message's event id: its header, else the envelope's ``event_id``."""
    for candidate in (header, _envelope_id(value)):
        try:
            return UUID(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _envelope_id(value: bytes) -> str:
    try:
        envelope = json.loads(value)
    except (UnicodeDecodeError, ValueError):
        return ""
    found = envelope.get("event_id") if isinstance(envelope, dict) else None
    return found if isinstance(found, str) else ""


@dataclass(frozen=True, slots=True)
class Replayed:
    """What a replay sent, or with ``dry_run`` would send: the message to ``to``."""

    letter: DeadLetter
    to: str
    sent: bool


class DeadLetters:
    """Lists a dead-letter topic and sends one of its messages back."""

    def __init__(self, reader: TopicReader, producer: MessageProducer) -> None:
        self._reader = reader
        self._producer = producer

    async def list(self, topic: str) -> list[DeadLetter]:
        """Every message of ``topic``, oldest first per partition."""
        return [DeadLetter.of(record) for record in await self._reader.read(topic)]

    async def replay(
        self, topic: str, event_id: UUID, *, to: str | None = None, dry_run: bool = False
    ) -> Replayed:
        """Send the last message of ``topic`` with ``event_id`` to its origin topic (or ``to``),
        with its key, value and headers less the dead-letter ones."""
        letters = await self.list(topic)
        matching = [letter for letter in letters if letter.event_id == event_id]
        if not matching:
            raise UnknownDeadLetterError(
                f"{topic} holds no message with event id {event_id} "
                f"({len(letters)} message{'' if len(letters) == 1 else 's'} read)"
            )
        letter = max(matching, key=lambda found: (found.partition, found.offset))
        target = (to or letter.origin_topic).strip()
        if not target:
            raise ReplayRefusedError(
                f"the message with event id {event_id} names no origin topic: name one with to"
            )
        if target.endswith(DLQ_SUFFIX):
            raise ReplayRefusedError(f"{target} is a dead-letter topic; a replay never goes there")
        if not dry_run:
            await self._producer.send(
                target,
                key=letter.key or b"",
                value=letter.value,
                headers=letter.replayed_headers(),
            )
        return Replayed(letter, target, not dry_run)


class AiokafkaTopicReader:
    """``TopicReader`` on a Kafka cluster: an aiokafka consumer with no group, assigned every
    partition of the topic from its first offset, reading until it reaches the end offsets it
    found when it started (or ``timeout_seconds`` pass). It never commits, and a topic the broker
    lacks is ``UnknownTopicError``, never created."""

    def __init__(
        self,
        kafka: KafkaClientConfig | str,
        *,
        client_id: str = "cw-outbox-replay",
        timeout_seconds: float = READ_TIMEOUT_SECONDS,
    ) -> None:
        self._kafka = KafkaClientConfig.of(kafka)
        self._client_id = client_id
        self._timeout = timeout_seconds

    async def read(self, topic: str) -> list[InboundRecord]:
        consumer = AIOKafkaConsumer(
            **self._kafka.aiokafka_kwargs(),
            client_id=self._client_id,
            group_id=None,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            if topic not in await consumer.topics():
                raise UnknownTopicError(f"no topic {topic} on the broker")
            # With no group, a subscription is assigned every partition of the topic as soon as
            # the client's metadata names them; nothing is committed.
            consumer.subscribe([topic])
            partitions = await self._assigned(consumer)
            await consumer.seek_to_beginning(*partitions)
            ends = await consumer.end_offsets(partitions)
            return await self._until(consumer, ends)
        finally:
            await consumer.stop()

    async def _assigned(self, consumer: AIOKafkaConsumer) -> list[TopicPartition]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while not consumer.assignment():
            if loop.time() >= deadline:
                raise TimeoutError("the broker named no partition of the topic in time")
            await asyncio.sleep(0.05)
        return sorted(consumer.assignment(), key=lambda tp: tp.partition)

    async def _until(
        self, consumer: AIOKafkaConsumer, ends: dict[TopicPartition, int]
    ) -> list[InboundRecord]:
        records: list[InboundRecord] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        waiting = {tp for tp, end in ends.items() if end > 0}
        while waiting and loop.time() < deadline:
            batches = await consumer.getmany(*waiting, timeout_ms=1000)
            for tp, found in batches.items():
                for raw in found:
                    if raw.offset < ends[tp]:
                        records.append(
                            InboundRecord(
                                topic=raw.topic,
                                partition=raw.partition,
                                offset=raw.offset,
                                key=raw.key,
                                value=raw.value,
                                headers=tuple(raw.headers or ()),
                            )
                        )
            waiting = {tp for tp in waiting if await consumer.position(tp) < ends[tp]}
        return sorted(records, key=lambda record: (record.partition, record.offset))


Run = Callable[["argparse.Namespace", DeadLetters], Awaitable[int]]


def _line(letter: DeadLetter) -> str:
    group = f" group {letter.consumer_group}" if letter.consumer_group else ""
    attempts = "?" if letter.attempts is None else str(letter.attempts)
    return (
        f"{letter.partition}:{letter.offset} event {letter.event_id} from "
        f"{letter.origin_topic or '?'}{group}, {attempts} attempt(s): {letter.error or '-'}"
    )


async def _list(args: argparse.Namespace, letters: DeadLetters) -> int:
    found = await letters.list(args.topic)
    if args.json:
        sys.stdout.write(json.dumps([letter.as_json() for letter in found], indent=2) + "\n")
        return 0
    sys.stdout.write(f"{args.topic}: {len(found)} message(s)\n")
    for letter in found:
        sys.stdout.write(_line(letter) + "\n")
    return 0


async def _send(args: argparse.Namespace, letters: DeadLetters) -> int:
    replayed = await letters.replay(args.topic, args.event_id, to=args.to, dry_run=args.dry_run)
    verb = "sent" if replayed.sent else "would send"
    sys.stdout.write(
        f"{verb} event {replayed.letter.event_id} from {args.topic} "
        f"({replayed.letter.partition}:{replayed.letter.offset}) to {replayed.to}\n"
    )
    return 0


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(
        prog="python -m py_common.outbox.replay",
        description="List a dead-letter topic, or send one of its messages back to its origin.",
    )
    commands = found.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="every message of a dead-letter topic, read only")
    listing.add_argument("--topic", required=True, help="the dead-letter topic: <topic>.dlq ...")
    listing.add_argument("--json", action="store_true", help="print JSON")
    send = commands.add_parser("send", help="send one message back to its origin topic")
    send.add_argument("--topic", required=True, help="the dead-letter topic it is on")
    send.add_argument("--event-id", required=True, type=UUID, help="the message's event id")
    send.add_argument("--to", default=None, help="send it here instead of its origin_topic")
    send.add_argument("--dry-run", action="store_true", help="say what it would send; send none")
    return found


async def run(
    argv: Sequence[str] | None,
    *,
    reader: TopicReader,
    producer: Callable[[], MessageProducer | AiokafkaProducer],
) -> int:
    """The command on ``reader`` and the producer ``producer`` makes (started and stopped here
    when it is an ``AiokafkaProducer``)."""
    args = parser().parse_args(argv)
    commands: dict[str, Run] = {"list": _list, "send": _send}
    made = producer()
    try:
        if isinstance(made, AiokafkaProducer) and args.command == "send" and not args.dry_run:
            await made.start()
        return await commands[args.command](args, DeadLetters(reader, made))
    except (UnknownTopicError, UnknownDeadLetterError, ReplayRefusedError) as exc:
        sys.stderr.write(f"replay: {exc}\n")
        return 1
    except (OSError, KafkaError, TimeoutError) as exc:
        sys.stderr.write(f"replay: the broker did not answer: {type(exc).__name__}: {exc}\n")
        return 2
    finally:
        if isinstance(made, AiokafkaProducer):
            await made.stop()


def main(argv: Sequence[str] | None = None) -> int:
    # Imported here: the settings read .env, which a test of ``run`` does without.
    from py_common.settings import Settings

    settings = Settings(service_name="outbox-replay")
    kafka = KafkaClientConfig.from_settings(settings)
    return asyncio.run(
        run(
            argv,
            reader=AiokafkaTopicReader(kafka),
            producer=lambda: AiokafkaProducer(kafka, client_id="cw-outbox-replay"),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
