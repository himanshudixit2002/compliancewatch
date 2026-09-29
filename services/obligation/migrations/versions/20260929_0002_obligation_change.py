"""obligation_change: the append-only change log of obligations, under row-level security

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29

Hand-written; mirrors obligation.infrastructure.models. One row per obligation.created,
obligation.rescheduled or obligation.closed event, keyed by the event id and written in the same
transaction as the event's outbox row (ADR-015: every change writes an audit row).

Expand-only: a new table, which nothing reads before this release. Row-level security is
forced, with the same tenant policy as ``obligation`` (py_common.migrations.enable_tenant_rls).
A trigger refuses UPDATE always and DELETE unless the transaction has set ``app.erasure`` to
``on``, so a tenant's erasure can still remove the rows
(py_common.migrations.create_append_only_guard). The foreign key to ``obligation`` is RESTRICT:
an erasure deletes the change rows before the obligations.

ck_obligation_change_kind lists the change kinds; a later migration that adds a kind drops and
recreates it with the wider list.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from py_common.migrations import (
    create_append_only_guard,
    drop_append_only_guard,
    drop_tenant_rls,
    enable_tenant_rls,
)

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "obligation_change"
KINDS = ("created", "rescheduled", "closed")
STATUSES = ("open", "in_progress", "done", "waived", "closed_not_applicable")
REASONS = (
    "",
    "deadline_extended",
    "corrected",
    "manual",
    "profile_changed",
    "rule_withdrawn",
    "rule_superseded",
    "waived_by_user",
    "completed",
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False, comment="The id of the event that made it"),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_after", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=24), server_default="", nullable=False),
        sa.Column("caused_by_rule_version_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_obligation_change"),
        sa.ForeignKeyConstraint(
            ["obligation_id"],
            ["obligation.id"],
            name="fk_obligation_change_obligation_id_obligation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in_list("kind", KINDS), name="ck_obligation_change_kind"),
        sa.CheckConstraint(
            _in_list("status_after", STATUSES), name="ck_obligation_change_status_after"
        ),
        sa.CheckConstraint(_in_list("reason", REASONS), name="ck_obligation_change_reason"),
        sa.CheckConstraint(
            "kind <> 'rescheduled' OR (previous_due_at IS NOT NULL AND new_due_at IS NOT NULL)",
            name="ck_obligation_change_rescheduled_dates",
        ),
        comment=(
            "Append-only change log of obligations (ADR-015): one row per created, "
            "rescheduled or closed event, written with its outbox row. Row-level "
            "security by tenant_id."
        ),
    )
    op.create_index(
        "ix_obligation_change_obligation", TABLE, ["tenant_id", "obligation_id", "occurred_at"]
    )
    enable_tenant_rls(op, TABLE)
    create_append_only_guard(op, TABLE, allow_erasure_delete=True)


def downgrade() -> None:
    drop_append_only_guard(op, TABLE, allow_erasure_delete=True)
    drop_tenant_rls(op, TABLE)
    op.drop_index("ix_obligation_change_obligation", table_name=TABLE)
    op.drop_table(TABLE)
