"""source, raw_document and crawl_run tables, plus the outbox table

Revision ID: 0001
Revises:
Create Date: 2026-10-06

Hand-written; mirrors pipeline.infrastructure.models. Table names are unqualified and land in the
schema at the front of search_path (CW_DB_SCHEMA, ``pipeline``). Sources, fetched documents and
crawl runs are regulatory data shared by every tenant: the ``pipeline`` schema is in the global
group of infra/scripts/migration_lint.toml, so the tables have no tenant_id and no row-level
security. A raw document never changes but for its status and is never deleted: a trigger
refuses the rest. The outbox table comes from py-common (ADR-005); the pipeline consumes no event
yet, so there is no processed-event table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.outbox import create_outbox_table, drop_outbox_table

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_KEY = "^[a-z][a-z0-9_]{0,62}$"
ADAPTER_TYPE = "^[a-z][a-z0-9_]{0,39}$"
DOCUMENT_STATUSES = ("discovered", "parsed", "failed", "irrelevant")
CRAWL_STATUSES = ("running", "completed", "failed")
COUNTS = ("listed", "stored", "duplicates", "failed")
MAX_ERROR_CHARS = 2000

RAW_DOCUMENT_GUARD = """
CREATE FUNCTION pipeline_raw_document_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'raw_document rows are never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.id, NEW.source_key, NEW.source_url, NEW.external_ref, NEW.fetched_at,
      NEW.published_on, NEW.content_type, NEW.size, NEW.sha256, NEW.storage_key, NEW.title)
     IS DISTINCT FROM
     (OLD.id, OLD.source_key, OLD.source_url, OLD.external_ref, OLD.fetched_at,
      OLD.published_on, OLD.content_type, OLD.size, OLD.sha256, OLD.storage_key, OLD.title) THEN
    RAISE EXCEPTION 'a raw_document row changes only its status'
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
        "source",
        sa.Column("key", sa.String(length=63), nullable=False),
        sa.Column("adapter_type", sa.String(length=40), nullable=False),
        sa.Column(
            "parameters",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cadence", sa.Interval(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("paused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("watermark", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("last_error", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_source"),
        sa.CheckConstraint(f"key ~ '{SOURCE_KEY}'", name="ck_source_key"),
        sa.CheckConstraint(f"adapter_type ~ '{ADAPTER_TYPE}'", name="ck_source_adapter_type"),
        sa.CheckConstraint("jsonb_typeof(parameters) = 'object'", name="ck_source_parameters"),
        sa.CheckConstraint(
            "watermark IS NULL OR jsonb_typeof(watermark) = 'object'", name="ck_source_watermark"
        ),
        sa.CheckConstraint("cadence >= interval '1 minute'", name="ck_source_cadence"),
        sa.CheckConstraint(
            f"length(last_error) <= {MAX_ERROR_CHARS}", name="ck_source_last_error_length"
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_source_updated"),
        comment=(
            "The sources the pipeline reads: the adapter type with its parameters, the cadence, "
            "whether it is enabled or paused, and how far the last crawl got. Regulatory data, "
            "no tenant."
        ),
    )
    op.create_table(
        "raw_document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=63), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("external_ref", sa.Text(), server_default="", nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="discovered", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_raw_document"),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["source.key"],
            name="fk_raw_document_source_key_source",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("sha256", name="uq_raw_document_sha256"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_raw_document_sha256"),
        sa.CheckConstraint(
            "id = CAST(substr(sha256, 1, 32) AS uuid)", name="ck_raw_document_id_from_sha256"
        ),
        sa.CheckConstraint("size > 0", name="ck_raw_document_size"),
        sa.CheckConstraint("length(source_url) > 0", name="ck_raw_document_source_url"),
        sa.CheckConstraint("length(content_type) > 0", name="ck_raw_document_content_type"),
        sa.CheckConstraint("length(storage_key) > 0", name="ck_raw_document_storage_key"),
        sa.CheckConstraint(_in_list("status", DOCUMENT_STATUSES), name="ck_raw_document_status"),
        comment=(
            "Fetched regulator files, one row per content: the id is the first half of the "
            "SHA-256 of the bytes, which are in the raw store under storage_key. Only status "
            "ever changes, and no row is deleted (pipeline_raw_document_guard). Regulatory data, "
            "no tenant."
        ),
    )
    op.create_index(
        "ix_raw_document_source_published", "raw_document", ["source_key", "published_on"]
    )
    op.create_index("ix_raw_document_status_fetched", "raw_document", ["status", "fetched_at"])
    op.execute(RAW_DOCUMENT_GUARD)
    op.execute(
        "CREATE TRIGGER tr_raw_document_guard BEFORE UPDATE OR DELETE ON raw_document"
        " FOR EACH ROW EXECUTE FUNCTION pipeline_raw_document_guard()"
    )
    op.create_table(
        "crawl_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=63), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        *(
            sa.Column(count, sa.Integer(), server_default=sa.text("0"), nullable=False)
            for count in COUNTS
        ),
        sa.Column("error", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_crawl_run"),
        sa.ForeignKeyConstraint(
            ["source_key"],
            ["source.key"],
            name="fk_crawl_run_source_key_source",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in_list("status", CRAWL_STATUSES), name="ck_crawl_run_status"),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="ck_crawl_run_finished"
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="ck_crawl_run_order"
        ),
        sa.CheckConstraint(
            " AND ".join(f"{count} >= 0" for count in COUNTS), name="ck_crawl_run_counts"
        ),
        sa.CheckConstraint("(status = 'failed') = (length(error) > 0)", name="ck_crawl_run_error"),
        sa.CheckConstraint(f"length(error) <= {MAX_ERROR_CHARS}", name="ck_crawl_run_error_length"),
        comment=(
            "One crawl of one source: when it ran, what it found and how it ended. Regulatory "
            "data, no tenant."
        ),
    )
    op.create_index("ix_crawl_run_source_started", "crawl_run", ["source_key", "started_at"])
    create_outbox_table(op)


def downgrade() -> None:
    drop_outbox_table(op)
    op.drop_index("ix_crawl_run_source_started", table_name="crawl_run")
    op.drop_table("crawl_run")
    op.execute("DROP TRIGGER tr_raw_document_guard ON raw_document")
    op.execute("DROP FUNCTION pipeline_raw_document_guard()")
    op.drop_index("ix_raw_document_status_fetched", table_name="raw_document")
    op.drop_index("ix_raw_document_source_published", table_name="raw_document")
    op.drop_table("raw_document")
    op.drop_table("source")
