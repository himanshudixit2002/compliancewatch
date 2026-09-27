import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, CorrelationId, EventId, ObligationId, TenantId
from py_common.events import (
    CONTENT_TYPE,
    DecodeError,
    EventMessage,
    decode,
    encode,
    kafka_headers,
    payload_of,
    to_json_value,
    to_message,
)


class Reason(StrEnum):
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class Step:
    title: str
    due_in_days: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationClosed(DomainEvent):
    topic: ClassVar[str] = "obligation.closed"
    schema_version: ClassVar[str] = "1.2.0"

    obligation_id: ObligationId
    business_id: BusinessId
    reason: Reason
    closed_at: datetime
    amount: Decimal
    due_on: date
    steps: tuple[Step, ...]
    tags: frozenset[str]
    extra: Mapping[str, object]
    note: str | None = None


IST = timezone(timedelta(hours=5, minutes=30))
TENANT = TenantId.new()


def sample() -> ObligationClosed:
    return ObligationClosed(
        tenant_id=TENANT,
        obligation_id=ObligationId.new(),
        business_id=BusinessId.new(),
        reason=Reason.COMPLETED,
        closed_at=datetime(2026, 10, 20, 11, 5, tzinfo=IST),
        amount=Decimal("1500.50"),
        due_on=date(2026, 10, 25),
        steps=(Step("Reconcile ITC", 3), Step("File")),
        tags=frozenset({"gst", "filing"}),
        extra={"channel": "whatsapp", "count": 2},
    )


def test_payload_converts_every_supported_type() -> None:
    event = sample()
    payload = payload_of(event)
    assert payload == {
        "obligation_id": str(event.obligation_id),
        "business_id": str(event.business_id),
        "reason": "completed",
        "closed_at": "2026-10-20T11:05:00+05:30",
        "amount": "1500.50",
        "due_on": "2026-10-25",
        "steps": [
            {"title": "Reconcile ITC", "due_in_days": 3},
            {"title": "File", "due_in_days": None},
        ],
        "tags": ["filing", "gst"],
        "extra": {"channel": "whatsapp", "count": 2},
        "note": None,
    }
    json.dumps(payload)


def test_envelope_fields_are_not_in_the_payload() -> None:
    assert not {"event_id", "occurred_at", "tenant_id", "correlation_id", "causation_id"} & set(
        payload_of(sample())
    )


def test_unsupported_values_are_rejected() -> None:
    with pytest.raises(TypeError, match="bytes"):
        to_json_value(b"raw")
    with pytest.raises(TypeError, match="object"):
        to_json_value(object())


def test_to_message_copies_the_envelope() -> None:
    cause = EventId.new()
    event = ObligationClosed(
        **{
            k: getattr(sample(), k) for k in ("obligation_id", "business_id", "reason", "closed_at")
        },
        amount=Decimal(1),
        due_on=date(2026, 1, 1),
        steps=(),
        tags=frozenset(),
        extra={},
        tenant_id=TENANT,
        causation_id=cause,
    )
    message = to_message(event)
    assert message.event_id == event.event_id.value
    assert message.topic == "obligation.closed"
    assert message.schema_version == "1.2.0"
    assert message.occurred_at == event.occurred_at
    assert message.tenant_id == TENANT.value
    assert message.correlation_id == event.correlation_id.value
    assert message.causation_id == cause.value
    assert message.payload["steps"] == []


def test_regulatory_events_have_a_null_tenant() -> None:
    @dataclass(frozen=True, slots=True, kw_only=True)
    class RulePublished(DomainEvent):
        topic: ClassVar[str] = "rule.published"
        title: str

    message = to_message(RulePublished(title="x"))
    assert message.tenant_id is None
    assert message.causation_id is None


def test_encode_is_canonical_and_decode_round_trips() -> None:
    message = to_message(sample())
    data = encode(message)
    assert data.startswith(b'{"causation_id":null,"correlation_id":"')
    assert b" " not in data.split(b'"payload"')[0]
    assert decode(data) == message
    assert decode(encode(decode(data))) == message


def test_utc_timestamps_survive_a_round_trip() -> None:
    at = datetime(2026, 10, 1, 2, 31, 5, tzinfo=UTC)
    message = to_message(sample()).model_copy(update={"occurred_at": at})
    assert decode(encode(message)).occurred_at == at


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not json",
        b"[]",
        b'{"event_id": "x"}',
        json.dumps({**json.loads(encode(to_message(sample()))), "topic": "Bad.Topic"}).encode(),
        json.dumps({**json.loads(encode(to_message(sample()))), "schema_version": "1"}).encode(),
        json.dumps({**json.loads(encode(to_message(sample()))), "extra": 1}).encode(),
        json.dumps(
            {**json.loads(encode(to_message(sample()))), "occurred_at": "2026-10-01T02:31:05"}
        ).encode(),
    ],
)
def test_decode_rejects_bad_messages(data: bytes) -> None:
    with pytest.raises(DecodeError, match="not an event message"):
        decode(data)


def test_kafka_headers_carry_routing_fields() -> None:
    message = to_message(sample())
    assert kafka_headers(message) == [
        ("event_id", str(message.event_id).encode()),
        ("topic", b"obligation.closed"),
        ("schema_version", b"1.2.0"),
        ("content-type", CONTENT_TYPE.encode()),
    ]


def test_message_is_frozen() -> None:
    message = to_message(sample())
    with pytest.raises(Exception, match="frozen"):
        message.topic = "x.y"  # type: ignore[misc]


@given(
    st.text(min_size=1),
    st.integers(),
    st.booleans(),
    st.decimals(allow_nan=False, allow_infinity=False),
    st.dates(),
)
def test_scalars_round_trip_through_json(
    text: str, number: int, flag: bool, amount: Decimal, day: date
) -> None:
    @dataclass(frozen=True, slots=True, kw_only=True)
    class Sample(DomainEvent):
        topic: ClassVar[str] = "sample.made"
        text: str
        number: int
        flag: bool
        amount: Decimal
        day: date

    event = Sample(text=text, number=number, flag=flag, amount=amount, day=day)
    decoded = decode(encode(to_message(event)))
    assert decoded.payload == {
        "text": text,
        "number": number,
        "flag": flag,
        "amount": str(amount),
        "day": day.isoformat(),
    }
    assert isinstance(decoded.event_id, UUID)
    assert decoded.correlation_id == CorrelationId.parse(str(event.correlation_id)).value


def test_event_message_validates_its_fields_directly() -> None:
    with pytest.raises(ValueError, match="topic"):
        EventMessage(
            event_id=UUID(int=1),
            topic="nodots",
            schema_version="1.0.0",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            tenant_id=None,
            correlation_id=UUID(int=2),
            causation_id=None,
            payload={},
        )
