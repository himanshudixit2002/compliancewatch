"""a tenant's data requests: exports now, deletions once the erasure cascade lands

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07

Hand-written; mirrors identity.infrastructure.models. Expand-only: a new table that nothing reads
before this release.

- data_request: one row per request a tenant (self_service) or support for it (support) made,
  with its kind (export, or deletion, which the routes refuse until the erasure cascade exists),
  the reason, when it was made and its deadline, 30 days later (docs/legal/data-map.md), its
  status (received, in_progress, completed), the services that answered so far and when it
  completed. No personal data beyond who asked (an actor label) and the reason they gave.

Under forced row-level security with the tenant policy (py_common.migrations.enable_tenant_rls).
Counting every tenant's overdue requests for the DataRequestOverdue alert goes through
identity.data_requests_open(), a SECURITY DEFINER function owned by the NOLOGIN role
cw_identity_directory with a read-only policy of its own; infra/dev/postgres/roles.sql makes
the role, the function and that policy once this table exists (make migrate runs it after the
migrations, and so does a deployment's role step). The downgrade drops the function, the table
and what it holds.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.migrations import drop_tenant_rls, enable_tenant_rls

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("export", "deletion")
SOURCES = ("self_service", "support")
STATUSES = ("received", "in_progress", "completed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        "data_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("requested_by", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "services_done",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_data_request"),
        sa.CheckConstraint(_in("kind", KINDS), name="ck_data_request_kind"),
        sa.CheckConstraint(_in("source", SOURCES), name="ck_data_request_source"),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_data_request_status"),
        sa.CheckConstraint("deadline_at > requested_at", name="ck_data_request_deadline"),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="ck_data_request_completed",
        ),
        comment=(
            "A tenant's export and deletion requests with their 30-day deadline; row-level "
            "security by tenant_id"
        ),
    )
    op.create_index(
        "ix_data_request_tenant_requested", "data_request", ["tenant_id", "requested_at"]
    )
    op.create_index(
        "ix_data_request_open_deadline",
        "data_request",
        ["deadline_at"],
        postgresql_where=sa.text("status <> 'completed'"),
    )
    enable_tenant_rls(op, "data_request")


def downgrade() -> None:
    # The function belongs to cw_identity_directory (roles.sql); the owner drops it as the role,
    # which it may act as but whose privileges it does not inherit.
    op.execute(
        "DO $drop$ BEGIN "
        "IF to_regprocedure('identity.data_requests_open()') IS NOT NULL THEN "
        "SET LOCAL ROLE cw_identity_directory; "
        "DROP FUNCTION identity.data_requests_open(); "
        "RESET ROLE; "
        "END IF; END $drop$"
    )
    drop_tenant_rls(op, "data_request")
    op.drop_index("ix_data_request_open_deadline", table_name="data_request")
    op.drop_index("ix_data_request_tenant_requested", table_name="data_request")
    op.drop_table("data_request")
