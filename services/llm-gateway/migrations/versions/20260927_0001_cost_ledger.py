"""cost_ledger: one row per LLM call; the usage-metering source for budgets.

Revision ID: 0001
Revises:
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_COMMENT = (
    "Usage metering for every LLM call. Row-level security is deliberately not applied: the cost "
    "dashboard reads this table across tenants and tenant_id is NULL for regulatory calls. The "
    "tenant RLS convention lands with the first customer-data table."
)


def upgrade() -> None:
    op.create_table(
        "cost_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("feature", sa.String(32), nullable=False),
        sa.Column("prompt_name", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("model_requested", sa.String(120), nullable=False),
        sa.Column("model_served", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("cost_inr", sa.Numeric(14, 4), nullable=False),
        sa.Column("cost_source", sa.String(16), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("generation_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("error_type", sa.String(80), nullable=False, server_default=""),
        comment=TABLE_COMMENT,
    )
    op.create_index("ix_cost_ledger_tenant_month", "cost_ledger", ["tenant_id", "occurred_at"])
    op.create_index("ix_cost_ledger_feature_month", "cost_ledger", ["feature", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_cost_ledger_feature_month", table_name="cost_ledger")
    op.drop_index("ix_cost_ledger_tenant_month", table_name="cost_ledger")
    op.drop_table("cost_ledger")
