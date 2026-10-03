"""applicability_decision with row-level security and an append-only guard, plus the outbox and
idempotency key tables

Revision ID: 0001
Revises:
Create Date: 2026-10-01

Hand-written; mirrors applicability_engine.infrastructure.models. Table names are unqualified and
land in the schema at the front of search_path (CW_DB_SCHEMA, ``applicability``).

``applicability_decision`` holds one row per evaluation of a rule version against a business
profile version, written in the same transaction as its ``applicability.decided`` outbox row.
Row-level security is enabled and forced (py_common.migrations.enable_tenant_rls): every
statement sees only the rows of the tenant the ``app.tenant_id`` setting names, and the table
owner is not exempt. A trigger refuses UPDATE always and DELETE unless the transaction has set
``app.erasure`` to ``on`` (py_common.migrations.create_append_only_guard), so recomputing
appends and a tenant's erasure can still remove the rows. The outbox comes from py-common
(ADR-005), and ``idempotency_key`` from py_common.idempotency for the evaluate route (tenant
policy forced, plus the purge policy for expired rows).
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
from py_common.outbox import create_outbox_table, drop_outbox_table

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "applicability_decision"
RESULTS = ("applies", "not_applicable", "unsure")
TRIGGERS = ("manual", "rule_published", "profile_updated")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("as_of_fy", sa.String(length=7), nullable=True),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column(
            "evaluated",
            postgresql.JSONB(),
            nullable=False,
            comment="Per-predicate outcomes, confidences and reasons",
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_applicability_decision"),
        sa.CheckConstraint(_in_list("result", RESULTS), name="ck_applicability_decision_result"),
        sa.CheckConstraint(_in_list("trigger", TRIGGERS), name="ck_applicability_decision_trigger"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_applicability_decision_confidence"
        ),
        sa.CheckConstraint(
            "profile_version >= 1", name="ck_applicability_decision_profile_version"
        ),
        comment=(
            "Applicability decisions, append-only: one row per evaluation of a rule version "
            "against a business profile version, written with its outbox row. Row-level "
            "security by tenant_id."
        ),
    )
    op.create_index(
        "ix_applicability_decision_business",
        TABLE,
        ["tenant_id", "business_id", "decided_at", "id"],
    )
    op.create_index(
        "ix_applicability_decision_rule_version",
        TABLE,
        ["tenant_id", "business_id", "rule_version_id", "decided_at"],
    )
    enable_tenant_rls(op, TABLE)
    create_append_only_guard(op, TABLE, allow_erasure_delete=True)
    create_outbox_table(op)
    create_idempotency_table(op)


def downgrade() -> None:
    drop_idempotency_table(op)
    drop_outbox_table(op)
    drop_append_only_guard(op, TABLE, allow_erasure_delete=True)
    drop_tenant_rls(op, TABLE)
    op.drop_index("ix_applicability_decision_rule_version", table_name=TABLE)
    op.drop_index("ix_applicability_decision_business", table_name=TABLE)
    op.drop_table(TABLE)
