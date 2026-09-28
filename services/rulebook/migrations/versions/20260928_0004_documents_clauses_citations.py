"""document, clause and citation tables; foreign keys for the knowledge tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28

Hand-written; mirrors rulebook.infrastructure.models. Regulator documents and their clauses land
here, so the knowledge tables finally point at real rows: clause_entity.clause_id and
rule_relation.clause_id reference clause, rule_relation.from_rule_version_id references
rule_version, and a relation to another rule version names it in the new to_rule_version_id.

Expand-only. The new foreign keys need clause_entity and rule_relation to be empty, which they
are everywhere because nothing writes them before this migration; the upgrade checks it and
stops with a clear message otherwise. Fly runs ``alembic upgrade head`` as the release command,
so the previous image never sees a half-migrated schema.

Documents and clauses are append-only (Architecture Reference, section 3.3): a trigger rejects
UPDATE and DELETE on both. A citation's identity is fixed once written; only its verification
may be set, and only one way.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_TYPES = ("notification", "circular", "press_release", "act_amendment")
MENTION_METHODS = ("grammar", "model", "analyst")
PARSER_VERSION = "^[a-z][a-z0-9_-]*@[0-9]+$"
CLAUSE_REF = "^(?:[a-z]{2,3}\\.)?p[1-9][0-9]{0,3}$"

APPEND_ONLY = """
CREATE FUNCTION rulebook_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'restrict_violation';
END
$$
"""

CITATION_GUARD = """
CREATE FUNCTION rulebook_citation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'citation is append-only' USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.id, NEW.rule_version_id, NEW.clause_id, NEW.quote, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.rule_version_id, OLD.clause_id, OLD.quote, OLD.created_at)
     OR (OLD.verified AND NOT NEW.verified) THEN
    RAISE EXCEPTION 'citation identity is immutable and verification is one-way'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END
$$
"""


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT (SELECT count(*) FROM clause_entity) + (SELECT count(*) FROM rule_relation)"
            )
        )
        .scalar_one()
    )
    if rows:
        raise RuntimeError(
            "0004 adds foreign keys to clause_entity and rule_relation and expects both empty; "
            f"found {rows} rows"
        )

    op.create_table(
        "document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("regulator", sa.String(length=40), nullable=False),
        sa.Column("doc_type", sa.String(length=16), nullable=False),
        sa.Column("external_ref", sa.Text(), server_default="", nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("media_type", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_uri", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document"),
        sa.UniqueConstraint("sha256", name="uq_document_sha256"),
        sa.CheckConstraint(_in_list("doc_type", DOCUMENT_TYPES), name="ck_document_doc_type"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_sha256"),
        sa.CheckConstraint(
            "replace(id::text, '-', '') = left(sha256, 32)", name="ck_document_id_from_sha256"
        ),
        sa.CheckConstraint(
            f"parser_version ~ '{PARSER_VERSION}'", name="ck_document_parser_version"
        ),
        comment=(
            "Regulator documents, one row per distinct file; id is the first 32 hex digits of "
            "sha256. Append-only: a corrected document is a new row, and a re-parse that gives "
            "different clauses is rejected, not applied."
        ),
    )
    op.create_index("ix_document_source_published", "document", ["source_id", "published_at"])

    op.create_table(
        "clause",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("clause_ref", sa.String(length=40), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_clause"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_clause_document_id_document",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("document_id", "clause_ref", name="uq_clause_document_id_clause_ref"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_clause_document_id_ordinal"),
        sa.CheckConstraint(f"clause_ref ~ '{CLAUSE_REF}'", name="ck_clause_clause_ref"),
        sa.CheckConstraint("ordinal >= 1", name="ck_clause_ordinal"),
        sa.CheckConstraint("page IS NULL OR page >= 1", name="ck_clause_page"),
        sa.CheckConstraint("length(text) > 0", name="ck_clause_text"),
        comment=(
            "Clauses of a document in order. id is clause_id_for(document id, clause_ref) from "
            "the kernel, which clause_entity, rule_relation, citation and the vector index "
            "share. Mention spans are code-point offsets into text. Append-only."
        ),
    )

    op.create_table(
        "citation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_version_id", sa.Uuid(), nullable=False),
        sa.Column("clause_id", sa.Uuid(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("match_score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_citation"),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name="fk_citation_rule_version_id_rule_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["clause_id"], ["clause.id"], name="fk_citation_clause_id_clause", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("length(quote) BETWEEN 1 AND 400", name="ck_citation_quote"),
        sa.CheckConstraint(
            "match_score IS NULL OR match_score BETWEEN 0 AND 1", name="ck_citation_match_score"
        ),
        sa.CheckConstraint(
            "verified = (verified_at IS NOT NULL)"
            " AND (NOT verified OR (match_score IS NOT NULL AND match_score >= 0.85))",
            name="ck_citation_verified",
        ),
        comment=(
            "Citations from rule versions to clauses (ADR-006). Every citation of a version "
            "must be verified before the version is published. Identity columns are fixed; "
            "only the one-way verification (verified, match_score, verified_at) may be set."
        ),
    )
    op.create_index("ix_citation_rule_version", "citation", ["rule_version_id"])
    op.create_index("ix_citation_clause", "citation", ["clause_id"])

    op.execute(APPEND_ONLY)
    op.execute(CITATION_GUARD)
    for table in ("document", "clause"):
        op.execute(
            f"CREATE TRIGGER tr_{table}_append_only BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION rulebook_append_only()"
        )
    op.execute(
        "CREATE TRIGGER tr_citation_guard BEFORE UPDATE OR DELETE ON citation"
        " FOR EACH ROW EXECUTE FUNCTION rulebook_citation_guard()"
    )

    op.add_column(
        "clause_entity",
        sa.Column("method", sa.String(length=16), server_default="grammar", nullable=False),
    )
    op.add_column(
        "clause_entity",
        sa.Column("extractor", sa.String(length=60), server_default="", nullable=False),
    )
    op.add_column(
        "clause_entity",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_clause_entity_method", "clause_entity", _in_list("method", MENTION_METHODS)
    )
    op.create_foreign_key(
        "fk_clause_entity_clause_id_clause",
        "clause_entity",
        "clause",
        ["clause_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table_comment(
        "clause_entity",
        "Entity mentions per clause with half-open code-point spans into clause.text: the "
        "text-to-fact half of the index. method says who found the mention.",
    )

    op.add_column("rule_relation", sa.Column("to_rule_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_rule_relation_from_rule_version_id_rule_version",
        "rule_relation",
        "rule_version",
        ["from_rule_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_rule_relation_to_rule_version_id_rule_version",
        "rule_relation",
        "rule_version",
        ["to_rule_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_rule_relation_clause_id_clause",
        "rule_relation",
        "clause",
        ["clause_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_rule_relation_target_version",
        "rule_relation",
        "((to_kind = 'rule_version') = (to_rule_version_id IS NOT NULL))"
        " AND (to_rule_version_id IS NULL OR to_ref = to_rule_version_id::text)",
    )
    op.create_index("ix_rule_relation_to_rule_version", "rule_relation", ["to_rule_version_id"])
    op.create_index("ix_rule_relation_clause", "rule_relation", ["clause_id"])
    op.create_table_comment(
        "rule_relation",
        "Typed relations from a rule version to a rule version (to_rule_version_id) or an "
        "entity (to_entity_id); clause_id is the evidence, the fact-to-text half of the index.",
    )
    op.execute(
        "COMMENT ON COLUMN canonical_entity.aliases IS 'Alternative names of the same type, "
        "each already normalised with normalise_name, that resolve to this entity'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON COLUMN canonical_entity.aliases IS NULL")
    op.create_table_comment(
        "rule_relation",
        "Typed relations between rule versions and entities; clause_id is the evidence. "
        "from_rule_version_id and clause_id have no foreign keys yet: the rule_version "
        "and clause tables arrive with a later migration, which adds them.",
    )
    op.drop_index("ix_rule_relation_clause", table_name="rule_relation")
    op.drop_index("ix_rule_relation_to_rule_version", table_name="rule_relation")
    op.drop_constraint("ck_rule_relation_target_version", "rule_relation", type_="check")
    op.drop_constraint("fk_rule_relation_clause_id_clause", "rule_relation", type_="foreignkey")
    op.drop_constraint(
        "fk_rule_relation_to_rule_version_id_rule_version", "rule_relation", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_rule_relation_from_rule_version_id_rule_version", "rule_relation", type_="foreignkey"
    )
    op.drop_column("rule_relation", "to_rule_version_id")

    op.create_table_comment(
        "clause_entity",
        "Entity mentions per clause with character spans. clause_id has no foreign key "
        "yet: the clause table arrives with a later migration, which adds it.",
    )
    op.drop_constraint("fk_clause_entity_clause_id_clause", "clause_entity", type_="foreignkey")
    op.drop_constraint("ck_clause_entity_method", "clause_entity", type_="check")
    op.drop_column("clause_entity", "created_at")
    op.drop_column("clause_entity", "extractor")
    op.drop_column("clause_entity", "method")

    op.drop_index("ix_citation_clause", table_name="citation")
    op.drop_index("ix_citation_rule_version", table_name="citation")
    op.drop_table("citation")
    op.drop_table("clause")
    op.drop_index("ix_document_source_published", table_name="document")
    op.drop_table("document")
    op.execute("DROP FUNCTION rulebook_citation_guard()")
    op.execute("DROP FUNCTION rulebook_append_only()")
