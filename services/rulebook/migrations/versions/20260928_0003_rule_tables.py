"""rule and rule_version tables for the seed calendar and the review flow

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28

Hand-written; mirrors rulebook.infrastructure.models (RuleRow, RuleVersionRow). Predicates,
templates and recurrences are stored in the kernel's mapping forms as jsonb. Citations to
clauses arrive with the pipeline's tables and are not part of this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULE_VERSION_STATUSES = ("draft", "in_review", "approved", "published", "superseded", "withdrawn")
SEED_STATUSES = ("needs_review", "reviewed")
LEVELS = ("entity", "registration", "location")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        "rule",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_key", sa.String(length=80), nullable=False),
        sa.Column("regulator", sa.String(length=40), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rule"),
        sa.UniqueConstraint("rule_key", name="uq_rule_rule_key"),
        sa.CheckConstraint(_in_list("level", LEVELS), name="ck_rule_level"),
        comment="One row per rule; rule_key is the stable key the seed calendar uses.",
    )
    op.create_table(
        "rule_version",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("specification", postgresql.JSONB(), nullable=False),
        sa.Column("obligation_template", postgresql.JSONB(), nullable=False),
        sa.Column("recurrence", postgresql.JSONB(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "source", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "seed_status", sa.String(length=16), server_default="needs_review", nullable=False
        ),
        sa.Column(
            "todo", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_rule_version"),
        sa.ForeignKeyConstraint(["rule_id"], ["rule.id"], name="fk_rule_version_rule_id_rule"),
        sa.UniqueConstraint("rule_id", "version", name="uq_rule_version_rule_id_version"),
        sa.CheckConstraint(
            _in_list("status", RULE_VERSION_STATUSES), name="ck_rule_version_status"
        ),
        sa.CheckConstraint(
            _in_list("seed_status", SEED_STATUSES), name="ck_rule_version_seed_status"
        ),
        sa.CheckConstraint("version >= 1", name="ck_rule_version_version"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_rule_version_effective",
        ),
        comment=(
            "Rule versions. specification, obligation_template and recurrence hold the "
            "kernel's mapping forms; source and todo come from the seed calendar. Citations "
            "to clauses arrive with the pipeline."
        ),
    )
    op.create_index(
        "ix_rule_version_status_effective", "rule_version", ["status", "effective_from"]
    )


def downgrade() -> None:
    op.drop_index("ix_rule_version_status_effective", table_name="rule_version")
    op.drop_table("rule_version")
    op.drop_table("rule")
