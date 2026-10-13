"""error_report: the errors a tenant's members report in its obligations

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08

Hand-written; mirrors obligation.infrastructure.models. Expand-only: a new table that nothing before
this release reads.

``error_report`` holds one row per report: the obligation (RESTRICT: an erasure deletes the reports
before the obligations), the business and rule version it names, the category, the reporter's text
as they wrote it (1 to 2,000 characters; it leaves the service masked for personal identifiers),
who reported it and when, and the regulatory team's decision once it comes back (status, when,
the analyst's notes and, for a confirmed report, the version that corrects the reported one).
``ck_error_report_state`` keeps a report decided exactly once and a correcting version on a
confirmed report only. Row-level security is forced with the tenant policy of the other tables
(``py_common.migrations``). The index on (tenant_id, status, submitted_at) serves the tenant's list
of its open reports.

The downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from py_common.migrations import drop_tenant_rls, enable_tenant_rls

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "error_report"
INDEX = "ix_error_report_tenant_status"
CATEGORIES = ("due_date", "applicability", "steps", "citation", "other")
STATUSES = ("submitted", "confirmed", "rejected")
MAX_TEXT_CHARS = 2000
STATE = (
    "(status = 'submitted' AND decided_at IS NULL AND correcting_rule_version_id IS NULL) "
    "OR (status = 'rejected' AND decided_at IS NOT NULL AND correcting_rule_version_id IS NULL) "
    "OR (status = 'confirmed' AND decided_at IS NOT NULL"
    " AND correcting_rule_version_id IS NOT NULL)"
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "submitted_by",
            sa.Uuid(),
            nullable=True,
            comment="The user who reported it; null when no token named them",
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "notes",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="What the analyst said about the decision",
        ),
        sa.Column(
            "correcting_rule_version_id",
            sa.Uuid(),
            nullable=True,
            comment="For a confirmed report, the version that corrects it",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_error_report"),
        sa.ForeignKeyConstraint(
            ["obligation_id"],
            ["obligation.id"],
            name="fk_error_report_obligation_id_obligation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in_list("category", CATEGORIES), name="ck_error_report_category"),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_error_report_status"),
        sa.CheckConstraint(
            f"char_length(description) BETWEEN 1 AND {MAX_TEXT_CHARS}",
            name="ck_error_report_description",
        ),
        sa.CheckConstraint(f"char_length(notes) <= {MAX_TEXT_CHARS}", name="ck_error_report_notes"),
        sa.CheckConstraint(STATE, name="ck_error_report_state"),
        comment=(
            "Errors a tenant's members reported in its obligations, each decided once by the "
            "regulatory team through the rulebook. The description is the reporter's text; "
            "the rulebook gets it masked. Row-level security by tenant_id."
        ),
    )
    op.create_index(INDEX, TABLE, ["tenant_id", "status", "submitted_at"])
    enable_tenant_rls(op, TABLE)


def downgrade() -> None:
    drop_tenant_rls(op, TABLE)
    op.drop_index(INDEX, table_name=TABLE)
    op.drop_table(TABLE)
