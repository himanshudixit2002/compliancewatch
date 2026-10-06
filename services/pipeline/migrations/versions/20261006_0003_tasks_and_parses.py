"""pipeline_task, and the parse of each raw document

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06

Hand-written; mirrors pipeline.infrastructure.models. Expand only, so the image before it keeps
working:

- ``raw_document.parser_version``: the parser of the document's last parse (``pdf@1``,
  ``pdf-tables@1``, ``html@1``, ``html-tables@1``, ``manual@1``), empty before one, as the
  rows stored before this migration are; ``doc_type``: the type an uploader gave, null for the
  source's; ``transcript_key``: where the raw store keeps the analyst's transcript the document
  is parsed from. The guard trigger now freezes ``doc_type`` too: a row changes only its status
  and its parse.
- ``pipeline_task``: work a person does on a stored document, a manual parse or a triage, with at
  most one open task of a kind per document (``uq_pipeline_task_open``). Regulatory data, no
  tenant: ``pipeline`` is a global schema in infra/scripts/migration_lint.toml.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARSER_VERSION = "^[a-z][a-z0-9_-]*@[0-9]+$"
DOCUMENT_TYPES = ("notification", "circular", "press_release", "act_amendment", "statute")
TASK_KINDS = ("manual_parse", "triage")
TASK_STATUSES = ("open", "resolved", "dismissed")
MAX_KEY_CHARS = 1024
MAX_TEXT_CHARS = 2000
RAW_DOCUMENT_COMMENT = (
    "Fetched regulator files, one row per content: the id is the first half of the SHA-256 of "
    "the bytes, which are in the raw store under storage_key. Only the status and the parse "
    "(parser_version, transcript_key) ever change, and no row is deleted "
    "(pipeline_raw_document_guard). Regulatory data, no tenant."
)
OLD_RAW_DOCUMENT_COMMENT = (
    "Fetched regulator files, one row per content: the id is the first half of the SHA-256 of "
    "the bytes, which are in the raw store under storage_key. Only status ever changes, and "
    "no row is deleted (pipeline_raw_document_guard). Regulatory data, no tenant."
)

GUARD = """
CREATE OR REPLACE FUNCTION pipeline_raw_document_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'raw_document rows are never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.id, NEW.source_key, NEW.source_url, NEW.external_ref, NEW.fetched_at,
      NEW.published_on, NEW.content_type, NEW.size, NEW.sha256, NEW.storage_key,
      NEW.title{doc_type})
     IS DISTINCT FROM
     (OLD.id, OLD.source_key, OLD.source_url, OLD.external_ref, OLD.fetched_at,
      OLD.published_on, OLD.content_type, OLD.size, OLD.sha256, OLD.storage_key,
      OLD.title{old_doc_type}) THEN
    RAISE EXCEPTION 'a raw_document row changes only its {what}'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END
$$
"""


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def upgrade() -> None:
    op.add_column(
        "raw_document",
        sa.Column("parser_version", sa.String(length=40), server_default="", nullable=False),
    )
    op.add_column("raw_document", sa.Column("doc_type", sa.String(length=16), nullable=True))
    op.add_column(
        "raw_document", sa.Column("transcript_key", sa.String(length=MAX_KEY_CHARS), nullable=True)
    )
    op.create_check_constraint(
        "ck_raw_document_parser_version",
        "raw_document",
        f"parser_version = '' OR parser_version ~ '{PARSER_VERSION}'",
    )
    op.create_check_constraint(
        "ck_raw_document_doc_type",
        "raw_document",
        f"doc_type IS NULL OR {_in_list('doc_type', DOCUMENT_TYPES)}",
    )
    op.create_check_constraint(
        "ck_raw_document_transcript_key",
        "raw_document",
        "transcript_key IS NULL OR length(transcript_key) > 0",
    )
    op.execute(
        GUARD.format(
            doc_type=", NEW.doc_type", old_doc_type=", OLD.doc_type", what="status and parse"
        )
    )
    op.create_table_comment(
        "raw_document", RAW_DOCUMENT_COMMENT, existing_comment=OLD_RAW_DOCUMENT_COMMENT
    )
    op.create_table(
        "pipeline_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=63), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("claimed_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_pipeline_task"),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["raw_document.id"],
            name="fk_pipeline_task_document_id_raw_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["source.key"],
            name="fk_pipeline_task_source_key_source",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in_list("kind", TASK_KINDS), name="ck_pipeline_task_kind"),
        sa.CheckConstraint(_in_list("status", TASK_STATUSES), name="ck_pipeline_task_status"),
        sa.CheckConstraint(
            "(status = 'open') = (resolved_at IS NULL)", name="ck_pipeline_task_resolved"
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= opened_at", name="ck_pipeline_task_order"
        ),
        sa.CheckConstraint(
            "status <> 'open' OR resolved_by IS NULL", name="ck_pipeline_task_open_unresolved"
        ),
        sa.CheckConstraint(
            "resolution IS NULL OR (status = 'resolved' AND jsonb_typeof(resolution) = 'object')",
            name="ck_pipeline_task_resolution",
        ),
        sa.CheckConstraint(
            f"length(reason) <= {MAX_TEXT_CHARS}", name="ck_pipeline_task_reason_length"
        ),
        sa.CheckConstraint(
            f"length(note) <= {MAX_TEXT_CHARS}", name="ck_pipeline_task_note_length"
        ),
        comment=(
            "Work a person does on a stored document: a manual parse of one no parser reads, a "
            "triage. At most one open task of a kind per document. Regulatory data, no tenant."
        ),
    )
    op.create_index(
        "uq_pipeline_task_open",
        "pipeline_task",
        ["document_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_pipeline_task_status_kind_opened",
        "pipeline_task",
        ["status", "kind", "opened_at", "id"],
    )
    op.create_index("ix_pipeline_task_document", "pipeline_task", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_task_document", table_name="pipeline_task")
    op.drop_index("ix_pipeline_task_status_kind_opened", table_name="pipeline_task")
    op.drop_index("uq_pipeline_task_open", table_name="pipeline_task")
    op.drop_table("pipeline_task")
    op.execute(GUARD.format(doc_type="", old_doc_type="", what="status"))
    op.create_table_comment(
        "raw_document", OLD_RAW_DOCUMENT_COMMENT, existing_comment=RAW_DOCUMENT_COMMENT
    )
    op.drop_constraint("ck_raw_document_transcript_key", "raw_document", type_="check")
    op.drop_constraint("ck_raw_document_doc_type", "raw_document", type_="check")
    op.drop_constraint("ck_raw_document_parser_version", "raw_document", type_="check")
    op.drop_column("raw_document", "transcript_key")
    op.drop_column("raw_document", "doc_type")
    op.drop_column("raw_document", "parser_version")
