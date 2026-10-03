"""obligation_reminder and obligation_tenant: the reminder sweep's record and tenant directory

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04

Hand-written; mirrors obligation.infrastructure.models. Expand-only: two new tables, which
nothing reads before this release.

``obligation_reminder`` holds one row per obligation.due_soon event the reminder sweep
publishes, keyed by the event id and written in the same transaction as its outbox row. The
unique (obligation_id, due_at, threshold_days) keeps a repeated sweep from reminding twice, and
the unique (obligation_id, reminder_index) keeps the index the notification service keys
reminders by from repeating. Row-level security is forced, with the tenant policy of the other
tables (py_common.migrations.enable_tenant_rls). The foreign key cascades: a reminder means
nothing without its obligation.

``obligation_tenant`` lists the tenants that have obligations, so a sweep can open one unit of
work per tenant without reading obligations across tenants. It is a routing directory
(infra/scripts/migration_lint.toml): row-level security is forced and every write must pass the
tenant policy, while ``obligation_tenant_directory_read`` lets any session read the ids. The
repository records a tenant when it adds the tenant's first obligation in a unit of work. No
backfill: obligations are only written by the worker this release adds, and a migration could
not read them across tenants anyway.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from py_common.migrations import drop_tenant_rls, enable_tenant_rls

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REMINDER = "obligation_reminder"
DIRECTORY = "obligation_tenant"
DIRECTORY_READ_POLICY = "obligation_tenant_directory_read"


def upgrade() -> None:
    op.create_table(
        REMINDER,
        sa.Column(
            "id", sa.Uuid(), nullable=False, comment="The id of the obligation.due_soon event"
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("threshold_days", sa.Integer(), nullable=False),
        sa.Column("reminder_index", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_obligation_reminder"),
        sa.ForeignKeyConstraint(
            ["obligation_id"],
            ["obligation.id"],
            name="fk_obligation_reminder_obligation_id_obligation",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "obligation_id", "due_at", "threshold_days", name="uq_obligation_reminder_threshold"
        ),
        sa.UniqueConstraint("obligation_id", "reminder_index", name="uq_obligation_reminder_index"),
        sa.CheckConstraint("threshold_days >= 0", name="ck_obligation_reminder_threshold_days"),
        sa.CheckConstraint("reminder_index >= 1", name="ck_obligation_reminder_reminder_index"),
        comment=(
            "Reminders sent for open obligations, one per obligation, due date and "
            "threshold, written with the obligation.due_soon outbox row. Row-level "
            "security by tenant_id."
        ),
    )
    enable_tenant_rls(op, REMINDER)

    op.create_table(
        DIRECTORY,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_obligation_tenant"),
        comment=(
            "Tenants that have obligations, for sweeps that run one tenant unit at a time. "
            "Row-level security: any session may read the ids, a write needs the tenant "
            "setting of its own row."
        ),
    )
    enable_tenant_rls(op, DIRECTORY)
    op.execute(f"CREATE POLICY {DIRECTORY_READ_POLICY} ON {DIRECTORY} FOR SELECT USING (true)")


def downgrade() -> None:
    op.execute(f"DROP POLICY {DIRECTORY_READ_POLICY} ON {DIRECTORY}")
    drop_tenant_rls(op, DIRECTORY)
    op.drop_table(DIRECTORY)
    drop_tenant_rls(op, REMINDER)
    op.drop_table(REMINDER)
