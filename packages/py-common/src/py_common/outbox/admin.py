"""The outbox as an operator sees it: the dead rows, one row, and a dead row put back to pending.

The relay marks a row ``dead`` once ``max_attempts`` sends failed and its message reached
``<topic>.dlq``; the row keeps when that happened in ``available_at``, which the relay never reads
for a dead row (``OutboxRow.dead_at``). ``OutboxAdmin`` reads and changes the table on the caller's
sync connection, inside its transaction, so a service's admin route commits the change with its
audit row:

- ``dead(topic=..., after=..., limit=...)``: the dead rows, the newest dead first (then by id from
  the highest), a page at a time after ``after``;
- ``get(event_id)``: one row whatever its status, None for an id the table does not hold;
  ``for_update`` holds the row until the transaction ends, so a requeue reads the row it moves
  as no other request can change it meanwhile;
- ``requeue(event_id, at=...)``: a dead row back to ``pending`` with its attempts reset and due at
  ``at``, so the relay sends it again on its next pass; ``last_error`` stays until a send
  succeeds. False, with nothing changed, for a row that is not dead.

``MemoryOutboxStore`` (``py_common.outbox.testing``) answers the same three, for memory stores.
The message's payload is returned as the table holds it: a route that lists dead rows shows a
summary of it (``payload_summary``), never the body.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

from sqlalchemy import Connection, Row, select, tuple_, update

from py_common.outbox.schema import STATUS_DEAD, STATUS_PENDING, outbox_event

SUMMARY_FIELDS: Final = (
    "document_id",
    "source_id",
    "source_key",
    "regulator",
    "external_ref",
    "candidate_id",
    "rule_version_id",
    "rule_key",
    "doc_type",
    "outcome",
    "prompt_version",
)
"""The payload fields a summary keeps when they hold a short text, a number or a flag: what the
event is about, never what it says."""
MAX_SUMMARY_VALUE: Final = 200


@dataclass(frozen=True, slots=True)
class OutboxRow:
    """One ``outbox_event`` row. ``message`` is the wire message, envelope and payload."""

    event_id: UUID
    topic: str
    schema_version: str
    partition_key: str
    tenant_id: UUID | None
    occurred_at: datetime
    created_at: datetime
    status: str
    attempts: int
    available_at: datetime
    published_at: datetime | None
    last_error: str
    message: Mapping[str, Any]

    @property
    def is_dead(self) -> bool:
        return self.status == STATUS_DEAD

    @property
    def dead_at(self) -> datetime | None:
        """When the relay marked it dead; None for a row that is not dead."""
        return self.available_at if self.is_dead else None

    @property
    def payload(self) -> Mapping[str, Any]:
        found = self.message.get("payload")
        return found if isinstance(found, Mapping) else {}


@dataclass(frozen=True, slots=True)
class DeadKey:
    """Where a page of dead rows starts: after the row that went dead at ``dead_at`` with
    ``event_id``."""

    dead_at: datetime
    event_id: UUID

    @classmethod
    def of(cls, row: OutboxRow) -> "DeadKey":
        if row.dead_at is None:
            raise ValueError(f"outbox row {row.event_id} is not dead")
        return cls(row.dead_at, row.event_id)


class DeadRows(Protocol):
    """The dead rows of one outbox and the requeue of one: ``OutboxAdmin`` on a connection,
    ``MemoryOutboxStore`` in memory."""

    def dead(
        self, *, topic: str | None = None, after: DeadKey | None = None, limit: int = 50
    ) -> Sequence[OutboxRow]: ...

    def get(self, event_id: UUID, *, for_update: bool = False) -> OutboxRow | None: ...

    def requeue(self, event_id: UUID, *, at: datetime) -> bool: ...


def payload_summary(payload: Mapping[str, Any]) -> dict[str, object]:
    """The fields of ``SUMMARY_FIELDS`` the payload holds as a short text, a number or a flag."""
    summary: dict[str, object] = {}
    for name in SUMMARY_FIELDS:
        value = payload.get(name)
        short = isinstance(value, str) and len(value) <= MAX_SUMMARY_VALUE
        if short or isinstance(value, bool | int | float):
            summary[name] = value
    return summary


class OutboxAdmin:
    """``DeadRows`` on the caller's connection: no commit, no rollback."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def dead(
        self, *, topic: str | None = None, after: DeadKey | None = None, limit: int = 50
    ) -> Sequence[OutboxRow]:
        statement = select(outbox_event).where(outbox_event.c.status == STATUS_DEAD)
        if topic is not None:
            statement = statement.where(outbox_event.c.topic == topic)
        if after is not None:
            statement = statement.where(
                tuple_(outbox_event.c.available_at, outbox_event.c.id)
                < tuple_(after.dead_at, after.event_id)
            )
        statement = statement.order_by(
            outbox_event.c.available_at.desc(), outbox_event.c.id.desc()
        ).limit(limit)
        return [_row(found) for found in self._connection.execute(statement)]

    def get(self, event_id: UUID, *, for_update: bool = False) -> OutboxRow | None:
        statement = select(outbox_event).where(outbox_event.c.id == event_id)
        if for_update:
            statement = statement.with_for_update()
        found = self._connection.execute(statement).first()
        return None if found is None else _row(found)

    def requeue(self, event_id: UUID, *, at: datetime) -> bool:
        moved = self._connection.execute(
            update(outbox_event)
            .where(outbox_event.c.id == event_id, outbox_event.c.status == STATUS_DEAD)
            .values(status=STATUS_PENDING, attempts=0, available_at=at)
            .returning(outbox_event.c.id)
        ).first()
        return moved is not None


def _aware(moment: datetime) -> datetime:
    """A timestamp as UTC; a store that hands back naive ones (SQLite) holds UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _row(found: Row[Any]) -> OutboxRow:
    published = found.published_at
    return OutboxRow(
        event_id=found.id,
        topic=found.topic,
        schema_version=found.schema_version,
        partition_key=found.partition_key,
        tenant_id=found.tenant_id,
        occurred_at=_aware(found.occurred_at),
        created_at=_aware(found.created_at),
        status=found.status,
        attempts=found.attempts,
        available_at=_aware(found.available_at),
        published_at=None if published is None else _aware(published),
        last_error=found.last_error,
        message=found.message,
    )
