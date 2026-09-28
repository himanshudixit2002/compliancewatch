"""consent records with row-level security by tenant

Revision ID: 0001
Revises:
Create Date: 2026-09-28

Hand-written; mirrors identity.infrastructure.models. Append-only: the application never
updates or deletes a row; a withdrawal is a new row. The policy reads the app.tenant_id
setting (NULLIF against '' because a used custom setting reads as an empty string between
transactions).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES = (
    "terms",
    "privacy_notice",
    "profile_processing",
    "whatsapp_reminders",
    "email_reminders",
    "analytics",
)
SOURCES = ("web_onboarding", "whatsapp_keyword", "api", "support")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        "consent_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=254), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("notice_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_consent_record"),
        sa.CheckConstraint(_in_list("purpose", PURPOSES), name="ck_consent_record_purpose"),
        sa.CheckConstraint(_in_list("source", SOURCES), name="ck_consent_record_source"),
        sa.CheckConstraint(
            "NOT granted OR notice_version <> ''", name="ck_consent_record_notice_version"
        ),
        comment="Append-only consent records; row-level security by tenant_id",
    )
    op.create_index(
        "ix_consent_record_subject", "consent_record", ["tenant_id", "subject", "recorded_at"]
    )
    op.execute("ALTER TABLE consent_record ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE consent_record FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY consent_record_tenant_isolation ON consent_record "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS consent_record_tenant_isolation ON consent_record")
    op.drop_index("ix_consent_record_subject", table_name="consent_record")
    op.drop_table("consent_record")
