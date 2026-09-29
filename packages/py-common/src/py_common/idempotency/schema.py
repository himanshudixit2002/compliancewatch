"""The ``idempotency_key`` table and the alembic helpers that create it in a service's schema.

A service whose routes take an ``Idempotency-Key`` calls ``create_idempotency_table(op)`` from
one of its migrations and ``drop_idempotency_table(op)`` from the downgrade, as it does for the
outbox. The table name is unqualified: the migration's ``search_path`` puts it in the service's
schema.

The table holds tenant data (the responses), so row-level security is enabled and forced with
the tenant policy of ``py_common.migrations.enable_tenant_rls``. One more permissive policy,
``idempotency_key_purge_expired``, admits DELETE of expired rows and nothing else: the daily
purge runs with no tenant set and could not remove anything under the tenant policy alone. It
lets no one read a row or write one. The migration lint accepts exactly this policy next to the
tenant policy (infra/scripts/check_migrations.py).
"""

from alembic.operations import Operations
from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.schema import SchemaItem
from sqlalchemy.types import JSON

from py_common.idempotency.store import MAX_KEY_LENGTH
from py_common.migrations import enable_tenant_rls

IDEMPOTENCY_TABLE = "idempotency_key"
EXPIRES_INDEX = "ix_idempotency_key_expires_at"
PURGE_POLICY = "idempotency_key_purge_expired"
EXPIRED = "expires_at < now()"
"""The USING of the purge policy: the rows whose replay window or lease has passed."""
IDEMPOTENCY_COMMENT = (
    "Idempotency keys per tenant: the fingerprint of the first request with a key and, once it "
    "finished, its response, replayed to retries for 24 hours. The daily purge deletes expired "
    "rows."
)

metadata = MetaData()


def _columns() -> list[SchemaItem]:
    return [
        Column("tenant_id", Uuid(), primary_key=True),
        Column("key", String(MAX_KEY_LENGTH), primary_key=True, comment="The Idempotency-Key"),
        Column("method", String(10), nullable=False),
        Column("path", Text(), nullable=False),
        Column(
            "fingerprint",
            CHAR(64),
            nullable=False,
            comment="SHA-256 of the method, path and body of the first request",
        ),
        Column(
            "status_code",
            SmallInteger(),
            nullable=True,
            comment="Null while the first request runs",
        ),
        Column("response", JSON().with_variant(JSONB(), "postgresql"), nullable=True),
        Column("response_headers", JSON().with_variant(JSONB(), "postgresql"), nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column(
            "expires_at",
            DateTime(timezone=True),
            nullable=False,
            comment="End of the lease while running, then end of the replay window",
        ),
        CheckConstraint(
            "status_code IS NULL OR status_code BETWEEN 200 AND 499",
            name="ck_idempotency_key_status_code",
        ),
    ]


idempotency_key = Table(IDEMPOTENCY_TABLE, metadata, *_columns(), comment=IDEMPOTENCY_COMMENT)
Index(EXPIRES_INDEX, idempotency_key.c.expires_at)


def create_idempotency_table(op: Operations) -> None:
    """Create ``idempotency_key`` with its index, the forced tenant policy and the purge policy.
    Call from a service migration's ``upgrade``."""
    op.create_table(IDEMPOTENCY_TABLE, *_columns(), comment=IDEMPOTENCY_COMMENT)
    op.create_index(EXPIRES_INDEX, IDEMPOTENCY_TABLE, ["expires_at"])
    enable_tenant_rls(op, IDEMPOTENCY_TABLE)
    op.execute(f"CREATE POLICY {PURGE_POLICY} ON {IDEMPOTENCY_TABLE} FOR DELETE USING ({EXPIRED})")


def drop_idempotency_table(op: Operations) -> None:
    """Reverse ``create_idempotency_table``; the policies go with the table."""
    op.drop_index(EXPIRES_INDEX, table_name=IDEMPOTENCY_TABLE)
    op.drop_table(IDEMPOTENCY_TABLE)
