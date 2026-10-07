"""Write an audit entry inside the caller's transaction.

``AuditWriter.write(connection, entry)`` inserts one ``audit.event`` row on the connection whose
transaction holds the action, as ``OutboxWriter`` does for events, so the row commits or rolls
back with the action. ``PostgresAuditSink`` is the kernel's ``AuditSink`` on one connection: what
a unit of work exposes as ``audit``. Row-level security admits a row of the tenant the
transaction's ``app.tenant_id`` names, or a row of no tenant; any other row fails the statement,
and with it the transaction.

The row is the entry masked for personal identifiers (``masking.masked_entry``, as the memory
twin stores it): GSTINs, PANs, Aadhaar numbers, phone numbers and email addresses in the reason,
and in every text of ``before`` and ``after`` at any depth, become ``[GSTIN]``, ``[PAN]``,
``[AADHAAR]``, ``[PHONE]`` and ``[EMAIL]``, with UUIDs, hex ids and the values of ``_id`` keys
kept whole. The action, the subject and its id, the actor and the correlation id are never
masked: they say who did what to which record.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, insert

from domain_kernel.audit import AuditActor, AuditActorKind, AuditEntry, AuditEntryId
from domain_kernel.ids import TenantId
from py_common.audit.masking import masked_entry
from py_common.audit.schema import audit_event


def audit_row(entry: AuditEntry) -> dict[str, Any]:
    """The column values of ``entry``'s row: the entry masked (``masked_entry``), with ``before``
    and ``after`` as plain JSON."""
    entry = masked_entry(entry)
    return {
        "id": entry.entry_id.value,
        "occurred_at": entry.occurred_at,
        "tenant_id": None if entry.tenant_id is None else entry.tenant_id.value,
        "action": entry.action,
        "subject_type": entry.subject_type,
        "subject_id": entry.subject_id,
        "actor_kind": entry.actor.kind.value,
        "actor_id": entry.actor.id,
        "actor_label": entry.actor.label,
        "reason": entry.reason,
        "before": _plain(entry.before),
        "after": _plain(entry.after),
        "correlation_id": entry.correlation_id,
    }


def entry_from_row(row: Mapping[Any, Any]) -> AuditEntry:
    """The entry an ``audit.event`` row holds, the reverse of ``audit_row`` (identity's audit
    trail reads rows back this way). A time without a zone (SQLite drops it) is UTC."""
    occurred_at: datetime = row["occurred_at"]
    return AuditEntry(
        entry_id=AuditEntryId(row["id"]),
        action=row["action"],
        tenant_id=None if row["tenant_id"] is None else TenantId(row["tenant_id"]),
        subject_type=row["subject_type"],
        subject_id=row["subject_id"],
        actor=AuditActor(AuditActorKind(row["actor_kind"]), row["actor_id"], row["actor_label"]),
        reason=row["reason"],
        before=row["before"],
        after=row["after"],
        occurred_at=occurred_at.replace(tzinfo=UTC)
        if occurred_at.tzinfo is None
        else occurred_at.astimezone(UTC),
        correlation_id=row["correlation_id"],
    )


class AuditWriter:
    """Insert one row per entry on the connection whose transaction holds the action."""

    def write(self, connection: Connection, entry: AuditEntry) -> None:
        connection.execute(insert(audit_event).values(audit_row(entry)))


class PostgresAuditSink:
    """The ``AuditSink`` of a unit of work: ``writer`` on the unit's connection."""

    def __init__(self, connection: Connection, writer: AuditWriter | None = None) -> None:
        self._connection = connection
        self._writer = writer or AuditWriter()

    def write(self, entry: AuditEntry) -> None:
        self._writer.write(self._connection, entry)


def _plain(value: object) -> Any:
    """The entry's read-only JSON as the dicts and lists a JSON column serialises."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_plain(item) for item in value]
    return value
