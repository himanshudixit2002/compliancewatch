"""What the check reads that no route serves yet: the business directory and the audit log.

The fan-out step compares a run's counters with the directory entries of the version's level, and
looks for the audit rows of the hold, the release and any resume, which are rows of no tenant.
No policy lets the product's role (``cw_app``) read those rows, and no route serves them yet, so
``PostgresRecords`` reads them on a session of its own, as the dev stack's database owner, read
only (``default_transaction_read_only``): it can run nothing but queries. ``make product-check``
passes the URL as ``CW_PRODUCT_RECORDS_URL``; the step fails without it rather than skip.

``ProductRecords`` is what the step needs; a test of the step against the memory stores
implements it over the engine's memory store.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from sqlalchemy import Engine, bindparam, create_engine, text
from sqlalchemy.pool import NullPool

READ_ONLY: Final = "-c default_transaction_read_only=on"


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One ``audit.event`` row, as the check reports it."""

    action: str
    subject_type: str
    subject_id: str
    actor_label: str
    reason: str
    occurred_at: datetime
    tenant_id: UUID | None


class ProductRecords(Protocol):
    def directory_count(self, level: str, *, as_of: datetime | None = None) -> int:
        """Directory entries of ``level``, those listed by ``as_of`` when given."""
        ...

    def listed(self, business_ids: Iterable[str], *, as_of: datetime | None = None) -> set[str]:
        """Which of ``business_ids`` the directory lists (by ``as_of`` when given)."""
        ...

    def audit_entries(self, *, actions: Sequence[str], since: datetime) -> list[AuditRecord]:
        """The audit rows of ``actions`` since ``since``, oldest first."""
        ...


class PostgresRecords:
    """``ProductRecords`` on a read-only session at ``url``."""

    def __init__(self, url: str) -> None:
        self._engine: Engine = create_engine(
            url, poolclass=NullPool, connect_args={"options": READ_ONLY}
        )

    def directory_count(self, level: str, *, as_of: datetime | None = None) -> int:
        sql = "SELECT count(*) FROM applicability.business_directory WHERE level = :level"
        values: dict[str, object] = {"level": level}
        if as_of is not None:
            sql += " AND created_at <= :as_of"
            values["as_of"] = as_of
        with self._engine.connect() as connection:
            return int(connection.execute(text(sql), values).scalar_one())

    def listed(self, business_ids: Iterable[str], *, as_of: datetime | None = None) -> set[str]:
        ids = [UUID(business_id) for business_id in business_ids]
        if not ids:
            return set()
        sql = "SELECT business_id FROM applicability.business_directory WHERE business_id IN :ids"
        values: dict[str, object] = {"ids": ids}
        if as_of is not None:
            sql += " AND created_at <= :as_of"
            values["as_of"] = as_of
        statement = text(sql).bindparams(bindparam("ids", expanding=True))
        with self._engine.connect() as connection:
            return {str(row[0]) for row in connection.execute(statement, values)}

    def audit_entries(self, *, actions: Sequence[str], since: datetime) -> list[AuditRecord]:
        statement = text(
            "SELECT action, subject_type, subject_id, actor_label, reason, occurred_at, tenant_id "
            "FROM audit.event WHERE action IN :actions AND occurred_at >= :since "
            "ORDER BY occurred_at, id"
        ).bindparams(bindparam("actions", expanding=True))
        with self._engine.connect() as connection:
            rows = connection.execute(statement, {"actions": list(actions), "since": since})
            return [AuditRecord(*row) for row in rows]

    def close(self) -> None:
        self._engine.dispose()
