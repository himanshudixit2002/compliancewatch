"""candidate version keys: a candidate's draft is the one its candidate and its task name

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06

Hand-written; mirrors rulebook.infrastructure.models. Expand only: one unique constraint and two
composite foreign keys, so the database ties the three places that name a candidate's draft
together. Before them, the guard let a candidate task's ``rule_version_id`` go from null to any
version, and ``rule_candidate.rule_version_id`` and ``rule_version.candidate_id`` could disagree.

- ``uq_rule_version_id_candidate_id`` on ``rule_version (id, candidate_id)``: what the two keys
  below reference. ``id`` is the primary key, so every row passes.
- ``fk_review_task_rule_version_id_candidate_id_rule_version``: ``review_task (rule_version_id,
  candidate_id)`` references ``rule_version (id, candidate_id)``, so a candidate task's version is
  the one drafted from its own candidate. MATCH SIMPLE checks a row only when both are set: a
  seed task (no candidate) and a candidate task not drafted yet (no version) are not checked.
- ``fk_rule_candidate_rule_version_id_id_rule_version``: ``rule_candidate (rule_version_id, id)``
  references ``rule_version (id, candidate_id)``, so the version a candidate names was drafted
  from it; an open candidate, or one rejected before drafting, has no version and is not checked.

Both keys also stop a version's ``candidate_id`` changing while a task or its candidate names it.
Drafting inserts the version, naming its candidate, before it points the candidate and the task
at it, so the keys hold after every statement and are not deferred. Every row stored before is
checked first, and a row that disagrees stops the upgrade with a message rather than a bare
foreign key error. The downgrade drops the three.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISAGREEING = """
SELECT
  (SELECT count(*) FROM review_task t
    WHERE t.rule_version_id IS NOT NULL AND t.candidate_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM rule_version v
                       WHERE v.id = t.rule_version_id AND v.candidate_id = t.candidate_id))
  + (SELECT count(*) FROM rule_candidate c
      WHERE c.rule_version_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM rule_version v
                         WHERE v.id = c.rule_version_id AND v.candidate_id = c.id))
"""


def upgrade() -> None:
    rows = op.get_bind().execute(sa.text(DISAGREEING)).scalar_one()
    if rows:
        raise RuntimeError(
            "0011 ties a candidate's draft to its candidate and its task, and found "
            f"{rows} review_task or rule_candidate rows naming a version drafted from another "
            "candidate; correct them before upgrading"
        )
    op.create_unique_constraint(
        "uq_rule_version_id_candidate_id", "rule_version", ["id", "candidate_id"]
    )
    op.create_foreign_key(
        "fk_review_task_rule_version_id_candidate_id_rule_version",
        "review_task",
        "rule_version",
        ["rule_version_id", "candidate_id"],
        ["id", "candidate_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_rule_candidate_rule_version_id_id_rule_version",
        "rule_candidate",
        "rule_version",
        ["rule_version_id", "id"],
        ["id", "candidate_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_rule_candidate_rule_version_id_id_rule_version", "rule_candidate", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_review_task_rule_version_id_candidate_id_rule_version",
        "review_task",
        type_="foreignkey",
    )
    op.drop_constraint("uq_rule_version_id_candidate_id", "rule_version", type_="unique")
