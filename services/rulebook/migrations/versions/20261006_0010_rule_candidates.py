"""rule candidates: rule_candidate, candidate review tasks, rule_version.candidate_id, an inbox

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-06

Hand-written; mirrors rulebook.infrastructure.models. Expand only:
- ``rule_candidate``: one row per rule candidate the pipeline extracted (rule.candidate.created),
  keyed by the event's candidate_id: its document, regulator (lower case), model, prompt version,
  scores, how the extraction ended, the rest of the event in ``payload``, the suggested rule key,
  whether it looks high impact, and its review: open, drafted (with the version drafted from it),
  approved, or rejected with a reason. Global regulatory data, so no tenant and no row-level
  security (``infra/scripts/migration_lint.toml``).
- ``review_task``: ``kind`` admits ``candidate``, with ``candidate_id``; ``rule_version_id``
  becomes nullable, since a candidate task has no version until an analyst drafts one;
  ``ck_review_task_subject`` keeps a seed task on its version and a candidate task on its
  candidate, and a partial unique index keeps one task per candidate that is not decided. The
  guard now lets ``rule_version_id`` go from null to a version once and never otherwise; a task
  keeps its kind, candidate, regulator and opening time, and a decided task never changes.
- ``rule_version.candidate_id``: the candidate a version was drafted from (unique).
- ``processed_event`` from py-common: the inbox of the rulebook's consumer of
  rule.candidate.created.

Every seed task stored before keeps its version and passes the new checks. The image before
this one expects every task to have a version; it writes no candidate task, and none is written
while the candidate intake (``rulebook.candidate_intake``) is off. The downgrade fails while a
candidate task or a version drafted from a candidate is stored, rather than dropping them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.outbox import create_processed_event_table, drop_processed_event_table

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS_BEFORE = ("seed",)
KINDS_AFTER = (*KINDS_BEFORE, "candidate")
OUTCOMES = ("extracted", "unparseable")
STATUSES = ("open", "drafted", "approved", "rejected")
REJECT_REASONS = ("not_a_rule", "wrong_extraction", "duplicate", "out_of_scope", "unparseable")
UNDECIDED = "status IN ('open', 'claimed')"
TASK_COMMENT_BEFORE = (
    "Review tasks: one decision (approve, return, reject) asked about one rule version, "
    "queued by regulator and priority. A version has at most one task that is not "
    "decided; a decided task never changes (trigger). Global regulatory work: no "
    "tenant, no row-level security."
)
TASK_COMMENT_AFTER = (
    "Review tasks: one decision (approve, return, reject) asked about one rule "
    "version (kind seed) or about one rule candidate and the version drafted from it "
    "(kind candidate), queued by regulator and priority. A version, and a candidate, "
    "has at most one task that is not decided; a decided task never changes and a "
    "task takes its version at most once (trigger). Global regulatory work: no "
    "tenant, no row-level security."
)

GUARD_BEFORE = """
CREATE OR REPLACE FUNCTION rulebook_review_task_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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

GUARD_AFTER = """
CREATE OR REPLACE FUNCTION rulebook_review_task_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'review_task %: a review task is never deleted', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'decided' THEN
    RAISE EXCEPTION 'review_task %: a decided task never changes', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.id, NEW.kind, NEW.candidate_id, NEW.regulator, NEW.opened_at)
     IS DISTINCT FROM (OLD.id, OLD.kind, OLD.candidate_id, OLD.regulator, OLD.opened_at) THEN
    RAISE EXCEPTION 'review_task %: a task keeps its kind, candidate, regulator and opening time',
      OLD.id USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.rule_version_id IS DISTINCT FROM OLD.rule_version_id
     AND OLD.rule_version_id IS NOT NULL THEN
    RAISE EXCEPTION 'review_task %: a task keeps its version once it has one', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END
$$
"""


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        "rule_candidate",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("regulator", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("reject_reason", sa.String(length=24), nullable=True),
        sa.Column("rule_version_id", sa.Uuid(), nullable=True),
        sa.Column("suggested_rule_key", sa.String(length=80), nullable=True),
        sa.Column("high_impact_suggested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "event_id",
            sa.Uuid(),
            nullable=False,
            comment="The rule.candidate.created event it came with",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_rule_candidate"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_rule_candidate_document_id_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name="fk_rule_candidate_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("rule_version_id", name="uq_rule_candidate_rule_version_id"),
        sa.CheckConstraint(
            "regulator = lower(regulator) AND length(btrim(regulator)) > 0",
            name="ck_rule_candidate_regulator",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_rule_candidate_confidence"),
        sa.CheckConstraint("citation_count >= 0", name="ck_rule_candidate_citation_count"),
        sa.CheckConstraint(_in_list("outcome", OUTCOMES), name="ck_rule_candidate_outcome"),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_rule_candidate_status"),
        sa.CheckConstraint(
            f"reject_reason IS NULL OR {_in_list('reject_reason', REJECT_REASONS)}",
            name="ck_rule_candidate_reject_reason",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND rule_version_id IS NULL AND reject_reason IS NULL"
            " AND decided_by IS NULL AND decided_at IS NULL)"
            " OR (status = 'drafted' AND rule_version_id IS NOT NULL AND reject_reason IS NULL"
            " AND decided_by IS NULL AND decided_at IS NULL)"
            " OR (status = 'approved' AND rule_version_id IS NOT NULL AND reject_reason IS NULL"
            " AND decided_by IS NOT NULL AND decided_at IS NOT NULL)"
            " OR (status = 'rejected' AND reject_reason IS NOT NULL"
            " AND decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_rule_candidate_state",
        ),
        comment=(
            "Rule candidates the pipeline extracted (rule.candidate.created), one row per "
            "candidate id; payload keeps the candidate, its issues, the cited clauses and its "
            "source. status moves open, drafted (a version was drafted from it), then "
            "approved or rejected with a reason. Global regulatory data: no tenant, no "
            "row-level security."
        ),
    )
    op.create_index("ix_rule_candidate_document", "rule_candidate", ["document_id"])
    op.create_index("ix_rule_candidate_status", "rule_candidate", ["status", "created_at"])

    op.add_column(
        "rule_version",
        sa.Column(
            "candidate_id",
            sa.Uuid(),
            nullable=True,
            comment="The rule candidate it was drafted from; null for a seed version",
        ),
    )
    op.create_foreign_key(
        "fk_rule_version_candidate_id_rule_candidate",
        "rule_version",
        "rule_candidate",
        ["candidate_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_rule_version_candidate_id", "rule_version", ["candidate_id"])

    op.add_column("review_task", sa.Column("candidate_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_review_task_candidate_id_rule_candidate",
        "review_task",
        "rule_candidate",
        ["candidate_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column("review_task", "rule_version_id", existing_type=sa.Uuid(), nullable=True)
    op.drop_constraint("ck_review_task_kind", "review_task", type_="check")
    op.create_check_constraint("ck_review_task_kind", "review_task", _in_list("kind", KINDS_AFTER))
    op.create_check_constraint(
        "ck_review_task_subject",
        "review_task",
        "(kind = 'seed' AND rule_version_id IS NOT NULL AND candidate_id IS NULL)"
        " OR (kind = 'candidate' AND candidate_id IS NOT NULL)",
    )
    op.create_index(
        "uq_review_task_undecided_candidate",
        "review_task",
        ["candidate_id"],
        unique=True,
        postgresql_where=sa.text(UNDECIDED),
    )
    op.create_index("ix_review_task_candidate", "review_task", ["candidate_id", "opened_at"])
    op.create_table_comment("review_task", TASK_COMMENT_AFTER, existing_comment=TASK_COMMENT_BEFORE)
    op.execute(GUARD_AFTER)

    create_processed_event_table(op)


def downgrade() -> None:
    drop_processed_event_table(op)

    op.execute(GUARD_BEFORE)
    op.create_table_comment("review_task", TASK_COMMENT_BEFORE, existing_comment=TASK_COMMENT_AFTER)
    op.drop_index("ix_review_task_candidate", table_name="review_task")
    op.drop_index("uq_review_task_undecided_candidate", table_name="review_task")
    op.drop_constraint("ck_review_task_subject", "review_task", type_="check")
    op.drop_constraint("ck_review_task_kind", "review_task", type_="check")
    op.create_check_constraint("ck_review_task_kind", "review_task", _in_list("kind", KINDS_BEFORE))
    op.alter_column("review_task", "rule_version_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint(
        "fk_review_task_candidate_id_rule_candidate", "review_task", type_="foreignkey"
    )
    op.drop_column("review_task", "candidate_id")

    op.drop_constraint("uq_rule_version_candidate_id", "rule_version", type_="unique")
    op.drop_constraint(
        "fk_rule_version_candidate_id_rule_candidate", "rule_version", type_="foreignkey"
    )
    op.drop_column("rule_version", "candidate_id")

    op.drop_index("ix_rule_candidate_status", table_name="rule_candidate")
    op.drop_index("ix_rule_candidate_document", table_name="rule_candidate")
    op.drop_table("rule_candidate")
