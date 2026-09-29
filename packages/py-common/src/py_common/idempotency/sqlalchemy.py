"""Idempotency keys in Postgres, in the ``idempotency_key`` table of the service's schema.

``SqlAlchemyIdempotencyStore(engine)`` runs every call in its own short transaction, which first
sets ``app.tenant_id`` with ``set_config`` for the tenant policy. ``begin`` claims a key with
``INSERT ... ON CONFLICT DO NOTHING``: the committed row is the in-flight lock, so a concurrent
request with the same key finds it and gets ``InFlight``. Only one of two concurrent inserts can
win the primary key, so exactly one request starts. A key whose lease or replay window has
passed is claimed again by an UPDATE that only matches while it is still expired.

``SqlAlchemyIdempotencyRecorder(connection)`` (``store.recorder(connection)``) runs the same
statements on the caller's connection, inside the transaction of the business write, whose unit
of work has already set ``app.tenant_id``. The key row then commits or rolls back with that
write. A concurrent request with the same key waits on the primary key until the first
transaction ends, then replays its response, or claims the key when it rolled back.

``purge_expired`` deletes the expired rows of every tenant. With row-level security in force
for the connection's role it runs a DELETE without a WHERE clause: the purge policy admits only
expired rows, and a WHERE clause naming a column would also need the tenant policy's read
access, which admits nothing without a tenant. A role that bypasses row-level security (a
superuser, as in local development) gets ``WHERE expires_at < now()`` instead, so no role can
purge a live key.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from domain_kernel.ids import TenantId
from py_common.idempotency.schema import IDEMPOTENCY_TABLE, idempotency_key
from py_common.idempotency.store import (
    IN_FLIGHT_LEASE,
    REPLAY_WINDOW,
    IdempotencyRequest,
    InFlight,
    Outcome,
    Replay,
    Reused,
    Started,
    StoredResponse,
)
from py_common.logging import get_logger
from py_common.migrations import TENANT_SETTING

log = get_logger(__name__)
_CLAIM_ATTEMPTS = 3
table = idempotency_key.c


class SqlAlchemyIdempotencyRecorder:
    """The key statements on the caller's connection, inside its transaction.

    The caller's unit of work sets ``app.tenant_id`` for ``tenant`` before this runs; the tenant
    policy refuses the key row otherwise. Nothing here commits or rolls back.
    """

    def __init__(
        self,
        connection: Connection,
        *,
        lease: timedelta = IN_FLIGHT_LEASE,
        window: timedelta = REPLAY_WINDOW,
    ) -> None:
        self._connection = connection
        self._lease = lease
        self._window = window

    def begin(self, tenant: TenantId, request: IdempotencyRequest) -> Outcome:
        for _ in range(_CLAIM_ATTEMPTS):
            if self._claim(tenant, request):
                return Started()
            row = self._connection.execute(
                select(
                    table.fingerprint,
                    table.status_code,
                    table.response,
                    table.response_headers,
                    (table.expires_at <= func.now()).label("expired"),
                ).where(table.tenant_id == tenant.value, table.key == request.key)
            ).first()
            if row is None:
                continue  # abandoned or purged since the insert: claim it again
            if row.expired:
                if self._take_over(tenant, request):
                    return Started()
                continue
            if row.fingerprint != request.fingerprint:
                return Reused()
            if row.status_code is None:
                return InFlight()
            return Replay(StoredResponse(row.status_code, row.response, row.response_headers or {}))
        # The key changed hands on every attempt; the client retries after the 409.
        return InFlight()

    def complete(
        self, tenant: TenantId, request: IdempotencyRequest, response: StoredResponse
    ) -> None:
        recorded = self._connection.execute(
            update(idempotency_key)
            .where(*_claimed_by(tenant, request))
            .values(
                status_code=response.status_code,
                response=response.body,
                response_headers=dict(response.headers),
                expires_at=func.now() + self._window,
            )
        )
        if recorded.rowcount == 0:
            log.warning(
                "idempotency.response_not_recorded",
                path=request.path,
                reason="the key's lease ran out and another request claimed it",
            )

    def abandon(self, tenant: TenantId, request: IdempotencyRequest) -> None:
        self._connection.execute(delete(idempotency_key).where(*_claimed_by(tenant, request)))

    def _claim(self, tenant: TenantId, request: IdempotencyRequest) -> bool:
        claimed = self._connection.execute(
            insert(idempotency_key)
            .values(
                tenant_id=tenant.value,
                key=request.key,
                method=request.method,
                path=request.path,
                fingerprint=request.fingerprint,
                expires_at=func.now() + self._lease,
            )
            .on_conflict_do_nothing(index_elements=[table.tenant_id, table.key])
            .returning(table.key)
        ).first()
        return claimed is not None

    def _take_over(self, tenant: TenantId, request: IdempotencyRequest) -> bool:
        taken = self._connection.execute(
            update(idempotency_key)
            .where(
                table.tenant_id == tenant.value,
                table.key == request.key,
                table.expires_at <= func.now(),
            )
            .values(
                method=request.method,
                path=request.path,
                fingerprint=request.fingerprint,
                status_code=None,
                response=None,
                response_headers=None,
                created_at=func.now(),
                expires_at=func.now() + self._lease,
            )
            .returning(table.key)
        ).first()
        return taken is not None


class SqlAlchemyIdempotencyStore:
    """An ``IdempotencyStore`` on ``engine``, each call in its own short transaction."""

    def __init__(
        self,
        engine: Engine,
        *,
        lease: timedelta = IN_FLIGHT_LEASE,
        window: timedelta = REPLAY_WINDOW,
    ) -> None:
        self._engine = engine
        self._lease = lease
        self._window = window

    def recorder(self, connection: Connection) -> SqlAlchemyIdempotencyRecorder:
        """A recorder inside the caller's transaction on ``connection``, with this store's
        lease and replay window."""
        return SqlAlchemyIdempotencyRecorder(connection, lease=self._lease, window=self._window)

    def begin(self, tenant: TenantId, request: IdempotencyRequest) -> Outcome:
        with self._engine.begin() as connection:
            return self._as_tenant(connection, tenant).begin(tenant, request)

    def complete(
        self, tenant: TenantId, request: IdempotencyRequest, response: StoredResponse
    ) -> None:
        with self._engine.begin() as connection:
            self._as_tenant(connection, tenant).complete(tenant, request, response)

    def abandon(self, tenant: TenantId, request: IdempotencyRequest) -> None:
        with self._engine.begin() as connection:
            self._as_tenant(connection, tenant).abandon(tenant, request)

    def purge_expired(self) -> int:
        with self._engine.begin() as connection:
            policed: Any = connection.execute(
                text("SELECT row_security_active(:table)"), {"table": IDEMPOTENCY_TABLE}
            ).scalar()
            statement = delete(idempotency_key)
            if not policed:
                statement = statement.where(table.expires_at < func.now())
            purged = connection.execute(statement).rowcount
        log.info("idempotency.purged", rows=purged, row_security=bool(policed))
        return purged

    def _as_tenant(self, connection: Connection, tenant: TenantId) -> SqlAlchemyIdempotencyRecorder:
        connection.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": TENANT_SETTING, "value": str(tenant)},
        )
        return self.recorder(connection)


def _claimed_by(tenant: TenantId, request: IdempotencyRequest) -> tuple[Any, ...]:
    """The row ``request`` claimed and has not recorded yet; not one another request took over
    after the lease ran out."""
    return (
        table.tenant_id == tenant.value,
        table.key == request.key,
        table.fingerprint == request.fingerprint,
        table.status_code.is_(None),
    )
