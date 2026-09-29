"""The work index across tenants: what the dispatcher claims, and where receipts find a tenant.

``work_index`` has no row-level security (the reason is in its comment): the dispatcher sees the
due entries of every tenant, leases a batch with ``FOR UPDATE SKIP LOCKED`` so that two
dispatchers never lease one entry, and handles each in a unit of work of the entry's tenant,
where it completes or reschedules the entry with the notification. An entry whose lease ran out
without either, because its dispatcher died, is due again. A lease lasts
``WORK_LEASE`` (60 seconds) by default.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, Engine, Row, text

from domain_kernel.ids import NotificationId, TenantId
from notification.domain.policy import WORK_LEASE
from notification.domain.repository import WorkEntry, WorkKind

_CLAIM = text(
    """
    UPDATE work_index
       SET lease_until = :lease_until, updated_at = :now
     WHERE id IN (
           SELECT id
             FROM work_index
            WHERE status = 'pending'
              AND available_at <= :now
              AND (lease_until IS NULL OR lease_until <= :now)
            ORDER BY available_at, id
            LIMIT :limit
              FOR UPDATE SKIP LOCKED
     )
    RETURNING id, tenant_id, kind, available_at
    """
)

_TENANT_FOR_MESSAGE = text(
    "SELECT tenant_id FROM work_index WHERE provider_message_id = :provider_message_id LIMIT 1"
)

_TENANTS = text(
    "SELECT tenant_id FROM work_index UNION SELECT tenant_id FROM address_directory "
    "ORDER BY tenant_id"
)


def claim_rows(
    connection: Connection, *, limit: int, now: datetime, lease: timedelta = WORK_LEASE
) -> list[WorkEntry]:
    """Lease due entries on ``connection``, inside the caller's transaction; the lease holds
    for other dispatchers once that transaction commits, and the row locks until then."""
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    rows = connection.execute(
        _CLAIM, {"limit": limit, "now": now, "lease_until": now + lease}
    ).all()
    entries = [_entry(row) for row in rows]
    return sorted(entries, key=lambda entry: (entry.available_at, entry.id.value))


class PostgresWorkIndex:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def claim(
        self, *, limit: int, now: datetime, lease: timedelta = WORK_LEASE
    ) -> Sequence[WorkEntry]:
        with self._engine.begin() as connection:
            return claim_rows(connection, limit=limit, now=now, lease=lease)

    def tenant_for_provider_message(self, provider_message_id: str) -> TenantId | None:
        if not provider_message_id:
            return None
        with self._engine.connect() as connection:
            found = connection.execute(
                _TENANT_FOR_MESSAGE, {"provider_message_id": provider_message_id}
            ).scalar()
        return None if found is None else TenantId(found)

    def tenants(self) -> Sequence[TenantId]:
        with self._engine.connect() as connection:
            values: list[UUID] = list(connection.execute(_TENANTS).scalars())
        return [TenantId(value) for value in values]


def _entry(row: Row[tuple[object, ...]]) -> WorkEntry:
    return WorkEntry(
        id=NotificationId(row.id),
        tenant_id=TenantId(row.tenant_id),
        kind=WorkKind(row.kind),
        available_at=row.available_at.astimezone(UTC),
    )
