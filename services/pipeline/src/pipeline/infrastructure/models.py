"""SQLAlchemy rows of the pipeline service; mirrored by the migrations.

Sources, fetched documents and crawl runs are regulatory data shared by every tenant (the
``pipeline`` schema is in the global group of infra/scripts/migration_lint.toml), so the tables
carry no tenant_id and no row-level security.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Interval,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from pipeline.domain.crawl import COUNTS, CrawlStatus
from pipeline.domain.raw_documents import (
    MAX_CONTENT_TYPE_CHARS,
    MAX_STORAGE_KEY_CHARS,
    DocumentStatus,
)
from pipeline.domain.sources import ADAPTER_TYPE_PATTERN, MAX_ERROR_CHARS, SOURCE_KEY_PATTERN

DOCUMENT_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in DocumentStatus)
CRAWL_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in CrawlStatus)
SOURCE_COMMENT: Final = (
    "The sources the pipeline reads: the adapter type with its parameters, the cadence, whether "
    "it is enabled or paused, and how far the last crawl got. Regulatory data, no tenant."
)
RAW_DOCUMENT_COMMENT: Final = (
    "Fetched regulator files, one row per content: the id is the first half of the SHA-256 of "
    "the bytes, which are in the raw store under storage_key. Only status ever changes, and "
    "no row is deleted (pipeline_raw_document_guard). Regulatory data, no tenant."
)
CRAWL_RUN_COMMENT: Final = (
    "One crawl of one source: when it ran, what it found and how it ended. Regulatory data, "
    "no tenant."
)


def sql_in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    pass


class SourceRow(Base):
    __tablename__ = "source"
    __table_args__ = (
        PrimaryKeyConstraint("key", name="pk_source"),
        CheckConstraint(f"key ~ '{SOURCE_KEY_PATTERN}'", name="ck_source_key"),
        CheckConstraint(f"adapter_type ~ '{ADAPTER_TYPE_PATTERN}'", name="ck_source_adapter_type"),
        CheckConstraint("jsonb_typeof(parameters) = 'object'", name="ck_source_parameters"),
        CheckConstraint(
            "watermark IS NULL OR jsonb_typeof(watermark) = 'object'", name="ck_source_watermark"
        ),
        CheckConstraint("cadence >= interval '1 minute'", name="ck_source_cadence"),
        CheckConstraint(
            f"length(last_error) <= {MAX_ERROR_CHARS}", name="ck_source_last_error_length"
        ),
        CheckConstraint("updated_at >= created_at", name="ck_source_updated"),
        {"comment": SOURCE_COMMENT},
    )

    key: Mapped[str] = mapped_column(String(63))
    adapter_type: Mapped[str] = mapped_column(String(40))
    parameters: Mapped[dict[str, object]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    cadence: Mapped[timedelta] = mapped_column(Interval)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    paused: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    watermark: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    last_error: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RawDocumentRow(Base):
    __tablename__ = "raw_document"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_raw_document"),
        ForeignKeyConstraint(
            ["source_key"],
            ["source.key"],
            name="fk_raw_document_source_key_source",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("sha256", name="uq_raw_document_sha256"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_raw_document_sha256"),
        CheckConstraint(
            "id = CAST(substr(sha256, 1, 32) AS uuid)", name="ck_raw_document_id_from_sha256"
        ),
        CheckConstraint("size > 0", name="ck_raw_document_size"),
        CheckConstraint("length(source_url) > 0", name="ck_raw_document_source_url"),
        CheckConstraint("length(content_type) > 0", name="ck_raw_document_content_type"),
        CheckConstraint("length(storage_key) > 0", name="ck_raw_document_storage_key"),
        CheckConstraint(sql_in_list("status", DOCUMENT_STATUSES), name="ck_raw_document_status"),
        Index("ix_raw_document_source_published", "source_key", "published_on"),
        Index("ix_raw_document_status_fetched", "status", "fetched_at"),
        {"comment": RAW_DOCUMENT_COMMENT},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_key: Mapped[str] = mapped_column(String(63))
    source_url: Mapped[str] = mapped_column(Text)
    external_ref: Mapped[str] = mapped_column(Text, server_default="")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_on: Mapped[date | None] = mapped_column(Date)
    content_type: Mapped[str] = mapped_column(String(MAX_CONTENT_TYPE_CHARS))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(MAX_STORAGE_KEY_CHARS))
    title: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(String(16), server_default=DocumentStatus.DISCOVERED.value)


class CrawlRunRow(Base):
    __tablename__ = "crawl_run"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_crawl_run"),
        ForeignKeyConstraint(
            ["source_key"],
            ["source.key"],
            name="fk_crawl_run_source_key_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(sql_in_list("status", CRAWL_STATUSES), name="ck_crawl_run_status"),
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="ck_crawl_run_finished"
        ),
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="ck_crawl_run_order"
        ),
        CheckConstraint(
            " AND ".join(f"{count} >= 0" for count in COUNTS), name="ck_crawl_run_counts"
        ),
        CheckConstraint("(status = 'failed') = (length(error) > 0)", name="ck_crawl_run_error"),
        CheckConstraint(f"length(error) <= {MAX_ERROR_CHARS}", name="ck_crawl_run_error_length"),
        Index("ix_crawl_run_source_started", "source_key", "started_at"),
        {"comment": CRAWL_RUN_COMMENT},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_key: Mapped[str] = mapped_column(String(63))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    listed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    stored: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    duplicates: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    failed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error: Mapped[str] = mapped_column(Text, server_default="")
