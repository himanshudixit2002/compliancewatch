"""knowledge schema: canonical_entity, clause_entity, rule_relation

Revision ID: 0001
Revises:
Create Date: 2026-09-28

Hand-written; mirrors rulebook.infrastructure.models. Table names are unqualified and land in
the schema at the front of search_path (CW_DB_SCHEMA, ``rulebook``). clause_id and
from_rule_version_id are plain uuid columns: the clause and rule_version tables do not exist yet,
and the migration that creates them adds the foreign keys. The three rule_relation checks beyond
the vocabulary repeat the kernel's rules: supersedes and extends_deadline target a rule version,
to_entity_id is set exactly when the target is an entity, and a rule version never relates to
itself.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENTITY_TYPES = (
    "notification",
    "circular",
    "section",
    "rule",
    "form",
    "hsn_code",
    "sac_code",
    "tax_rate",
    "threshold",
    "state",
)
RELATION_KINDS = ("supersedes", "amends", "refers_to", "exempts", "extends_deadline")
TARGET_KINDS = ("rule_version", *ENTITY_TYPES)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.create_table(
        "canonical_entity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_canonical_entity"),
        sa.CheckConstraint(_in_list("type", ENTITY_TYPES), name="ck_canonical_entity_type"),
        sa.UniqueConstraint(
            "type", "canonical_name", name="uq_canonical_entity_type_canonical_name"
        ),
        comment=(
            "Aligned knowledge entities (one row per type and canonical name); "
            "aliases hold the surface forms seen in clauses."
        ),
    )
    op.create_index(
        "ix_canonical_entity_aliases",
        "canonical_entity",
        ["aliases"],
        unique=False,
        postgresql_using="gin",
    )

    op.create_table(
        "clause_entity",
        sa.Column("clause_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("clause_id", "entity_id", "span_start", name="pk_clause_entity"),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["canonical_entity.id"],
            name="fk_clause_entity_entity_id_canonical_entity",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("span_start >= 0", name="ck_clause_entity_span_start"),
        sa.CheckConstraint("span_end > span_start", name="ck_clause_entity_span_end"),
        comment=(
            "Entity mentions per clause with character spans. clause_id has no foreign key "
            "yet: the clause table arrives with a later migration, which adds it."
        ),
    )
    op.create_index("ix_clause_entity_entity", "clause_entity", ["entity_id"], unique=False)

    op.create_table(
        "rule_relation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("from_rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("relation", sa.String(length=24), nullable=False),
        sa.Column("to_kind", sa.String(length=16), nullable=False),
        sa.Column("to_ref", sa.Text(), nullable=False),
        sa.Column("to_entity_id", sa.Uuid(), nullable=True),
        sa.Column("clause_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rule_relation"),
        sa.ForeignKeyConstraint(
            ["to_entity_id"],
            ["canonical_entity.id"],
            name="fk_rule_relation_to_entity_id_canonical_entity",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in_list("relation", RELATION_KINDS), name="ck_rule_relation_relation"),
        sa.CheckConstraint(_in_list("to_kind", TARGET_KINDS), name="ck_rule_relation_to_kind"),
        sa.CheckConstraint(
            "relation NOT IN ('supersedes', 'extends_deadline') OR to_kind = 'rule_version'",
            name="ck_rule_relation_pairing",
        ),
        sa.CheckConstraint(
            "(to_kind = 'rule_version') = (to_entity_id IS NULL)",
            name="ck_rule_relation_target_entity",
        ),
        sa.CheckConstraint(
            "NOT (to_kind = 'rule_version' AND to_ref = from_rule_version_id::text)",
            name="ck_rule_relation_not_self",
        ),
        sa.UniqueConstraint(
            "from_rule_version_id",
            "relation",
            "to_kind",
            "to_ref",
            "clause_id",
            name="uq_rule_relation_edge",
        ),
        comment=(
            "Typed relations between rule versions and entities; clause_id is the evidence. "
            "from_rule_version_id and clause_id have no foreign keys yet: the rule_version "
            "and clause tables arrive with a later migration, which adds them."
        ),
    )
    op.create_index(
        "ix_rule_relation_target", "rule_relation", ["relation", "to_ref"], unique=False
    )
    op.create_index(
        "ix_rule_relation_source", "rule_relation", ["from_rule_version_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_rule_relation_source", table_name="rule_relation")
    op.drop_index("ix_rule_relation_target", table_name="rule_relation")
    op.drop_table("rule_relation")
    op.drop_index("ix_clause_entity_entity", table_name="clause_entity")
    op.drop_table("clause_entity")
    op.drop_index("ix_canonical_entity_aliases", table_name="canonical_entity")
    op.drop_table("canonical_entity")
