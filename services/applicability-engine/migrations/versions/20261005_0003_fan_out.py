"""fanout_run and fanout_hold: the rule.published fan-out and its global hold

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05

Hand-written; mirrors applicability_engine.infrastructure.models. Expand-only: two new tables.

``fanout_run`` holds one row per published rule version the engine fans out over the business
directory: its rule key and level, its status (running, paused, held, completed, cancelled,
disabled or failed), the counters (the directory entries of the level when it began, the
businesses decided, those the version applies to, those compared with the superseded version and
those whose result flipped), when it started, was last changed and finished, the rule.published
event that started it, why and by whom its status last changed (a user id, ``system:<service>``
or ``service:<client>``, never a name) and its last error. ``finished_at`` is set exactly when
the status is no longer active (``ck_fanout_run_finished``).

``fanout_hold`` is the global hold: its one row (``id = 1``, ``ck_fanout_hold_single``) exists
while the hold is set, with the reason (at least ten characters), who set it and when; releasing
it deletes the row. The audit log keeps every hold and release.

Both tables are rule-level, not tenant data, so they carry no tenant_id and no row-level security
(exempt in infra/scripts/migration_lint.toml); the audit entries of their controls belong to no
tenant (``audit.event``'s platform insert). ``make product-role`` grants them to ``cw_app`` like
every table of the schema (infra/dev/postgres/50-app-role.sql: its default privileges cover the
tables a later migration creates).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN = "fanout_run"
HOLD = "fanout_hold"
STATUSES = ("running", "paused", "held", "completed", "cancelled", "disabled", "failed")
ACTIVE = ("running", "paused", "held")
LEVELS = ("entity", "registration", "location")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        RUN,
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("rule_key", sa.String(length=80), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "trigger_event_id",
            sa.Uuid(),
            nullable=False,
            comment="The rule.published event that started the fan-out",
        ),
        sa.Column(
            "supersedes",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
            comment="Rule version ids it supersedes; flips count against their decisions",
        ),
        sa.Column(
            "businesses_total",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Directory entries of the level when the run began",
        ),
        sa.Column("evaluated", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("applies", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("flips_compared", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("flips", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status_reason",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="Why the status last changed",
        ),
        sa.Column(
            "status_by",
            sa.String(length=200),
            server_default="",
            nullable=False,
            comment="Who changed it: a user id, system:<service> or service:<client>; never a name",
        ),
        sa.Column(
            "last_error",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="Why the run failed",
        ),
        sa.PrimaryKeyConstraint("rule_version_id", name="pk_fanout_run"),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_fanout_run_status"),
        sa.CheckConstraint(_in_list("level", LEVELS), name="ck_fanout_run_level"),
        sa.CheckConstraint(
            "businesses_total >= 0 AND evaluated >= 0 AND applies >= 0 AND flips_compared >= 0 "
            "AND flips >= 0 AND applies <= evaluated AND flips <= flips_compared",
            name="ck_fanout_run_counters",
        ),
        sa.CheckConstraint(
            f"(finished_at IS NULL) = ({_in_list('status', ACTIVE)})",
            name="ck_fanout_run_finished",
        ),
        comment=(
            "One fan-out per published rule version: its status, counters, and the reason and "
            "author of its last change of status. Rule-level, of no tenant: no row-level security."
        ),
    )
    op.create_index("ix_fanout_run_started", RUN, ["started_at", "rule_version_id"])
    op.create_index("ix_fanout_run_status", RUN, ["status"])

    op.create_table(
        HOLD,
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "set_by",
            sa.String(length=200),
            nullable=False,
            comment="A user id, system:<service> or service:<client>; never a name",
        ),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_fanout_hold"),
        sa.CheckConstraint("id = 1", name="ck_fanout_hold_single"),
        sa.CheckConstraint("length(btrim(reason)) >= 10", name="ck_fanout_hold_reason"),
        comment=(
            "The global fan-out hold: while its one row exists no fan-out starts its next batch. "
            "Rule-level, of no tenant: no row-level security."
        ),
    )


def downgrade() -> None:
    op.drop_table(HOLD)
    op.drop_index("ix_fanout_run_status", table_name=RUN)
    op.drop_index("ix_fanout_run_started", table_name=RUN)
    op.drop_table(RUN)
