"""error_report_review: tenants' error reports, masked, for the regulatory team to decide

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-08

Hand-written; mirrors rulebook.infrastructure.models. Expand-only: a new table that nothing before
this release reads.

``error_report_review`` holds one row per error report a tenant's member made about an obligation
(error_report.submitted, taken in by the worker's group ``rulebook.error-reports``): the report's
id (unique, so a redelivered event changes nothing), the reporting tenant, the obligation, the rule
version it is about (RESTRICT), the category, the description as the obligation service masked it,
when it arrived, and the decision once an analyst, reviewer or admin made it: confirmed, with the
version that corrects the reported one (RESTRICT), or rejected, with the notes.
``ck_error_report_review_state`` keeps a review decided exactly once and a correcting version on a
confirmed review only.

Regulatory data every tenant's analysts share: no row-level security. ``tenant_id`` is nullable
because a tenant's erasure nulls it and empties the masked text, keeping the decision as a fact
about the rule (``infra/scripts/migration_lint.toml`` exempts the table for that reason). The
index on (status, rule_version_id, received_at) serves the review queue, and the one on tenant_id
the erasure.

The downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "error_report_review"
CATEGORIES = ("due_date", "applicability", "steps", "citation", "other")
STATUSES = ("open", "confirmed", "rejected")
MAX_TEXT_CHARS = 2000
STATE = (
    "(status = 'open' AND decided_by IS NULL AND decided_at IS NULL"
    " AND correcting_rule_version_id IS NULL)"
    " OR (status = 'rejected' AND decided_by IS NOT NULL AND decided_at IS NOT NULL"
    " AND correcting_rule_version_id IS NULL)"
    " OR (status = 'confirmed' AND decided_by IS NOT NULL AND decided_at IS NOT NULL"
    " AND correcting_rule_version_id IS NOT NULL)"
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=True,
            comment="The reporting tenant; null once the tenant was erased",
        ),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column(
            "description_masked",
            sa.Text(),
            nullable=False,
            comment="The reporter's account as the obligation service masked it; '' once erased",
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("correcting_rule_version_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_error_report_review"),
        sa.UniqueConstraint("report_id", name="uq_error_report_review_report_id"),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name="fk_error_report_review_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["correcting_rule_version_id"],
            ["rule_version.id"],
            name="fk_error_report_review_correcting_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            _in_list("category", CATEGORIES), name="ck_error_report_review_category"
        ),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_error_report_review_status"),
        sa.CheckConstraint(
            f"char_length(description_masked) <= {MAX_TEXT_CHARS}",
            name="ck_error_report_review_description",
        ),
        sa.CheckConstraint(
            f"char_length(notes) <= {MAX_TEXT_CHARS}", name="ck_error_report_review_notes"
        ),
        sa.CheckConstraint(STATE, name="ck_error_report_review_state"),
        comment=(
            "Error reports tenants' members made about their obligations, masked, each decided "
            "once by the regulatory team: confirmed with the version that corrects the reported "
            "one, or rejected. Regulatory review shared by every tenant: no row-level security; "
            "an erasure nulls the tenant and empties the text."
        ),
    )
    op.create_index(
        "ix_error_report_review_queue", TABLE, ["status", "rule_version_id", "received_at"]
    )
    op.create_index("ix_error_report_review_tenant", TABLE, ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_error_report_review_tenant", table_name=TABLE)
    op.drop_index("ix_error_report_review_queue", table_name=TABLE)
    op.drop_table(TABLE)
