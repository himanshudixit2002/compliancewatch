"""eval_run and eval_gate_result tables, plus the outbox and consumer inbox tables

Revision ID: 0001
Revises:
Create Date: 2026-10-01

Hand-written; mirrors eval_service.infrastructure.models. Table names are unqualified and land in
the schema at the front of search_path (CW_DB_SCHEMA, ``eval``). Eval runs are platform data
shared by every tenant: the ``eval`` schema is in the global group of
infra/scripts/migration_lint.toml, so the tables have no tenant_id and no row-level security.
The outbox and processed-event tables come from py-common (ADR-005).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

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

SUITES = ("extraction", "relations", "qa")
PROFILES = ("ci", "nightly")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        "eval_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("suite", sa.String(length=20), nullable=False),
        sa.Column("profile", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_run_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_eval_run"),
        sa.ForeignKeyConstraint(
            ["previous_run_id"], ["eval_run.id"], name="fk_eval_run_previous_run_id_eval_run"
        ),
        sa.CheckConstraint(_in_list("suite", SUITES), name="ck_eval_run_suite"),
        sa.CheckConstraint(_in_list("profile", PROFILES), name="ck_eval_run_profile"),
        sa.CheckConstraint("completed_at >= started_at", name="ck_eval_run_completed"),
        comment="One run of an eval harness suite under a profile; platform data, no tenant.",
    )
    op.create_index(
        "ix_eval_run_suite_profile_started", "eval_run", ["suite", "profile", "started_at"]
    )
    op.create_index("ix_eval_run_started", "eval_run", ["started_at"])
    op.create_table(
        "eval_gate_result",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("metric", sa.String(length=100), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("previous_value", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", "position", name="pk_eval_gate_result"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["eval_run.id"], name="fk_eval_gate_result_run_id_eval_run"
        ),
        sa.UniqueConstraint("run_id", "name", name="uq_eval_gate_result_name"),
        sa.CheckConstraint("position >= 0", name="ck_eval_gate_result_position"),
        comment="The gates of one eval run, in the harness's order, with the previous value.",
    )
    create_outbox_table(op)
    create_processed_event_table(op)


def downgrade() -> None:
    drop_processed_event_table(op)
    drop_outbox_table(op)
    op.drop_table("eval_gate_result")
    op.drop_index("ix_eval_run_started", table_name="eval_run")
    op.drop_index("ix_eval_run_suite_profile_started", table_name="eval_run")
    op.drop_table("eval_run")
