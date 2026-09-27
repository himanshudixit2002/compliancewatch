"""obligation table with row-level security, plus the outbox and consumer inbox tables

Revision ID: 0001
Revises:
Create Date: 2026-09-28

Hand-written; mirrors obligation.infrastructure.models. Table names are unqualified and land in
the schema at the front of search_path (CW_DB_SCHEMA, ``obligation``). Row-level security is
enabled and forced on ``obligation``: every statement sees only the rows of the tenant named by
the ``app.tenant_id`` setting, which the unit of work sets per transaction; the table owner is
not exempt, so tests and migrations run under the same rule. The outbox and processed-event
tables come from py-common (ADR-005).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

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

STATUSES = ("open", "in_progress", "done", "waived", "closed_not_applicable")
CLOSURE_REASONS = (
    "profile_changed",
    "rule_withdrawn",
    "rule_superseded",
    "waived_by_user",
    "completed",
)
TENANT_POLICY = "obligation_tenant_isolation"


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        "obligation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("evidence_type", sa.String(length=60), nullable=False),
        sa.Column("period_label", sa.String(length=20), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_reason", sa.String(length=24), nullable=True),
        sa.Column("closed_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_obligation"),
        sa.UniqueConstraint(
            "business_id", "rule_version_id", "period_label", name="uq_obligation_period"
        ),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_obligation_status"),
        sa.CheckConstraint(
            f"closed_reason IS NULL OR {_in_list('closed_reason', CLOSURE_REASONS)}",
            name="ck_obligation_closed_reason",
        ),
        sa.CheckConstraint(
            "(status IN ('done', 'waived', 'closed_not_applicable')) = (closed_at IS NOT NULL)",
            name="ck_obligation_closed",
        ),
        sa.CheckConstraint(
            "(period_label IS NULL) = (period_start IS NULL) AND "
            "(period_label IS NULL) = (period_end IS NULL)",
            name="ck_obligation_period",
        ),
        comment=(
            "Obligations per business and period. Row-level security by tenant_id: the "
            "policy reads the app.tenant_id setting the unit of work sets per transaction."
        ),
    )
    op.create_index(
        "ix_obligation_tenant_status_due", "obligation", ["tenant_id", "status", "due_at"]
    )
    op.create_index("ix_obligation_rule_version", "obligation", ["rule_version_id", "period_label"])
    op.execute("ALTER TABLE obligation ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE obligation FORCE ROW LEVEL SECURITY")
    # NULLIF: once the setting has been used in a session, Postgres reports it as an empty
    # string between transactions, and ''::uuid would fail instead of matching nothing.
    op.execute(
        f"CREATE POLICY {TENANT_POLICY} ON obligation "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    create_outbox_table(op)
    create_processed_event_table(op)


def downgrade() -> None:
    drop_processed_event_table(op)
    drop_outbox_table(op)
    op.execute(f"DROP POLICY {TENANT_POLICY} ON obligation")
    op.drop_index("ix_obligation_rule_version", table_name="obligation")
    op.drop_index("ix_obligation_tenant_status_due", table_name="obligation")
    op.drop_table("obligation")
