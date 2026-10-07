"""the billing ledger and the idempotency keys of the subscription route

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07

Hand-written; mirrors identity.infrastructure.models. Expand-only: new tables that nothing reads
before this release (the ledger lived in the process's memory until now, so nothing moves).

- billing_customer: a tenant's customer at the billing provider, one per tenant.
- billing_subscription: the tenant's subscriptions, keyed by the provider's id, with the plan,
  the quantity and the current status.
- billing_event: every verified webhook of a tenant, its payload masked for personal identifiers;
  unique on (tenant_id, body_sha256), so a redelivered body is recorded once. A trigger refuses
  UPDATE, and DELETE unless the transaction is a tenant erasure (``app.erasure``).
- idempotency_key (py_common.idempotency) for ``POST /v1/identity/billing/subscriptions``.

All four are under forced row-level security with the tenant policy
(py_common.migrations.enable_tenant_rls); the idempotency table also has the purge policy of the
daily purge. There are no foreign keys to tenant: a webhook names its tenant in the provider's
notes, and a row must never be refused for that reason. cw_identity and cw_app reach the tables
through the default privileges infra/dev/postgres/roles.sql grants on the schema. The downgrade
drops the tables with what they hold.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.idempotency.schema import create_idempotency_table, drop_idempotency_table
from py_common.migrations import (
    create_append_only_guard,
    drop_append_only_guard,
    drop_tenant_rls,
    enable_tenant_rls,
)

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = ("created", "active", "past_due", "cancelled")
STATUS_IN = f"status IN ({', '.join(f"'{status}'" for status in STATUSES)})"


def upgrade() -> None:
    op.create_table(
        "billing_customer",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_customer_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_billing_customer"),
        comment="A tenant's customer at the billing provider; row-level security by tenant_id",
    )
    enable_tenant_rls(op, "billing_customer")

    op.create_table(
        "billing_subscription",
        sa.Column("provider_subscription_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("plan_key", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checkout_url", sa.Text(), nullable=False, server_default=""),
        sa.PrimaryKeyConstraint("provider_subscription_id", name="pk_billing_subscription"),
        sa.CheckConstraint(STATUS_IN, name="ck_billing_subscription_status"),
        sa.CheckConstraint("quantity >= 1", name="ck_billing_subscription_quantity"),
        comment=(
            "A tenant's subscriptions at the billing provider and their current status; "
            "row-level security by tenant_id"
        ),
    )
    op.create_index(
        "ix_billing_subscription_tenant_started",
        "billing_subscription",
        ["tenant_id", "started_at"],
    )
    enable_tenant_rls(op, "billing_subscription")

    op.create_table(
        "billing_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider_subscription_id", sa.String(length=64), nullable=False, server_default=""
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_event", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_billing_event"),
        sa.UniqueConstraint("tenant_id", "body_sha256", name="uq_billing_event_body"),
        sa.CheckConstraint(f"status IS NULL OR {STATUS_IN}", name="ck_billing_event_status"),
        sa.CheckConstraint("body_sha256 ~ '^[0-9a-f]{64}$'", name="ck_billing_event_body_sha256"),
        comment=(
            "Append-only verified billing webhooks with the payload masked; row-level security "
            "by tenant_id"
        ),
    )
    op.create_index(
        "ix_billing_event_subscription",
        "billing_event",
        ["tenant_id", "provider_subscription_id", "received_at"],
    )
    enable_tenant_rls(op, "billing_event")
    create_append_only_guard(op, "billing_event", allow_erasure_delete=True)

    create_idempotency_table(op)


def downgrade() -> None:
    drop_idempotency_table(op)
    drop_append_only_guard(op, "billing_event", allow_erasure_delete=True)
    drop_tenant_rls(op, "billing_event")
    op.drop_index("ix_billing_event_subscription", table_name="billing_event")
    op.drop_table("billing_event")
    drop_tenant_rls(op, "billing_subscription")
    op.drop_index("ix_billing_subscription_tenant_started", table_name="billing_subscription")
    op.drop_table("billing_subscription")
    drop_tenant_rls(op, "billing_customer")
    op.drop_table("billing_customer")
