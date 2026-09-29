"""notification store: recipients and notifications under row-level security, consents,
suppressions, the address directory and the work index, plus the outbox and consumer inbox

Revision ID: 0001
Revises:
Create Date: 2026-09-29

Hand-written; mirrors notification.infrastructure.models. Table names are unqualified and land in
the schema at the front of search_path (CW_DB_SCHEMA, ``notification``).

Row-level security is enabled and forced on the tenant tables, recipient, recipient_address,
recipient_business and notification, with the tenant policy of
``py_common.migrations.enable_tenant_rls``: every statement sees only the rows of the tenant named
by the ``app.tenant_id`` setting, which the unit of work sets per transaction, and the table owner
is not exempt.

Four tables have no row-level security, each with the reason in its comment (``No row-level
security: ...``) and an exemption in infra/scripts/migration_lint.toml: channel_preference and
suppression, keyed by address before any tenant links it; address_directory, which routes an
address to its tenants; and work_index, which the dispatcher claims across tenants. They hold
addresses, ids and times, never message content.

The outbox and processed-event tables come from py-common (ADR-005).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.migrations import drop_tenant_rls, enable_tenant_rls
from py_common.outbox import (
    create_outbox_table,
    create_processed_event_table,
    drop_outbox_table,
    drop_processed_event_table,
)

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHANNELS = ("whatsapp", "email")
STATES = ("queued", "digest_pending", "sent", "delivered", "read", "failed", "suppressed")
OCCASIONS = ("change_card", "reminder", "closure", "reschedule", "manual")
SOURCES = ("whatsapp_keyword", "web_onboarding", "api", "support")
SUPPRESSION_REASONS = ("bounce", "complaint", "manual")
WORK_KINDS = ("item", "digest_item")
WORK_STATUSES = ("pending", "done")
ROLES = ("owner", "staff", "ca_admin", "ca_staff")
DIGEST_MODES = ("off", "daily")
TENANT_TABLES = ("recipient", "recipient_address", "recipient_business", "notification")

NO_RLS = "No row-level security: "
PREFERENCE_COMMENT = (
    NO_RLS + "consent is per channel and normalised address, recorded before any tenant links the "
    "address (an opt-out typed on WhatsApp must be honoured for every tenant), with the time the "
    "address last wrote to us (the 24-hour WhatsApp window)."
)
SUPPRESSION_COMMENT = (
    NO_RLS + "a closed address (permanent bounce, complaint, or support) holds for every tenant "
    "that sends to it."
)
DIRECTORY_COMMENT = (
    NO_RLS + "routes an address to the tenants and recipients that registered it, for inbound "
    "messages and receipts that name only the address, and lists the tenants a retention sweep "
    "visits. It holds ids and addresses, no message content."
)
WORK_INDEX_COMMENT = (
    NO_RLS + "the dispatcher claims due work across tenants (FOR UPDATE SKIP LOCKED) and then "
    "handles each entry in a unit of work of its tenant; receipts find their tenant by the "
    "provider's message id. It holds ids and times, no message content."
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _created_updated() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "recipient",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("language", sa.String(length=8), server_default="en", nullable=False),
        sa.Column("digest_mode", sa.String(length=8), server_default="off", nullable=False),
        sa.Column("org_label", sa.Text(), server_default="", nullable=False),
        *_created_updated(),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="pk_recipient"),
        sa.CheckConstraint(_in_list("role", ROLES), name="ck_recipient_role"),
        sa.CheckConstraint(_in_list("digest_mode", DIGEST_MODES), name="ck_recipient_digest_mode"),
        comment="Recipients of a tenant's notifications. Row-level security by tenant_id.",
    )
    op.create_index("ix_recipient_tenant_user", "recipient", ["tenant_id", "user_id"])

    op.create_table(
        "recipient_address",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "recipient_id", "channel", "address", name="pk_recipient_address"
        ),
        sa.UniqueConstraint(
            "tenant_id", "recipient_id", "position", name="uq_recipient_address_position"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["recipient.tenant_id", "recipient.id"],
            name="fk_recipient_address_recipient",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(_in_list("channel", CHANNELS), name="ck_recipient_address_channel"),
        sa.CheckConstraint("position >= 0", name="ck_recipient_address_position"),
        comment="Addresses of a recipient in order. Row-level security by tenant_id.",
    )

    op.create_table(
        "recipient_business",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint(
            "tenant_id", "recipient_id", "business_id", name="pk_recipient_business"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["recipient.tenant_id", "recipient.id"],
            name="fk_recipient_business_recipient",
            ondelete="CASCADE",
        ),
        comment="The businesses each recipient hears about. Row-level security by tenant_id.",
    )
    op.create_index(
        "ix_recipient_business_business", "recipient_business", ["tenant_id", "business_id"]
    )

    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("occasion", sa.String(length=16), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_id", sa.Uuid(), nullable=True),
        sa.Column("provider_message_id", sa.Text(), server_default="", nullable=False),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.Column("fallback_of", sa.Uuid(), nullable=True),
        *_created_updated(),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_notification"),
        sa.UniqueConstraint("dedupe_key", name="uq_notification_dedupe_key"),
        sa.ForeignKeyConstraint(
            ["fallback_of"],
            ["notification.id"],
            name="fk_notification_fallback_of_notification",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(_in_list("channel", CHANNELS), name="ck_notification_channel"),
        sa.CheckConstraint(_in_list("occasion", OCCASIONS), name="ck_notification_occasion"),
        sa.CheckConstraint(_in_list("state", STATES), name="ck_notification_state"),
        sa.CheckConstraint("attempts >= 0", name="ck_notification_attempts"),
        sa.CheckConstraint(
            "state NOT IN ('sent', 'delivered', 'read') OR sent_at IS NOT NULL",
            name="ck_notification_sent_at",
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR failed_at IS NOT NULL", name="ck_notification_failed_at"
        ),
        comment=(
            "Notifications, one per occasion, recipient and channel (unique dedupe_key). "
            "Row-level security by tenant_id."
        ),
    )
    op.create_index("ix_notification_state_available", "notification", ["state", "available_at"])
    op.create_index("ix_notification_provider_message", "notification", ["provider_message_id"])
    op.create_index(
        "ix_notification_business_created",
        "notification",
        ["tenant_id", "business_id", "created_at"],
    )
    op.create_index(
        "ix_notification_recipient_due",
        "notification",
        ["recipient_id", "channel", "state", "available_at"],
    )
    op.create_index("ix_notification_dispatch", "notification", ["dispatch_id"])
    op.create_index("ix_notification_obligation", "notification", ["obligation_id", "created_at"])

    for table in TENANT_TABLES:
        enable_tenant_rls(op, table)

    op.create_table(
        "channel_preference",
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("opted_in", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=True),
        sa.Column("language", sa.String(length=8), server_default="en", nullable=False),
        sa.Column(
            "quiet_hours_start", sa.Time(), server_default=sa.text("'21:00'"), nullable=False
        ),
        sa.Column("quiet_hours_end", sa.Time(), server_default=sa.text("'08:00'"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("channel", "address", name="pk_channel_preference"),
        sa.CheckConstraint(_in_list("channel", CHANNELS), name="ck_channel_preference_channel"),
        sa.CheckConstraint(
            f"source IS NULL OR {_in_list('source', SOURCES)}",
            name="ck_channel_preference_source",
        ),
        sa.CheckConstraint(
            "(opted_in IS NULL) = (source IS NULL) AND (opted_in IS NULL) = (updated_at IS NULL)",
            name="ck_channel_preference_consent",
        ),
        sa.CheckConstraint(
            "opted_in IS NOT NULL OR last_inbound_at IS NOT NULL",
            name="ck_channel_preference_not_empty",
        ),
        comment=PREFERENCE_COMMENT,
    )

    op.create_table(
        "suppression",
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("channel", "address", name="pk_suppression"),
        sa.CheckConstraint(_in_list("channel", CHANNELS), name="ck_suppression_channel"),
        sa.CheckConstraint(_in_list("reason", SUPPRESSION_REASONS), name="ck_suppression_reason"),
        comment=SUPPRESSION_COMMENT,
    )

    op.create_table(
        "address_directory",
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint(
            "channel", "address", "tenant_id", "recipient_id", name="pk_address_directory"
        ),
        sa.CheckConstraint(_in_list("channel", CHANNELS), name="ck_address_directory_channel"),
        comment=DIRECTORY_COMMENT,
    )
    op.create_index(
        "ix_address_directory_recipient", "address_directory", ["tenant_id", "recipient_id"]
    )

    op.create_table(
        "work_index",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="pending", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.Text(), server_default="", nullable=False),
        *_created_updated(),
        sa.PrimaryKeyConstraint("id", name="pk_work_index"),
        sa.ForeignKeyConstraint(
            ["id"], ["notification.id"], name="fk_work_index_id_notification", ondelete="CASCADE"
        ),
        sa.CheckConstraint(_in_list("kind", WORK_KINDS), name="ck_work_index_kind"),
        sa.CheckConstraint(_in_list("status", WORK_STATUSES), name="ck_work_index_status"),
        comment=WORK_INDEX_COMMENT,
    )
    op.create_index(
        "ix_work_index_due",
        "work_index",
        ["available_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_work_index_provider_message",
        "work_index",
        ["provider_message_id"],
        postgresql_where=sa.text("provider_message_id <> ''"),
    )
    op.create_index("ix_work_index_tenant", "work_index", ["tenant_id"])

    create_outbox_table(op)
    create_processed_event_table(op)


def downgrade() -> None:
    drop_processed_event_table(op)
    drop_outbox_table(op)
    op.drop_index("ix_work_index_tenant", table_name="work_index")
    op.drop_index("ix_work_index_provider_message", table_name="work_index")
    op.drop_index("ix_work_index_due", table_name="work_index")
    op.drop_table("work_index")
    op.drop_index("ix_address_directory_recipient", table_name="address_directory")
    op.drop_table("address_directory")
    op.drop_table("suppression")
    op.drop_table("channel_preference")
    for table in reversed(TENANT_TABLES):
        drop_tenant_rls(op, table)
    for index in (
        "ix_notification_obligation",
        "ix_notification_dispatch",
        "ix_notification_recipient_due",
        "ix_notification_business_created",
        "ix_notification_provider_message",
        "ix_notification_state_available",
    ):
        op.drop_index(index, table_name="notification")
    op.drop_table("notification")
    op.drop_index("ix_recipient_business_business", table_name="recipient_business")
    op.drop_table("recipient_business")
    op.drop_table("recipient_address")
    op.drop_index("ix_recipient_tenant_user", table_name="recipient")
    op.drop_table("recipient")
