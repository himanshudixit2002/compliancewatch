"""document_classification, rule_extraction, and the statuses of a classified document

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06

Hand-written; mirrors pipeline.infrastructure.models. Expand only, so the image before it keeps
working:

- ``raw_document.status`` admits ``classified`` (on its way to the rule extraction), ``triage``
  (held for a person), ``reference`` (a press release or a statute: registered, nothing
  extracted) and ``extracted``. The guard trigger is unchanged: a row still changes only its
  status and its parse, and its ``doc_type`` stays the uploader's.
- ``document_classification``: one row per classified document, its type, relevance, confidence
  and reasons, by the detector or a person's triage (who, and the task).
- ``rule_extraction``: one row per document and extraction prompt version, the candidate the
  model gave (or that its answer was not one) with the validators' issues; its
  rule.candidate.created is written in the same transaction. A trigger keeps it as written.

Regulatory data, no tenant: ``pipeline`` is a global schema in infra/scripts/migration_lint.toml.
The downgrade moves the documents of the new statuses back to ``parsed``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = ("discovered", "parsed", "failed", "irrelevant")
NEW_STATUSES = ("classified", "triage", "reference", "extracted")
DOCUMENT_TYPES = ("notification", "circular", "press_release", "act_amendment", "statute")
RULE_KINDS = ("notification", "circular", "act_amendment")
RELEVANCES = ("relevant", "irrelevant")
CONFIDENCES = ("certain", "default", "conflict")
OUTCOMES = ("extracted", "unparseable")
PROMPT_VERSION = "^[a-z][a-z0-9_.-]*@[0-9]+$"
MAX_REASONS = 8
MAX_ANSWER_CHARS = 20_000

EXTRACTION_GUARD = """
CREATE FUNCTION pipeline_rule_extraction_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'a rule_extraction row is kept as written' USING ERRCODE = 'restrict_violation';
END
$$
"""


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.drop_constraint("ck_raw_document_status", "raw_document", type_="check")
    op.create_check_constraint(
        "ck_raw_document_status", "raw_document", _in_list("status", OLD_STATUSES + NEW_STATUSES)
    )
    op.create_table(
        "document_classification",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", sa.String(length=16), nullable=False),
        sa.Column("relevance", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("reasons", postgresql.JSONB(), nullable=False),
        sa.Column("classifier", sa.String(length=40), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("document_id", name="pk_document_classification"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["raw_document.id"],
            name="fk_document_classification_document_id_raw_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["pipeline_task.id"],
            name="fk_document_classification_task_id_pipeline_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            _in_list("doc_type", DOCUMENT_TYPES), name="ck_document_classification_doc_type"
        ),
        sa.CheckConstraint(
            _in_list("relevance", RELEVANCES), name="ck_document_classification_relevance"
        ),
        sa.CheckConstraint(
            _in_list("confidence", CONFIDENCES), name="ck_document_classification_confidence"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reasons) = 'array' AND jsonb_array_length(reasons) "
            f"BETWEEN 1 AND {MAX_REASONS}",
            name="ck_document_classification_reasons",
        ),
        sa.CheckConstraint("length(classifier) > 0", name="ck_document_classification_classifier"),
        sa.CheckConstraint(
            "decided_by IS NULL OR classifier = 'triage'",
            name="ck_document_classification_decided_by",
        ),
        comment=(
            "How each parsed document was classified: its type, whether it is a regulatory "
            "document, how sure the type is and why, by the detector or a person's triage. "
            "Regulatory data, no tenant."
        ),
    )
    op.create_index("ix_document_classification_task", "document_classification", ["task_id"])
    op.create_table(
        "rule_extraction",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("source_key", sa.String(length=63), nullable=False),
        sa.Column("doc_type", sa.String(length=16), nullable=False),
        sa.Column("regulator", sa.String(length=40), nullable=False),
        sa.Column("fields", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("issues", postgresql.JSONB(), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("answer", sa.Text(), server_default="", nullable=False),
        sa.Column("ontology_version", sa.String(length=40), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("document_id", "prompt_version", name="pk_rule_extraction"),
        sa.UniqueConstraint("candidate_id", name="uq_rule_extraction_candidate_id"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["raw_document.id"],
            name="fk_rule_extraction_document_id_raw_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["source.key"],
            name="fk_rule_extraction_source_key_source",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"prompt_version ~ '{PROMPT_VERSION}'", name="ck_rule_extraction_prompt_version"
        ),
        sa.CheckConstraint(_in_list("outcome", OUTCOMES), name="ck_rule_extraction_outcome"),
        sa.CheckConstraint(_in_list("doc_type", RULE_KINDS), name="ck_rule_extraction_doc_type"),
        sa.CheckConstraint("length(model) > 0", name="ck_rule_extraction_model"),
        sa.CheckConstraint("attempts >= 1", name="ck_rule_extraction_attempts"),
        sa.CheckConstraint(
            "(outcome = 'extracted') = (fields IS NOT NULL) "
            "AND (fields IS NULL OR jsonb_typeof(fields) = 'object')",
            name="ck_rule_extraction_fields",
        ),
        sa.CheckConstraint("jsonb_typeof(issues) = 'array'", name="ck_rule_extraction_issues"),
        sa.CheckConstraint("citation_count >= 0", name="ck_rule_extraction_citation_count"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_rule_extraction_confidence"
        ),
        sa.CheckConstraint(
            "outcome = 'extracted' OR needs_review", name="ck_rule_extraction_review"
        ),
        sa.CheckConstraint(
            f"length(answer) <= {MAX_ANSWER_CHARS}", name="ck_rule_extraction_answer_length"
        ),
        comment=(
            "The rule extraction of each document by each prompt version: the candidate the "
            "model gave, or that its answer was not one, with the validators' issues and the "
            "candidate id its rule.candidate.created names. Kept as written "
            "(pipeline_rule_extraction_guard). Regulatory data, no tenant."
        ),
    )
    op.create_index(
        "ix_rule_extraction_extracted", "rule_extraction", ["extracted_at", "document_id"]
    )
    op.execute(EXTRACTION_GUARD)
    op.execute(
        "CREATE TRIGGER tr_rule_extraction_guard BEFORE UPDATE OR DELETE ON rule_extraction"
        " FOR EACH ROW EXECUTE FUNCTION pipeline_rule_extraction_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER tr_rule_extraction_guard ON rule_extraction")
    op.execute("DROP FUNCTION pipeline_rule_extraction_guard()")
    op.drop_index("ix_rule_extraction_extracted", table_name="rule_extraction")
    op.drop_table("rule_extraction")
    op.drop_index("ix_document_classification_task", table_name="document_classification")
    op.drop_table("document_classification")
    op.execute(
        f"UPDATE raw_document SET status = 'parsed' WHERE {_in_list('status', NEW_STATUSES)}"
    )
    op.drop_constraint("ck_raw_document_status", "raw_document", type_="check")
    op.create_check_constraint(
        "ck_raw_document_status", "raw_document", _in_list("status", OLD_STATUSES)
    )
