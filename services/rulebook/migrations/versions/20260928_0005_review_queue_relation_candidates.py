"""extraction runs, the entity review queue and relation candidates

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28

Hand-written; mirrors rulebook.infrastructure.models. KAG phase 2 (ADR-017):
- ``extraction_run`` records one run of an extraction stage over a document, including model
  output that could not become a candidate, so nothing the pipeline produced is lost.
- ``entity_review`` holds the mentions alignment could not resolve to exactly one canonical
  entity. An analyst decides them per (entity_type, proposed_name).
- ``relation_candidate`` holds the relations the model proposed for a document before any rule
  version exists for it. An analyst approval turns one into a ``rule_relation`` row, which
  points back at its candidate.

Expand-only: three new tables and one nullable column. Global regulatory data: no tenant, no
row-level security.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
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
RELATION_KINDS = (
    "supersedes",
    "amends",
    "refers_to",
    "exempts",
    "extends_deadline",
    "corrects",
    "withdraws",
)
STAGES = ("mentions", "relations")
OUTCOMES = ("ok", "needs_review", "no_targets", "unparseable", "failed")
REVIEW_REASONS = ("no_match", "ambiguous_alias", "empty_name", "unqualified")
REVIEW_STATUSES = ("open", "resolved", "rejected")
RESOLUTIONS = ("created", "aliased", "matched")
ENTITY_REJECT_REASONS = ("not_an_entity", "wrong_type", "text_artifact", "out_of_scope")
CANDIDATE_STATUSES = ("open", "approved", "rejected")
CANDIDATE_REJECT_REASONS = (
    "wrong_kind",
    "wrong_target",
    "not_in_text",
    "duplicate",
    "out_of_scope",
)
METHODS = ("grammar", "model", "analyst")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.create_table(
        "extraction_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("extractor", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=120), server_default="", nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column(
            "counts", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "issues", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_extraction_run"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_extraction_run_document_id_document",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in_list("stage", STAGES), name="ck_extraction_run_stage"),
        sa.CheckConstraint(_in_list("outcome", OUTCOMES), name="ck_extraction_run_outcome"),
        comment=(
            "One row per document, stage and extractor: counts and run-level issues, including "
            "model output that could not become a candidate. The first write wins."
        ),
    )
    op.create_index("ix_extraction_run_document", "extraction_run", ["document_id"])

    op.create_table(
        "entity_review",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("clause_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("proposed_name", sa.Text(), server_default="", nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("extractor", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("resolution", sa.String(length=16), nullable=True),
        sa.Column("resolved_entity_id", sa.Uuid(), nullable=True),
        sa.Column("reject_reason", sa.String(length=24), nullable=True),
        sa.Column("decided_by", sa.String(length=120), server_default="", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entity_review"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_entity_review_document_id_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["clause_id"],
            ["clause.id"],
            name="fk_entity_review_clause_id_clause",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_entity_id"],
            ["canonical_entity.id"],
            name="fk_entity_review_resolved_entity_id_canonical_entity",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "clause_id",
            "entity_type",
            "span_start",
            name="uq_entity_review_clause_id_entity_type_span_start",
        ),
        sa.CheckConstraint(
            _in_list("entity_type", ENTITY_TYPES), name="ck_entity_review_entity_type"
        ),
        sa.CheckConstraint("span_start >= 0", name="ck_entity_review_span_start"),
        sa.CheckConstraint("span_end > span_start", name="ck_entity_review_span_end"),
        sa.CheckConstraint(_in_list("reason", REVIEW_REASONS), name="ck_entity_review_reason"),
        sa.CheckConstraint(_in_list("status", REVIEW_STATUSES), name="ck_entity_review_status"),
        sa.CheckConstraint(
            f"resolution IS NULL OR {_in_list('resolution', RESOLUTIONS)}",
            name="ck_entity_review_resolution",
        ),
        sa.CheckConstraint(
            f"reject_reason IS NULL OR {_in_list('reject_reason', ENTITY_REJECT_REASONS)}",
            name="ck_entity_review_reject_reason",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND resolution IS NULL AND resolved_entity_id IS NULL"
            " AND reject_reason IS NULL AND decided_at IS NULL)"
            " OR (status = 'resolved' AND resolution IS NOT NULL AND resolved_entity_id IS NOT NULL"
            " AND reject_reason IS NULL AND decided_at IS NOT NULL)"
            " OR (status = 'rejected' AND resolution IS NULL AND resolved_entity_id IS NULL"
            " AND reject_reason IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_entity_review_decision",
        ),
        comment=(
            "Mentions alignment could not resolve to exactly one canonical entity, decided per "
            "(entity_type, proposed_name). Resolving writes clause_entity rows. Global: no "
            "tenant, no row-level security."
        ),
    )
    op.create_index(
        "ix_entity_review_open_group",
        "entity_review",
        ["entity_type", "proposed_name"],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("ix_entity_review_document", "entity_review", ["document_id"])

    op.create_table(
        "relation_candidate",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("relation", sa.String(length=24), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_name", sa.Text(), nullable=False),
        sa.Column("target_clause_id", sa.Uuid(), nullable=False),
        sa.Column("target_span_start", sa.Integer(), nullable=False),
        sa.Column("target_span_end", sa.Integer(), nullable=False),
        sa.Column("target_entity_id", sa.Uuid(), nullable=True),
        sa.Column("target_rule_key", sa.String(length=80), nullable=True),
        sa.Column("target_rule_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_clause_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("quote_score", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("period_label", sa.String(length=16), nullable=True),
        sa.Column("new_due_on", sa.Date(), nullable=True),
        sa.Column("method", sa.String(length=16), server_default="model", nullable=False),
        sa.Column("prompt_version", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=120), server_default="", nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column(
            "issues", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("reject_reason", sa.String(length=24), nullable=True),
        sa.Column("decided_by", sa.String(length=120), server_default="", nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_relation_candidate"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_relation_candidate_document_id_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_clause_id"],
            ["clause.id"],
            name="fk_relation_candidate_target_clause_id_clause",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_clause_id"],
            ["clause.id"],
            name="fk_relation_candidate_evidence_clause_id_clause",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_entity_id"],
            ["canonical_entity.id"],
            name="fk_relation_candidate_target_entity_id_canonical_entity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_rule_id"],
            ["rule.id"],
            name="fk_relation_candidate_target_rule_id_rule",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            _in_list("relation", RELATION_KINDS), name="ck_relation_candidate_relation"
        ),
        sa.CheckConstraint(
            _in_list("target_type", ENTITY_TYPES), name="ck_relation_candidate_target_type"
        ),
        sa.CheckConstraint(
            "target_span_start >= 0 AND target_span_end > target_span_start",
            name="ck_relation_candidate_target_span",
        ),
        sa.CheckConstraint(
            "target_rule_id IS NULL OR target_rule_key IS NOT NULL",
            name="ck_relation_candidate_rule_hint",
        ),
        sa.CheckConstraint(
            "relation = 'extends_deadline' OR (period_label IS NULL AND new_due_on IS NULL)",
            name="ck_relation_candidate_deadline_detail",
        ),
        sa.CheckConstraint(
            "quote_score BETWEEN 0 AND 1 AND confidence BETWEEN 0 AND 1",
            name="ck_relation_candidate_scores",
        ),
        sa.CheckConstraint(
            "length(evidence_quote) BETWEEN 8 AND 400", name="ck_relation_candidate_quote"
        ),
        sa.CheckConstraint(_in_list("method", METHODS), name="ck_relation_candidate_method"),
        sa.CheckConstraint(
            _in_list("status", CANDIDATE_STATUSES), name="ck_relation_candidate_status"
        ),
        sa.CheckConstraint(
            f"reject_reason IS NULL OR {_in_list('reject_reason', CANDIDATE_REJECT_REASONS)}",
            name="ck_relation_candidate_reject_reason",
        ),
        sa.CheckConstraint(
            "(status = 'open' AND decided_at IS NULL AND reject_reason IS NULL)"
            " OR (status = 'approved' AND decided_at IS NOT NULL AND reject_reason IS NULL)"
            " OR (status = 'rejected' AND decided_at IS NOT NULL AND reject_reason IS NOT NULL)",
            name="ck_relation_candidate_decision",
        ),
        comment=(
            "Relations the model proposed for a document before any rule version exists for "
            "it. An analyst approval turns one into a rule_relation row (ADR-006, ADR-017); "
            "period_label and new_due_on feed the obligation service's deadline change."
        ),
    )
    op.create_index("ix_relation_candidate_document", "relation_candidate", ["document_id"])
    op.create_index(
        "ix_relation_candidate_open",
        "relation_candidate",
        ["needs_review", "created_at"],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_relation_candidate_target", "relation_candidate", ["target_type", "target_name"]
    )

    op.add_column("rule_relation", sa.Column("candidate_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_rule_relation_candidate_id_relation_candidate",
        "rule_relation",
        "relation_candidate",
        ["candidate_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_rule_relation_candidate_id", "rule_relation", ["candidate_id"])


def downgrade() -> None:
    op.drop_constraint("uq_rule_relation_candidate_id", "rule_relation", type_="unique")
    op.drop_constraint(
        "fk_rule_relation_candidate_id_relation_candidate", "rule_relation", type_="foreignkey"
    )
    op.drop_column("rule_relation", "candidate_id")
    op.drop_index("ix_relation_candidate_target", table_name="relation_candidate")
    op.drop_index("ix_relation_candidate_open", table_name="relation_candidate")
    op.drop_index("ix_relation_candidate_document", table_name="relation_candidate")
    op.drop_table("relation_candidate")
    op.drop_index("ix_entity_review_document", table_name="entity_review")
    op.drop_index("ix_entity_review_open_group", table_name="entity_review")
    op.drop_table("entity_review")
    op.drop_index("ix_extraction_run_document", table_name="extraction_run")
    op.drop_table("extraction_run")
