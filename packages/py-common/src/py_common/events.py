"""The wire form of a domain event.

``packages/contracts/events/schemas/envelope.v1.json`` describes the message; this module builds
it from a kernel ``DomainEvent`` and reads it back. The payload is every dataclass field that is
not part of the envelope, converted to JSON-friendly values: typed ids and UUIDs become strings,
dates and datetimes ISO 8601 text, decimals strings, enums their values, nested dataclasses
objects, tuples and frozensets lists.
"""

import dataclasses
import json
from collections.abc import Mapping, Sequence, Set
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from domain_kernel.events import DomainEvent
from domain_kernel.ids import EntityId

ENVELOPE_FIELDS = frozenset(
    {"event_id", "occurred_at", "tenant_id", "correlation_id", "causation_id"}
)
"""Dataclass fields of ``DomainEvent`` itself; everything else is payload."""

CONTENT_TYPE = "application/json"
TOPIC_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
SEMVER_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"


class DecodeError(ValueError):
    """The bytes are not a valid event message."""


class EventMessage(BaseModel):
    """One message on the bus: the envelope plus the topic's payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    topic: str = Field(pattern=TOPIC_PATTERN)
    schema_version: str = Field(pattern=SEMVER_PATTERN)
    occurred_at: AwareDatetime
    tenant_id: UUID | None
    correlation_id: UUID
    causation_id: UUID | None
    payload: dict[str, Any]


def to_json_value(value: object) -> object:
    """Convert one payload value to something ``json.dumps`` accepts. Raises for anything else."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, EntityId | UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_json_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, Set):
        return sorted(to_json_value(item) for item in value)  # type: ignore[type-var]
    if isinstance(value, Sequence | frozenset) and not isinstance(value, bytes | bytearray):
        return [to_json_value(item) for item in value]
    raise TypeError(f"cannot put a {type(value).__name__} into an event payload")


def payload_of(event: DomainEvent) -> dict[str, Any]:
    """The event's own fields, JSON-ready."""
    return {
        field.name: to_json_value(getattr(event, field.name))
        for field in dataclasses.fields(event)
        if field.name not in ENVELOPE_FIELDS
    }


def to_message(event: DomainEvent) -> EventMessage:
    return EventMessage(
        event_id=event.event_id.value,
        topic=type(event).topic,
        schema_version=type(event).schema_version,
        occurred_at=event.occurred_at,
        tenant_id=None if event.tenant_id is None else event.tenant_id.value,
        correlation_id=event.correlation_id.value,
        causation_id=None if event.causation_id is None else event.causation_id.value,
        payload=payload_of(event),
    )


def encode(message: EventMessage) -> bytes:
    """Compact UTF-8 JSON with sorted keys, so the same message always encodes the same way."""
    return json.dumps(
        message.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def decode(data: bytes) -> EventMessage:
    try:
        return EventMessage.model_validate_json(data)
    except ValidationError as exc:
        raise DecodeError(f"not an event message: {exc.errors()[0]['msg']}") from exc
    except ValueError as exc:
        raise DecodeError(f"not an event message: {exc}") from exc


def kafka_headers(message: EventMessage) -> list[tuple[str, bytes]]:
    """Headers that let a consumer route without parsing the value."""
    return [
        ("event_id", str(message.event_id).encode("ascii")),
        ("topic", message.topic.encode("ascii")),
        ("schema_version", message.schema_version.encode("ascii")),
        ("content-type", CONTENT_TYPE.encode("ascii")),
    ]
