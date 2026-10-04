"""processed_event, business_directory and review_item, and trigger_ref on decisions: the
profile.updated consumer and the review queue

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04

Hand-written; mirrors applicability_engine.infrastructure.models. Expand-only: three new tables,
a nullable column with its unique constraint, and a trigger CHECK that admits one more value, so
the code before this release keeps working against it.

``processed_event`` is the consumer inbox of py-common (ADR-005): the profile.updated consumer
records each event it handled in the transaction of its writes.

``business_directory`` lists every hierarchy node the consumer heard of (a legal entity, a
registration or a location), with its tenant, level, parent and the entity at the top of its
lineage. It is a routing directory (infra/scripts/migration_lint.toml): row-level security is
forced and every write must pass the tenant policy, while ``business_directory_read`` lets any
session read the rows, which hold ids and levels only, for a fan-out over every business that
then opens one tenant unit of work at a time. No backfill: the consumer this release adds fills
it, and a migration could not read the profiles across tenants anyway.

``review_item`` holds the decisions a person has to settle: at most one open per business and
rule version (the partial unique index ``uq_review_item_open``), with the decision under review,
the reason (free_text or low_confidence), and once settled the resolution (applies,
not_applicable or dismiss), who settled it, when, the note and the decision a resolution to a
result appended. Row-level security is forced with the tenant policy of the other tables
(py_common.migrations.enable_tenant_rls). Its foreign keys to ``applicability_decision``
cascade, so a tenant's erasure, which may delete decisions, takes the items with them.

``applicability_decision.trigger_ref`` names the event or review item behind a decision
(``profile.updated:<event id>``, ``review:<item id>``; null for a manual evaluation), and
``uq_applicability_decision_trigger_ref`` keeps one decision per (trigger_ref, business, rule
version), so a replayed event inserts nothing. The trigger CHECK gains ``review``. Both changes
are expand steps: the column is nullable and the CHECK only widens. The append-only guard of
migration 0001 still refuses every UPDATE, and adding a column updates no row.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from py_common.migrations import drop_tenant_rls, enable_tenant_rls
from py_common.outbox import create_processed_event_table, drop_processed_event_table

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DECISION = "applicability_decision"
DIRECTORY = "business_directory"
DIRECTORY_READ_POLICY = "business_directory_read"
REVIEW = "review_item"
TRIGGER_CHECK = "ck_applicability_decision_trigger"
TRIGGER_REF_UNIQUE = "uq_applicability_decision_trigger_ref"
TRIGGERS_BEFORE = ("manual", "rule_published", "profile_updated")
TRIGGERS = (*TRIGGERS_BEFORE, "review")
LEVELS = ("entity", "registration", "location")
REASONS = ("free_text", "low_confidence")
STATUSES = ("open", "resolved")
RESOLUTIONS = ("applies", "not_applicable", "dismiss")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    create_processed_event_table(op)

    op.add_column(
        DECISION,
        sa.Column(
            "trigger_ref",
            sa.String(length=120),
            nullable=True,
            comment=(
                "The event or review item that caused the decision (profile.updated:<event id>, "
                "review:<item id>); null for a manual evaluation"
            ),
        ),
    )
    op.create_unique_constraint(
        TRIGGER_REF_UNIQUE, DECISION, ["trigger_ref", "business_id", "rule_version_id"]
    )
    op.drop_constraint(TRIGGER_CHECK, DECISION, type_="check")
    op.create_check_constraint(TRIGGER_CHECK, DECISION, _in_list("trigger", TRIGGERS))

    op.create_table(
        DIRECTORY,
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "entity_id",
            sa.Uuid(),
            nullable=False,
            comment="The legal entity at the top of the node's lineage",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("business_id", name="pk_business_directory"),
        sa.CheckConstraint(_in_list("level", LEVELS), name="ck_business_directory_level"),
        sa.CheckConstraint(
            "(level = 'entity') = (parent_id IS NULL)", name="ck_business_directory_parent"
        ),
        comment=(
            "Every business node the engine heard of, by tenant and level, for fan-outs that "
            "read the ids across tenants and then work one tenant unit at a time. Row-level "
            "security: any session may read, a write needs the tenant setting of its row."
        ),
    )
    op.create_index("ix_business_directory_level", DIRECTORY, ["level", "tenant_id", "business_id"])
    enable_tenant_rls(op, DIRECTORY)
    op.execute(f"CREATE POLICY {DIRECTORY_READ_POLICY} ON {DIRECTORY} FOR SELECT USING (true)")

    op.create_table(
        REVIEW,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("business_id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "decision_id",
            sa.Uuid(),
            nullable=False,
            comment="The decision under review: the pair's latest while open",
        ),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", sa.String(length=16), nullable=True),
        sa.Column(
            "resolved_by",
            sa.Uuid(),
            nullable=True,
            comment="The reviewer; null when a later decision settled the item",
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "resolution_decision_id",
            sa.Uuid(),
            nullable=True,
            comment="The decision a resolution to a result appended",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_item"),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            [f"{DECISION}.id"],
            name="fk_review_item_decision_id_applicability_decision",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolution_decision_id"],
            [f"{DECISION}.id"],
            name="fk_review_item_resolution_decision_id_applicability_decision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(_in_list("reason", REASONS), name="ck_review_item_reason"),
        sa.CheckConstraint(_in_list("status", STATUSES), name="ck_review_item_status"),
        sa.CheckConstraint(
            f"resolution IS NULL OR {_in_list('resolution', RESOLUTIONS)}",
            name="ck_review_item_resolution",
        ),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL AND resolved_at IS NOT NULL)",
            name="ck_review_item_resolved",
        ),
        sa.CheckConstraint(
            "(resolution_decision_id IS NOT NULL) = "
            "(resolution IS NOT NULL AND resolution <> 'dismiss')",
            name="ck_review_item_resolution_decision",
        ),
        comment=(
            "Decisions a person has to settle (a free-text predicate, a low confidence), at "
            "most one open per business and rule version. Row-level security by tenant_id."
        ),
    )
    op.create_index(
        "uq_review_item_open",
        REVIEW,
        ["business_id", "rule_version_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("ix_review_item_queue", REVIEW, ["tenant_id", "status", "opened_at", "id"])
    op.create_index("ix_review_item_decision_id", REVIEW, ["decision_id"])
    enable_tenant_rls(op, REVIEW)


def downgrade() -> None:
    drop_tenant_rls(op, REVIEW)
    op.drop_index("ix_review_item_decision_id", table_name=REVIEW)
    op.drop_index("ix_review_item_queue", table_name=REVIEW)
    op.drop_index("uq_review_item_open", table_name=REVIEW)
    op.drop_table(REVIEW)

    op.execute(f"DROP POLICY {DIRECTORY_READ_POLICY} ON {DIRECTORY}")
    drop_tenant_rls(op, DIRECTORY)
    op.drop_index("ix_business_directory_level", table_name=DIRECTORY)
    op.drop_table(DIRECTORY)

    # Decisions are append-only and a review decision may exist by now: the narrowed CHECK binds
    # new rows only (NOT VALID), so going back deletes no decision.
    op.drop_constraint(TRIGGER_CHECK, DECISION, type_="check")
    op.execute(
        f"ALTER TABLE {DECISION} ADD CONSTRAINT {TRIGGER_CHECK} "
        f"CHECK ({_in_list('trigger', TRIGGERS_BEFORE)}) NOT VALID"
    )
    op.drop_constraint(TRIGGER_REF_UNIQUE, DECISION, type_="unique")
    op.drop_column(DECISION, "trigger_ref")

    drop_processed_event_table(op)
