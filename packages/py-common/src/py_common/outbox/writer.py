"""Write an event into the outbox inside the caller's transaction."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, insert

from domain_kernel.events import DomainEvent, utc_now
from py_common.events import EventMessage, to_message
from py_common.outbox.schema import STATUS_PENDING, outbox_event

Validator = Callable[[EventMessage], None]
"""Raises when a message does not follow its topic's schema; the write is then not made."""


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    """What was written: the row's keys and the message it carries."""

    event_id: UUID
    topic: str
    schema_version: str
    partition_key: str
    tenant_id: UUID | None
    occurred_at: datetime
    message: EventMessage


class OutboxWriter:
    """Insert one row per event on the connection whose transaction holds the state change.

    The row commits or rolls back with that transaction, which is the whole point of the
    pattern. ``partition_key`` is the Kafka message key and decides ordering: pass the aggregate
    id for regulatory events; tenant events default to the tenant id, others to the event id.
    """

    def __init__(
        self, *, validator: Validator | None = None, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._validator = validator
        self._clock = clock

    def write(
        self, connection: Connection, event: DomainEvent, *, partition_key: str | None = None
    ) -> OutboxRecord:
        message = to_message(event)
        if self._validator is not None:
            self._validator(message)
        key = partition_key or (
            str(message.tenant_id) if message.tenant_id is not None else str(message.event_id)
        )
        if not key.strip():
            raise ValueError("partition_key must not be blank")
        record = OutboxRecord(
            event_id=message.event_id,
            topic=message.topic,
            schema_version=message.schema_version,
            partition_key=key,
            tenant_id=message.tenant_id,
            occurred_at=message.occurred_at,
            message=message,
        )
        connection.execute(
            insert(outbox_event).values(
                id=record.event_id,
                topic=record.topic,
                schema_version=record.schema_version,
                partition_key=record.partition_key,
                tenant_id=record.tenant_id,
                occurred_at=record.occurred_at,
                message=message.model_dump(mode="json"),
                status=STATUS_PENDING,
                attempts=0,
                available_at=self._clock(),
            )
        )
        return record
