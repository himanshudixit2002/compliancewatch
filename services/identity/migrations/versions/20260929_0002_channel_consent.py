"""channel_consent: keyword opt-ins and opt-outs keyed by phone number, append-only

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

Hand-written; mirrors identity.infrastructure.models. A person who writes START or STOP to the
WhatsApp number has no account and no tenant owns the number yet, so the table has no tenant_id
and no row-level security (infra/scripts/migration_lint.toml exempts it). Only the service-token
routes of identity read or write it.

Expand-only: a new table, which nothing reads before this release. Each row is one message's
evidence, so a trigger refuses UPDATE and DELETE (py_common.migrations.create_append_only_guard).
The partial unique index on (channel, message_id) makes a redelivered webhook find the first
row; rows without a message id are not constrained.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from py_common.migrations import create_append_only_guard, drop_append_only_guard

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "channel_consent"
CHANNELS = ("whatsapp",)
PURPOSES = ("whatsapp_reminders",)
SOURCES = ("whatsapp_keyword",)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("notice_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("message_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_channel_consent"),
        sa.CheckConstraint(_in_list("channel", CHANNELS), name="ck_channel_consent_channel"),
        sa.CheckConstraint("subject ~ '^[1-9][0-9]{7,14}$'", name="ck_channel_consent_subject"),
        sa.CheckConstraint(_in_list("purpose", PURPOSES), name="ck_channel_consent_purpose"),
        sa.CheckConstraint(_in_list("source", SOURCES), name="ck_channel_consent_source"),
        sa.CheckConstraint(
            "NOT granted OR notice_version <> ''", name="ck_channel_consent_notice_version"
        ),
        comment=(
            "Append-only consents typed on a channel, keyed by phone number before any tenant "
            "owns it; no tenant_id"
        ),
    )
    op.create_index(
        "ux_channel_consent_message",
        TABLE,
        ["channel", "message_id"],
        unique=True,
        postgresql_where=sa.text("message_id <> ''"),
    )
    op.create_index("ix_channel_consent_subject", TABLE, ["channel", "subject", "recorded_at"])
    create_append_only_guard(op, TABLE)


def downgrade() -> None:
    drop_append_only_guard(op, TABLE)
    op.drop_index("ix_channel_consent_subject", table_name=TABLE)
    op.drop_index("ux_channel_consent_message", table_name=TABLE)
    op.drop_table(TABLE)
