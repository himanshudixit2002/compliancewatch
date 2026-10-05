"""obligation tracking: profile version, assignee, people's changes, comments, idempotency keys

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06

Hand-written; mirrors obligation.infrastructure.models. Expand-only: nullable columns, a column
with a default, two new tables and a wider CHECK; nothing that runs today reads the new shape.

- ``obligation`` gets ``profile_version``, the profile version of the decision that made it, and
  ``assignee_id``. ``obligation_decision`` gets ``profile_version`` too, which the rolling window
  gives the periods it makes. No backfill: the service never kept the decisions' profile
  versions, so an obligation made before this release keeps null.
- ``obligation_change`` records the changes people make that no event records: the kind check
  (``ck_obligation_change_kind``) is dropped and recreated with ``started``, ``assigned`` and
  ``unassigned``. ``previous_assignee_id`` and ``new_assignee_id`` name the assignees of an
  assignment and nothing else (``ck_obligation_change_assignees``), and ``note`` keeps what the
  person said, a waiver's reason (at most 2,000 characters). Adding a column fires no row trigger,
  so the append-only guard stays as it is; the table and id comments say what the rows are now.
- ``obligation_comment``: one row per comment, with its author and its body (1 to 2,000
  characters). Row-level security is forced with the tenant policy of the other tables, and the
  append-only guard refuses UPDATE always and DELETE outside a tenant's erasure
  (``py_common.migrations``). The foreign key is RESTRICT: an erasure deletes the comments before
  the obligations, as it deletes the change rows.
- ``idempotency_key`` from ``py_common.idempotency`` for the status, assignee and comment routes
  (tenant policy forced, plus the purge policy of the daily purge).

The downgrade drops what the upgrade added. The change log is append-only evidence, and a row of
a new kind may exist by then: the narrowed kind check binds new rows only (NOT VALID), so going
back deletes no change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from py_common.idempotency.schema import create_idempotency_table, drop_idempotency_table
from py_common.migrations import (
    create_append_only_guard,
    drop_append_only_guard,
    drop_tenant_rls,
    enable_tenant_rls,
)

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OBLIGATION = "obligation"
DECISION = "obligation_decision"
CHANGE = "obligation_change"
COMMENT = "obligation_comment"
PROFILE_VERSION_CHECK = "ck_obligation_profile_version"
KIND_CHECK = "ck_obligation_change_kind"
ASSIGNEES_CHECK = "ck_obligation_change_assignees"
NOTE_CHECK = "ck_obligation_change_note"
KINDS_BEFORE = ("created", "rescheduled", "closed")
KINDS = (*KINDS_BEFORE, "started", "assigned", "unassigned")
ASSIGNEES = (
    "CASE kind WHEN 'assigned' THEN new_assignee_id IS NOT NULL "
    "WHEN 'unassigned' THEN previous_assignee_id IS NOT NULL AND new_assignee_id IS NULL "
    "ELSE previous_assignee_id IS NULL AND new_assignee_id IS NULL END"
)
MAX_TEXT_CHARS = 2000
CHANGE_COMMENT_BEFORE = (
    "Append-only change log of obligations (ADR-015): one row per created, rescheduled or "
    "closed event, written with its outbox row. Row-level security by tenant_id."
)
CHANGE_COMMENT = (
    "Append-only change log of obligations (ADR-015): one row per change, written with the "
    "outbox row of the event that records it, if any. Row-level security by tenant_id."
)
CHANGE_ID_COMMENT_BEFORE = "The id of the event that made it"
CHANGE_ID_COMMENT = "The id of the event that made it, or its own for a change no event records"


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.add_column(
        OBLIGATION,
        sa.Column(
            "profile_version",
            sa.Integer(),
            nullable=True,
            comment="The profile version of the decision that made it",
        ),
    )
    op.add_column(OBLIGATION, sa.Column("assignee_id", sa.Uuid(), nullable=True))
    op.create_check_constraint(
        PROFILE_VERSION_CHECK, OBLIGATION, "profile_version IS NULL OR profile_version >= 1"
    )
    op.add_column(DECISION, sa.Column("profile_version", sa.Integer(), nullable=True))

    op.drop_constraint(KIND_CHECK, CHANGE, type_="check")
    op.create_check_constraint(KIND_CHECK, CHANGE, _in_list("kind", KINDS))
    op.add_column(CHANGE, sa.Column("previous_assignee_id", sa.Uuid(), nullable=True))
    op.add_column(CHANGE, sa.Column("new_assignee_id", sa.Uuid(), nullable=True))
    op.add_column(
        CHANGE,
        sa.Column(
            "note",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="What the person said: a waiver's reason",
        ),
    )
    op.create_check_constraint(ASSIGNEES_CHECK, CHANGE, ASSIGNEES)
    op.create_check_constraint(NOTE_CHECK, CHANGE, f"char_length(note) <= {MAX_TEXT_CHARS}")
    op.create_table_comment(CHANGE, CHANGE_COMMENT, existing_comment=CHANGE_COMMENT_BEFORE)
    op.alter_column(
        CHANGE,
        "id",
        existing_type=sa.Uuid(),
        existing_nullable=False,
        comment=CHANGE_ID_COMMENT,
        existing_comment=CHANGE_ID_COMMENT_BEFORE,
    )

    op.create_table(
        COMMENT,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "author_id",
            sa.Uuid(),
            nullable=True,
            comment="The user who wrote it; null when no token named the caller",
        ),
        sa.Column(
            "author_label",
            sa.String(length=200),
            nullable=False,
            comment=(
                "The author as the audit log labels them: roles, service:<client> or system:<name>"
            ),
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_obligation_comment"),
        sa.ForeignKeyConstraint(
            ["obligation_id"],
            ["obligation.id"],
            name="fk_obligation_comment_obligation_id_obligation",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"char_length(body) BETWEEN 1 AND {MAX_TEXT_CHARS}", name="ck_obligation_comment_body"
        ),
        comment=(
            "Comments on obligations, each with its author; append-only. Row-level security by "
            "tenant_id."
        ),
    )
    op.create_index(
        "ix_obligation_comment_obligation", COMMENT, ["tenant_id", "obligation_id", "created_at"]
    )
    enable_tenant_rls(op, COMMENT)
    create_append_only_guard(op, COMMENT, allow_erasure_delete=True)

    create_idempotency_table(op)


def downgrade() -> None:
    drop_idempotency_table(op)

    drop_append_only_guard(op, COMMENT, allow_erasure_delete=True)
    drop_tenant_rls(op, COMMENT)
    op.drop_index("ix_obligation_comment_obligation", table_name=COMMENT)
    op.drop_table(COMMENT)

    op.alter_column(
        CHANGE,
        "id",
        existing_type=sa.Uuid(),
        existing_nullable=False,
        comment=CHANGE_ID_COMMENT_BEFORE,
        existing_comment=CHANGE_ID_COMMENT,
    )
    op.create_table_comment(CHANGE, CHANGE_COMMENT_BEFORE, existing_comment=CHANGE_COMMENT)
    op.drop_constraint(NOTE_CHECK, CHANGE, type_="check")
    op.drop_constraint(ASSIGNEES_CHECK, CHANGE, type_="check")
    op.drop_column(CHANGE, "note")
    op.drop_column(CHANGE, "new_assignee_id")
    op.drop_column(CHANGE, "previous_assignee_id")
    # The change log is append-only and a person's change may exist by now: the narrowed CHECK
    # binds new rows only (NOT VALID), so going back deletes no change.
    op.drop_constraint(KIND_CHECK, CHANGE, type_="check")
    op.execute(
        f"ALTER TABLE {CHANGE} ADD CONSTRAINT {KIND_CHECK} "
        f"CHECK ({_in_list('kind', KINDS_BEFORE)}) NOT VALID"
    )

    op.drop_column(DECISION, "profile_version")
    op.drop_constraint(PROFILE_VERSION_CHECK, OBLIGATION, type_="check")
    op.drop_column(OBLIGATION, "assignee_id")
    op.drop_column(OBLIGATION, "profile_version")
