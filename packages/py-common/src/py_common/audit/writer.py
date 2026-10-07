"""Write an audit entry inside the caller's transaction.

``AuditWriter.write(connection, entry)`` inserts one ``audit.event`` row on the connection whose
transaction holds the action, as ``OutboxWriter`` does for events, so the row commits or rolls
back with the action. ``PostgresAuditSink`` is the kernel's ``AuditSink`` on one connection: what
a unit of work exposes as ``audit``. Row-level security admits a row of the tenant the
transaction's ``app.tenant_id`` names, or a row of no tenant; any other row fails the statement,
and with it the transaction.

The row is masked for personal identifiers before it is written (``domain_kernel.pii``, the
patterns the log lines are masked with): GSTINs, PANs, Aadhaar numbers, phone numbers and email
addresses in the reason, and in every text of ``before`` and ``after`` at any depth, become
``[GSTIN]``, ``[PAN]``, ``[AADHAAR]``, ``[PHONE]`` and ``[EMAIL]``. The value of a key ending in
``_id`` or ``_ids`` is left alone, as on a log line, since a twelve-digit piece of an id would
read as an Aadhaar number. The action, the subject and its id, the actor and the correlation id
are never masked: they say who did what to which record. The memory twin (``MemoryAuditSink``)
keeps the entry as the use case built it.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, insert

from domain_kernel.audit import AuditEntry
from domain_kernel.pii import mask_pii, mask_pii_in
from py_common.audit.schema import audit_event


def audit_row(entry: AuditEntry) -> dict[str, Any]:
    """The column values of ``entry``'s row: the reason, ``before`` and ``after`` masked for
    personal identifiers, and ``before`` and ``after`` as plain JSON."""
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
        "reason": mask_pii(entry.reason).text,
        "before": _plain(mask_pii_in(entry.before)),
        "after": _plain(mask_pii_in(entry.after)),
        "correlation_id": entry.correlation_id,
    }


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
