"""The pipeline's outbox as an operator sees it: its rows, the dead ones above all.

The relay publishes each ``outbox_event`` row and marks it ``published``; after eight failed sends
it puts the message on ``<topic>.dlq`` and marks the row ``dead``, keeping when it went dead
(``dead_at``). A dead row is requeued (back to ``pending``, its attempts reset, due at once) for the
relay to send again. An ``OutboxEvent`` carries a summary of the payload (what it is about: the
document, the source, the candidate) and its size, never its body.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    DEAD = "dead"


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """One outbox row without its body: the topic, key and schema version, how it stands, how
    many sends failed, the last error, when it went dead (dead rows only), and the payload's
    summary and size in bytes."""

    event_id: UUID
    topic: str
    schema_version: str
    partition_key: str
    status: OutboxStatus
    attempts: int
    last_error: str
    occurred_at: datetime
    created_at: datetime
    published_at: datetime | None = None
    dead_at: datetime | None = None
    summary: Mapping[str, object] = field(default_factory=dict, hash=False)
    payload_bytes: int = 0

    @property
    def is_dead(self) -> bool:
        return self.status is OutboxStatus.DEAD


@dataclass(frozen=True, slots=True)
class DeadEventKey:
    """Where a page of dead rows starts: after the row that went dead at ``dead_at`` with
    ``event_id``. Rows come the newest dead first, then by id from the highest."""

    dead_at: datetime
    event_id: UUID

    @classmethod
    def of(cls, event: OutboxEvent) -> "DeadEventKey":
        if event.dead_at is None:
            raise ValueError(f"outbox event {event.event_id} is not dead")
        return cls(event.dead_at, event.event_id)
