"""the order of billing webhooks, the past-due grace and the subscription starts

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07

Hand-written; mirrors identity.infrastructure.models. Expand-only: two nullable columns and a new
table that nothing reads before this release.

- billing_subscription.last_event_at: when the newest webhook applied to the subscription
  happened, so an older one that arrives later is ignored. Null until a webhook applies.
- billing_subscription.past_due_since: when the subscription turned past due; the plan is kept
  for the grace period after it (CW_PLAN_PAST_DUE_GRACE_DAYS). Null while it is not past due.
- billing_start: one row per tenant and Idempotency-Key of POST
  /v1/identity/billing/subscriptions, written before the billing provider is called, with the
  provider's subscription id once it answered. A key found here is never sent to the provider
  again. Under forced row-level security with the tenant policy; no personal data.

The downgrade drops the table and the columns with what they hold.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from py_common.migrations import drop_tenant_rls, enable_tenant_rls

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_subscription",
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "billing_subscription",
        sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "billing_start",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("plan_key", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=64), nullable=True),
        sa.Column("checkout_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "idempotency_key", name="pk_billing_start"),
        sa.CheckConstraint("quantity >= 1", name="ck_billing_start_quantity"),
        comment=(
            "Subscription starts by Idempotency-Key, recorded before the provider is called; "
            "row-level security by tenant_id"
        ),
    )
    enable_tenant_rls(op, "billing_start")


def downgrade() -> None:
    drop_tenant_rls(op, "billing_start")
    op.drop_table("billing_start")
    op.drop_column("billing_subscription", "past_due_since")
    op.drop_column("billing_subscription", "last_event_at")
