"""The audit trail read from ``audit.event`` on Postgres.

Each read is one transaction that names its scope to row-level security first:
``app.tenant_id`` for a tenant's rows, ``app.audit_scope = 'regulatory'`` (with the reader's own
tenant) for the platform's rows, ``app.audit_scope = 'export'`` for every row (identity migration
0006). The query states the same scope again, so a role that bypasses row-level security (the
dev stack's superuser) reads no more than the scope admits. Pages run on the keyset
(occurred_at, id), newest first, through the index on (tenant_id, occurred_at) for a tenant's
trail; the export streams oldest first.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Any, Final

from sqlalchemy import Connection, Engine, Select, false, or_, select, text, tuple_

from domain_kernel.audit import AuditEntry
from domain_kernel.ids import TenantId
from identity.domain.audit import AuditQuery, AuditScope
from identity.infrastructure.models import TENANT_SETTING
from py_common.audit.schema import (
    AUDIT_SCOPE_SETTING,
    EXPORT_SCOPE,
    REGULATORY_SCOPE,
    audit_event,
)
from py_common.audit.writer import entry_from_row

EXPORT_BATCH: Final = 1_000
"""Rows the export fetches per round trip."""
_SCOPE_SETTINGS: Final = {
    AuditScope.REGULATORY: REGULATORY_SCOPE,
    AuditScope.EXPORT: EXPORT_SCOPE,
}


class PostgresAuditReader:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def page(
        self, scope: AuditScope, tenant_id: TenantId | None, query: AuditQuery
    ) -> list[AuditEntry]:
        statement = _scoped(select(audit_event), scope, tenant_id)
        column = audit_event.c
        if query.subject_type is not None:
            statement = statement.where(column.subject_type == query.subject_type)
        if query.subject_id is not None:
            statement = statement.where(column.subject_id == query.subject_id)
        if query.action is not None:
            statement = statement.where(column.action == query.action)
        if query.since is not None:
            statement = statement.where(column.occurred_at >= query.since)
        if query.until is not None:
            statement = statement.where(column.occurred_at < query.until)
        if query.after is not None:
            statement = statement.where(
                tuple_(column.occurred_at, column.id)
                < tuple_(query.after.occurred_at, query.after.entry_id.value)
            )
        statement = statement.order_by(column.occurred_at.desc(), column.id.desc()).limit(
            query.limit + 1
        )
        with self._engine.connect() as connection, connection.begin():
            _name_scope(connection, scope, tenant_id)
            return [entry_from_row(row._mapping) for row in connection.execute(statement)]

    def export(self, since: datetime, until: datetime) -> Iterator[AuditEntry]:
        column = audit_event.c
        statement = (
            select(audit_event)
            .where(column.occurred_at >= since, column.occurred_at < until)
            .order_by(column.occurred_at, column.id)
        )
        with self._engine.connect() as connection, connection.begin():
            _name_scope(connection, AuditScope.EXPORT, None)
            rows = connection.execution_options(
                stream_results=True, yield_per=EXPORT_BATCH
            ).execute(statement)
            for row in rows:
                yield entry_from_row(row._mapping)


def _scoped(statement: Select[Any], scope: AuditScope, tenant_id: TenantId | None) -> Select[Any]:
    """``statement`` limited to the rows ``scope`` admits in ``tenant_id``, as the policies are."""
    column = audit_event.c.tenant_id
    if scope is AuditScope.EXPORT:
        return statement
    own = column == tenant_id.value if tenant_id is not None else false()
    if scope is AuditScope.REGULATORY:
        return statement.where(or_(column.is_(None), own))
    return statement.where(own)


def _name_scope(connection: Connection, scope: AuditScope, tenant_id: TenantId | None) -> None:
    """Name the scope to row-level security for this transaction (``set_config(..., true)`` is
    SET LOCAL with the values as bind parameters)."""
    if tenant_id is not None and scope is not AuditScope.EXPORT:
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant_id)},
        )
    setting = _SCOPE_SETTINGS.get(scope)
    if setting is not None:
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": AUDIT_SCOPE_SETTING, "value": setting},
        )
