"""rule_version_ref and obligation_decision: the rule version cache and the window's decisions

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06

Hand-written; mirrors obligation.infrastructure.models. Expand-only: two new tables, which nothing
reads before this release.

``rule_version_ref`` caches what the service needs of a rule version: its rule key, status,
title, effective dates, seed status, the approvers of the round it was published from, when it
was published, its verified citations (JSON) and when the rulebook was read. The decision
consumer fills it when a version is missing, from a read made before its transaction began, and
the rule events consumer keeps it current; a status only moves past publication and an
effective_to only moves earlier (``RuleVersionRef.merge``). It is rule-level data, the same for
every tenant: no tenant_id and no row-level security, exempt in infra/scripts/migration_lint.toml.

``obligation_decision`` keeps, per business and rule version, the latest applies or
not_applicable decision the service acted on, which the daily rolling window reads to make the
periods that entered its window. Row-level security is forced with the tenant policy of the other
tables (py_common.migrations.enable_tenant_rls). No backfill: a migration cannot read decisions
across tenants, and the service never stored them before, so a business decided before this
release has its window rolled from its next decision on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.migrations import drop_tenant_rls, enable_tenant_rls

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CACHE = "rule_version_ref"
DECISION = "obligation_decision"
RULE_VERSION_STATUSES = ("draft", "in_review", "approved", "published", "superseded", "withdrawn")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        CACHE,
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("rule_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("seed_status", sa.String(length=24), nullable=False),
        sa.Column("approved_by", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("rule_version_id", name="pk_rule_version_ref"),
        sa.CheckConstraint(
            _in_list("status", RULE_VERSION_STATUSES), name="ck_rule_version_ref_status"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_rule_version_ref_effective",
        ),
        comment=(
            "The rule versions obligations come from, as the rulebook last described them: "
            "status, dates, approvers and verified citations. Rule-level, the same for every "
            "tenant."
        ),
    )

    op.create_table(
        DECISION,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("applies", sa.Boolean(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("business_id", "rule_version_id", name="pk_obligation_decision"),
        comment=(
            "The latest applies or not_applicable decision per business and rule version, "
            "which the daily rolling window reads. Row-level security by tenant_id."
        ),
    )
    op.create_index(
        "ix_obligation_decision_tenant_applies", DECISION, ["tenant_id", "applies"], unique=False
    )
    enable_tenant_rls(op, DECISION)


def downgrade() -> None:
    drop_tenant_rls(op, DECISION)
    op.drop_index("ix_obligation_decision_tenant_applies", table_name=DECISION)
    op.drop_table(DECISION)
    op.drop_table(CACHE)
