"""The two outbox tables and the alembic helpers that create them in a service's schema.

Table names are unqualified: the service's ``search_path`` (set by ``make migrate`` and
``make run``) places them in its own schema, next to its other tables. A service that produces
events calls ``create_outbox_table(op)`` from a migration; one that consumes them calls
``create_processed_event_table(op)``. Both are idempotent to downgrade with the ``drop_*`` twins.
"""

from collections.abc import Sequence

from alembic.operations import Operations
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.schema import SchemaItem
from sqlalchemy.types import JSON

OUTBOX_TABLE = "outbox_event"
PROCESSED_TABLE = "processed_event"
STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_DEAD = "dead"
STATUSES = (STATUS_PENDING, STATUS_PUBLISHED, STATUS_DEAD)
PENDING_INDEX = "ix_outbox_event_pending"
PUBLISHED_INDEX = "ix_outbox_event_published_at"
OUTBOX_COMMENT = (
    "Transactional outbox: one row per domain event, written in the producer's transaction and "
    "published to Kafka by the relay. Rows stay after publication for auditing until pruned."
)
PROCESSED_COMMENT = (
    "Consumer inbox: the event ids one consumer group has already handled, so a redelivered "
    "message is skipped."
)

metadata = MetaData()


def _outbox_columns() -> list[SchemaItem]:
    return [
        Column("id", Uuid(), primary_key=True, comment="The event id"),
        Column("topic", String(120), nullable=False),
        Column("schema_version", String(20), nullable=False),
        Column("partition_key", String(120), nullable=False, comment="Kafka message key"),
        Column("tenant_id", Uuid(), nullable=True),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
        Column(
            "message",
            JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            comment="The full wire message: envelope and payload",
        ),
        Column("status", String(12), nullable=False, server_default=STATUS_PENDING),
        Column("attempts", Integer(), nullable=False, server_default="0"),
        Column("available_at", DateTime(timezone=True), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column("published_at", DateTime(timezone=True), nullable=True),
        Column("last_error", Text(), nullable=False, server_default=""),
        CheckConstraint(
            "status in ('pending', 'published', 'dead')", name="ck_outbox_event_status"
        ),
    ]


def _processed_columns() -> list[SchemaItem]:
    return [
        Column("consumer_group", String(120), primary_key=True),
        Column("event_id", Uuid(), primary_key=True),
        Column("topic", String(120), nullable=False),
        Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    ]


outbox_event = Table(OUTBOX_TABLE, metadata, *_outbox_columns(), comment=OUTBOX_COMMENT)
Index(
    PENDING_INDEX,
    outbox_event.c.available_at,
    postgresql_where=text("status = 'pending'"),
)
Index(PUBLISHED_INDEX, outbox_event.c.published_at)

processed_event = Table(PROCESSED_TABLE, metadata, *_processed_columns(), comment=PROCESSED_COMMENT)


def create_outbox_table(op: Operations) -> None:
    """Create ``outbox_event`` and its indexes. Call from a service migration's ``upgrade``."""
    op.create_table(OUTBOX_TABLE, *_outbox_columns(), comment=OUTBOX_COMMENT)
    op.create_index(
        PENDING_INDEX, OUTBOX_TABLE, ["available_at"], postgresql_where=text("status = 'pending'")
    )
    op.create_index(PUBLISHED_INDEX, OUTBOX_TABLE, ["published_at"])


def drop_outbox_table(op: Operations) -> None:
    op.drop_index(PUBLISHED_INDEX, table_name=OUTBOX_TABLE)
    op.drop_index(PENDING_INDEX, table_name=OUTBOX_TABLE)
    op.drop_table(OUTBOX_TABLE)


def create_processed_event_table(op: Operations) -> None:
    """Create ``processed_event``. Call from a consuming service's migration."""
    op.create_table(PROCESSED_TABLE, *_processed_columns(), comment=PROCESSED_COMMENT)


def drop_processed_event_table(op: Operations) -> None:
    op.drop_table(PROCESSED_TABLE)


def table_names() -> Sequence[str]:
    return (OUTBOX_TABLE, PROCESSED_TABLE)
