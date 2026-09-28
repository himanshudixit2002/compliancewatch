"""review_task.reason accepts verify_registration (the GSTIN lookup was unavailable)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("not_applicable", "confirm_financial_year")
NEW = (*OLD, "verify_registration")


def _in_list(values: tuple[str, ...]) -> str:
    return f"reason IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.drop_constraint("ck_review_task_reason", "review_task", type_="check")
    op.create_check_constraint("ck_review_task_reason", "review_task", _in_list(NEW))


def downgrade() -> None:
    op.execute("DELETE FROM review_task WHERE reason = 'verify_registration'")
    op.drop_constraint("ck_review_task_reason", "review_task", type_="check")
    op.create_check_constraint("ck_review_task_reason", "review_task", _in_list(OLD))
