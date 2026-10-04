"""Helpers for tests of code that writes audit entries.

- ``audit_entry(**overrides)``: a valid entry with synthetic values.
- ``install_audit_table(connection)``: the table identity's migration creates
  (``create_audit_table``), for the integration tests of a service that do not run identity's
  migrations; the caller's transaction holds it.
- ``read_audit_entries(connection, action=...)``: the rows the connection may read, as entries,
  oldest first; ``entry_from_row`` turns one row back into its entry.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, select

from domain_kernel.access import Role
from domain_kernel.audit import AuditActor, AuditActorKind, AuditEntry, AuditEntryId
from domain_kernel.ids import TenantId, UserId
from py_common.audit.schema import audit_event, create_audit_table

SAMPLE_TENANT = TenantId(UUID("5a3c6a0e-0d7b-4f43-9a4e-2f7f6f2c0a11"))
SAMPLE_USER = UserId(UUID("8d1f4b2a-6c0e-4e5b-a7d3-1b9e2c4f6a08"))
SAMPLE_AT = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


def audit_entry(**overrides: Any) -> AuditEntry:
    """An entry of ``SAMPLE_TENANT`` by an admin, changing a synthetic thing; ``overrides`` win."""
    values: dict[str, Any] = {
        "action": "example.thing.change",
        "tenant_id": SAMPLE_TENANT,
        "subject_type": "thing",
        "subject_id": "thing-1",
        "actor": AuditActor.user(SAMPLE_USER, [Role.ADMIN]),
        "reason": "Synthetic reason for a test",
        "before": {"status": "old"},
        "after": {"status": "new"},
        "occurred_at": SAMPLE_AT,
    }
    values.update(overrides)
    return AuditEntry(**values)


def install_audit_table(connection: Connection) -> None:
    """Create ``audit.event`` as identity's migration does, on ``connection``."""
    create_audit_table(Operations(MigrationContext.configure(connection)))


def entry_from_row(row: Mapping[Any, Any]) -> AuditEntry:
    """The entry an ``audit.event`` row holds. A time without a zone (SQLite drops it) is UTC."""
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


def read_audit_entries(connection: Connection, *, action: str | None = None) -> list[AuditEntry]:
    """The entries ``connection`` may read (row-level security applies), of one action or all,
    oldest first."""
    statement = select(audit_event).order_by(audit_event.c.occurred_at, audit_event.c.id)
    if action is not None:
        statement = statement.where(audit_event.c.action == action)
    return [entry_from_row(row._mapping) for row in connection.execute(statement)]
