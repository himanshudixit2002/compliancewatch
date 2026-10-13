"""review_task closure: when, how and with what outcome a task closed, and the note

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13

Hand-written; mirrors profile_service.infrastructure.models. Expand-only: four nullable or
defaulted columns on review_task, which the code before this release neither reads nor writes
(it only ever opened tasks).

- closed_at: when the task closed; null while it is open, so ``open`` and ``closed_at`` agree
  (ck_review_task_closed).
- closed_by: what closed it, ``answer`` (the attribute the task asked about was answered, in the
  transaction of the answer) or ``resolve`` (a person closed it through the resolve route).
- outcome: ``answered`` for an answer; ``confirmed`` or ``dismissed`` for a resolve.
- note: what the person said when resolving; empty otherwise.

The downgrade drops the four columns and their checks; closed tasks stay closed (``open`` is
false), with nothing more said about how.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "review_task"
CLOSED_BY = ("answer", "resolve")
OUTCOMES = ("answered", "confirmed", "dismissed")
CHECKS = {
    "ck_review_task_closed": "(open) = (closed_at IS NULL)",
    "ck_review_task_closed_by": (
        "(closed_at IS NULL) = (closed_by IS NULL) AND (closed_by IS NULL OR closed_by IN "
        + "("
        + ", ".join(f"'{value}'" for value in CLOSED_BY)
        + "))"
    ),
    "ck_review_task_outcome": (
        "(closed_at IS NULL) = (outcome IS NULL) AND (outcome IS NULL OR outcome IN "
        + "("
        + ", ".join(f"'{value}'" for value in OUTCOMES)
        + "))"
    ),
    "ck_review_task_answered": (
        "(closed_by = 'answer') = (outcome = 'answered') OR closed_by IS NULL"
    ),
}


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("closed_by", sa.String(length=16), nullable=True))
    op.add_column(TABLE, sa.Column("outcome", sa.String(length=16), nullable=True))
    op.add_column(TABLE, sa.Column("note", sa.Text(), nullable=False, server_default=""))
    for name, expression in CHECKS.items():
        op.create_check_constraint(name, TABLE, expression)


def downgrade() -> None:
    for name in reversed(CHECKS):
        op.drop_constraint(name, TABLE, type_="check")
    op.drop_column(TABLE, "note")
    op.drop_column(TABLE, "outcome")
    op.drop_column(TABLE, "closed_by")
    op.drop_column(TABLE, "closed_at")
