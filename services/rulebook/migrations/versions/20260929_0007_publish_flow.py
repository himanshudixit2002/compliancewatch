"""publish flow: review columns, the decision audit, the rule_version guard, the outbox

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29

Hand-written; mirrors rulebook.infrastructure.models. Expand-only:
- ``rule_version.high_impact`` (two different approvers, ADR-006) and ``submitted_at`` (the start
  of the current review round).
- ``rule_version_decision``, the append-only audit of every review and publication step.
- ``rulebook_rule_version_insert_guard``, a BEFORE INSERT trigger on ``rule_version``: a version
  is inserted as a draft with no ``published_at``, so every published version went through the
  review flow and its checks.
- ``rulebook_rule_version_guard``, a BEFORE UPDATE trigger on ``rule_version``. The status moves
  only along the kernel's ``RULE_VERSION_TRANSITIONS``, written here as literals (the vocabulary
  test pins them). Once published, superseded or withdrawn, a version's content is frozen and
  ``effective_to`` may only be set or moved earlier. Moving from approved to published needs
  ``published_at``, at least one verified citation and no unverified one, and one distinct
  approver since ``submitted_at`` (two when high impact).
- ``outbox_event`` from py-common: the rule events are written in the same transaction as the
  change they describe (ADR-005) and relayed to Kafka by ``python -m py_common.outbox``.

Nothing here publishes a version: the seed rules stay draft and needs_review.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from py_common.outbox import create_outbox_table, drop_outbox_table

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULE_VERSION_STATUSES = ("draft", "in_review", "approved", "published", "superseded", "withdrawn")
DECISION_ACTIONS = ("submitted", "returned", "approved", "published", "withdrawn", "superseded")
RULE_VERSION_COMMENT = (
    "Rule versions. specification, obligation_template and recurrence hold the kernel's mapping "
    "forms; source and todo come from the seed calendar. A version is inserted as a draft, status "
    "moves only as the kernel's transitions allow, and a published version's content is frozen "
    "(triggers)."
)
OLD_RULE_VERSION_COMMENT = (
    "Rule versions. specification, obligation_template and recurrence hold the kernel's mapping "
    "forms; source and todo come from the seed calendar. Citations to clauses arrive with the "
    "pipeline."
)

INSERT_GUARD = """
CREATE FUNCTION rulebook_rule_version_insert_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status IS DISTINCT FROM 'draft' OR NEW.published_at IS NOT NULL THEN
    RAISE EXCEPTION 'rule_version %: a version is inserted as an unpublished draft, not %',
      NEW.id, NEW.status USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END
$$
"""

GUARD = """
CREATE FUNCTION rulebook_rule_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  approvals integer;
  needed integer;
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status
     AND (OLD.status, NEW.status) NOT IN (
       ('draft', 'in_review'),
       ('in_review', 'approved'),
       ('in_review', 'draft'),
       ('approved', 'published'),
       ('approved', 'draft'),
       ('published', 'superseded'),
       ('published', 'withdrawn')
     ) THEN
    RAISE EXCEPTION 'rule_version %: cannot move from % to %', OLD.id, OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('published', 'superseded', 'withdrawn') THEN
    IF (NEW.id, NEW.rule_id, NEW.version, NEW.title, NEW.summary, NEW.specification,
        NEW.obligation_template, NEW.recurrence, NEW.effective_from, NEW.source,
        NEW.seed_status, NEW.todo, NEW.created_at, NEW.published_at, NEW.high_impact,
        NEW.submitted_at)
       IS DISTINCT FROM
       (OLD.id, OLD.rule_id, OLD.version, OLD.title, OLD.summary, OLD.specification,
        OLD.obligation_template, OLD.recurrence, OLD.effective_from, OLD.source,
        OLD.seed_status, OLD.todo, OLD.created_at, OLD.published_at, OLD.high_impact,
        OLD.submitted_at) THEN
      RAISE EXCEPTION 'rule_version %: the content of a published version is frozen', OLD.id
        USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.effective_to IS DISTINCT FROM OLD.effective_to
       AND (NEW.effective_to IS NULL
            OR (OLD.effective_to IS NOT NULL AND NEW.effective_to > OLD.effective_to)) THEN
      RAISE EXCEPTION 'rule_version %: effective_to may only be set or moved earlier', OLD.id
        USING ERRCODE = 'restrict_violation';
    END IF;
  END IF;
  IF OLD.status = 'approved' AND NEW.status = 'published' THEN
    IF NEW.published_at IS NULL THEN
      RAISE EXCEPTION 'rule_version %: publishing needs published_at', OLD.id
        USING ERRCODE = 'restrict_violation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM citation WHERE rule_version_id = OLD.id AND verified)
       OR EXISTS (SELECT 1 FROM citation WHERE rule_version_id = OLD.id AND NOT verified) THEN
      RAISE EXCEPTION 'rule_version %: publishing needs verified citations and no unverified one',
        OLD.id USING ERRCODE = 'restrict_violation';
    END IF;
    needed := CASE WHEN OLD.high_impact OR NEW.high_impact THEN 2 ELSE 1 END;
    SELECT count(DISTINCT actor_id) INTO approvals FROM rule_version_decision
      WHERE rule_version_id = OLD.id AND action = 'approved' AND actor_id IS NOT NULL
        AND decided_at >= OLD.submitted_at;
    IF approvals < needed THEN
      RAISE EXCEPTION 'rule_version %: publishing needs % approvers, has %', OLD.id, needed,
        approvals USING ERRCODE = 'restrict_violation';
    END IF;
  END IF;
  RETURN NEW;
END
$$
"""


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.add_column(
        "rule_version",
        sa.Column(
            "high_impact",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment="Publishing needs two different approvers (ADR-006)",
        ),
    )
    op.add_column(
        "rule_version",
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Start of the current review round; approvals before it do not count",
        ),
    )
    op.create_table_comment("rule_version", RULE_VERSION_COMMENT)

    op.create_table(
        "rule_version_decision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=False),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("caused_by_rule_version_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_rule_version_decision"),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name="fk_rule_version_decision_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["caused_by_rule_version_id"],
            ["rule_version.id"],
            name="fk_rule_version_decision_caused_by_rule_version_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            _in_list("action", DECISION_ACTIONS), name="ck_rule_version_decision_action"
        ),
        sa.CheckConstraint(
            _in_list("from_status", RULE_VERSION_STATUSES),
            name="ck_rule_version_decision_from_status",
        ),
        sa.CheckConstraint(
            _in_list("to_status", RULE_VERSION_STATUSES),
            name="ck_rule_version_decision_to_status",
        ),
        sa.CheckConstraint(
            "actor_id IS NOT NULL OR caused_by_rule_version_id IS NOT NULL",
            name="ck_rule_version_decision_actor",
        ),
        comment=(
            "The review and publication audit of rule versions (ADR-006): who submitted, "
            "returned, approved, published or withdrew a version, or which version superseded "
            "or withdrew it. Append-only (trigger)."
        ),
    )
    op.create_index(
        "ix_rule_version_decision_version",
        "rule_version_decision",
        ["rule_version_id", "decided_at"],
    )
    op.execute(
        "CREATE TRIGGER tr_rule_version_decision_append_only BEFORE UPDATE OR DELETE"
        " ON rule_version_decision FOR EACH ROW EXECUTE FUNCTION rulebook_append_only()"
    )

    op.execute(INSERT_GUARD)
    op.execute(
        "CREATE TRIGGER tr_rule_version_insert_guard BEFORE INSERT ON rule_version"
        " FOR EACH ROW EXECUTE FUNCTION rulebook_rule_version_insert_guard()"
    )
    op.execute(GUARD)
    op.execute(
        "CREATE TRIGGER tr_rule_version_guard BEFORE UPDATE ON rule_version"
        " FOR EACH ROW EXECUTE FUNCTION rulebook_rule_version_guard()"
    )

    create_outbox_table(op)


def downgrade() -> None:
    drop_outbox_table(op)
    op.execute("DROP TRIGGER tr_rule_version_guard ON rule_version")
    op.execute("DROP FUNCTION rulebook_rule_version_guard()")
    op.execute("DROP TRIGGER tr_rule_version_insert_guard ON rule_version")
    op.execute("DROP FUNCTION rulebook_rule_version_insert_guard()")
    op.drop_index("ix_rule_version_decision_version", table_name="rule_version_decision")
    op.drop_table("rule_version_decision")
    op.create_table_comment("rule_version", OLD_RULE_VERSION_COMMENT)
    op.drop_column("rule_version", "submitted_at")
    op.drop_column("rule_version", "high_impact")
