"""review tasks: review_task with its guard, and the edited decision

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06

Hand-written; mirrors rulebook.infrastructure.models. Expand only:
- ``review_task``: one decision (approve, return, reject) asked about one rule version, queued by
  regulator and priority. ``kind`` is ``seed`` (a draft the seed calendar wrote); the pipeline's
  candidates add their own kind later. A partial unique index keeps at most one task per version
  that is not decided (open or claimed). Global regulatory work, so no tenant and no row-level
  security (``infra/scripts/migration_lint.toml``).
- ``rulebook_review_task_guard``, a BEFORE UPDATE OR DELETE trigger: a decided task never changes,
  a task keeps its version, kind, regulator and opening time, and no task is deleted.
- ``ck_rule_version_decision_action`` admits ``edited``: an analyst's change to a draft through its
  review task, recorded in the decision audit with what it changed.

The image before this one writes neither. The downgrade fails while an ``edited`` decision is
recorded (the audit is append-only), rather than dropping it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS_BEFORE = ("submitted", "returned", "approved", "published", "withdrawn", "superseded")
ACTIONS_AFTER = (*ACTIONS_BEFORE, "edited")
KINDS = ("seed",)
STATUSES = ("open", "claimed", "decided")
DECISIONS = ("approve", "return", "reject")
UNDECIDED = "status IN ('open', 'claimed')"

GUARD = """
CREATE FUNCTION rulebook_review_task_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'review_task %: a review task is never deleted', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'decided' THEN
    RAISE EXCEPTION 'review_task %: a decided task never changes', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.id, NEW.rule_version_id, NEW.kind, NEW.regulator, NEW.opened_at)
     IS DISTINCT FROM (OLD.id, OLD.rule_version_id, OLD.kind, OLD.regulator, OLD.opened_at) THEN
    RAISE EXCEPTION 'review_task %: a task keeps its version, kind, regulator and opening time',
      OLD.id USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END
$$
"""


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        "review_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("regulator", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("claimed_by", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_review_task"),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name="fk_review_task_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in_list("kind", KINDS), name="ck_review_task_kind"),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_review_task_status"),
        sa.CheckConstraint(
            f"decision IS NULL OR {_in_list('decision', DECISIONS)}",
            name="ck_review_task_decision",
        ),
        sa.CheckConstraint("priority BETWEEN 0 AND 1000", name="ck_review_task_priority"),
        sa.CheckConstraint(
            "(claimed_by IS NULL) = (claimed_at IS NULL)", name="ck_review_task_claim"
        ),
        sa.CheckConstraint(
            "(status = 'open' AND claimed_by IS NULL AND decision IS NULL"
            " AND decided_by IS NULL AND decided_at IS NULL)"
            " OR (status = 'claimed' AND claimed_by IS NOT NULL AND decision IS NULL"
            " AND decided_by IS NULL AND decided_at IS NULL)"
            " OR (status = 'decided' AND decision IS NOT NULL AND decided_by IS NOT NULL"
            " AND decided_at IS NOT NULL)",
            name="ck_review_task_state",
        ),
        comment=(
            "Review tasks: one decision (approve, return, reject) asked about one rule version, "
            "queued by regulator and priority. A version has at most one task that is not "
            "decided; a decided task never changes (trigger). Global regulatory work: no "
            "tenant, no row-level security."
        ),
    )
    op.create_index(
        "uq_review_task_undecided_version",
        "review_task",
        ["rule_version_id"],
        unique=True,
        postgresql_where=sa.text(UNDECIDED),
    )
    op.create_index("ix_review_task_rule_version", "review_task", ["rule_version_id", "opened_at"])
    op.create_index(
        "ix_review_task_queue", "review_task", ["status", "regulator", "priority", "opened_at"]
    )
    op.execute(GUARD)
    op.execute(
        "CREATE TRIGGER tr_review_task_guard BEFORE UPDATE OR DELETE ON review_task"
        " FOR EACH ROW EXECUTE FUNCTION rulebook_review_task_guard()"
    )

    op.drop_constraint("ck_rule_version_decision_action", "rule_version_decision", type_="check")
    op.create_check_constraint(
        "ck_rule_version_decision_action",
        "rule_version_decision",
        _in_list("action", ACTIONS_AFTER),
    )


def downgrade() -> None:
    op.drop_constraint("ck_rule_version_decision_action", "rule_version_decision", type_="check")
    op.create_check_constraint(
        "ck_rule_version_decision_action",
        "rule_version_decision",
        _in_list("action", ACTIONS_BEFORE),
    )
    op.execute("DROP TRIGGER tr_review_task_guard ON review_task")
    op.execute("DROP FUNCTION rulebook_review_task_guard()")
    op.drop_index("ix_review_task_queue", table_name="review_task")
    op.drop_index("ix_review_task_rule_version", table_name="review_task")
    op.drop_index("uq_review_task_undecided_version", table_name="review_task")
    op.drop_table("review_task")
