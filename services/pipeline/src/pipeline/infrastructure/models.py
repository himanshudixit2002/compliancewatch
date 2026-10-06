"""SQLAlchemy rows of the pipeline service; mirrored by the migrations.

Sources, fetched documents, crawl runs, the tasks people work on the documents, their
classifications and their rule extractions are regulatory data shared by every tenant (the
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
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Interval,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from domain_kernel.documents import PARSER_VERSION_PATTERN, DocumentType
from pipeline.domain.classification import (
    MAX_REASONS,
    RULE_KINDS,
    Relevance,
    TypeConfidence,
)
from pipeline.domain.crawl import COUNTS, CrawlStatus
from pipeline.domain.extraction import (
    MAX_ANSWER_CHARS,
    PROMPT_VERSION_PATTERN,
    ExtractionOutcome,
)
from pipeline.domain.raw_documents import (
    MAX_CONTENT_TYPE_CHARS,
    MAX_STORAGE_KEY_CHARS,
    DocumentStatus,
)
from pipeline.domain.sources import (
    ADAPTER_TYPE_PATTERN,
    MAX_ERROR_CHARS,
    MAX_NAME_CHARS,
    SOURCE_KEY_PATTERN,
)
from pipeline.domain.tasks import MAX_NOTE_CHARS, MAX_REASON_CHARS, TaskKind, TaskStatus

DOCUMENT_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in DocumentStatus)
DOCUMENT_TYPES: Final[tuple[str, ...]] = tuple(kind.value for kind in DocumentType)
CRAWL_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in CrawlStatus)
TASK_KINDS: Final[tuple[str, ...]] = tuple(kind.value for kind in TaskKind)
TASK_STATUSES: Final[tuple[str, ...]] = tuple(status.value for status in TaskStatus)
RELEVANCES: Final[tuple[str, ...]] = tuple(relevance.value for relevance in Relevance)
CONFIDENCES: Final[tuple[str, ...]] = tuple(confidence.value for confidence in TypeConfidence)
OUTCOMES: Final[tuple[str, ...]] = tuple(outcome.value for outcome in ExtractionOutcome)
SOURCE_COMMENT: Final = (
    "The sources the pipeline reads: the adapter type with its parameters, the cadence, whether "
    "it is enabled or paused, and how far the last crawl got. Regulatory data, no tenant."
)
RAW_DOCUMENT_COMMENT: Final = (
    "Fetched regulator files, one row per content: the id is the first half of the SHA-256 of "
    "the bytes, which are in the raw store under storage_key. Only the status and the parse "
    "(parser_version, transcript_key) ever change, and no row is deleted "
    "(pipeline_raw_document_guard). Regulatory data, no tenant."
)
TASK_COMMENT: Final = (
    "Work a person does on a stored document: a manual parse of one no parser reads, a triage. "
    "At most one open task of a kind per document. Regulatory data, no tenant."
)
CLASSIFICATION_COMMENT: Final = (
    "How each parsed document was classified: its type, whether it is a regulatory document, "
    "how sure the type is and why, by the detector or a person's triage. Regulatory data, no "
    "tenant."
)
EXTRACTION_COMMENT: Final = (
    "The rule extraction of each document by each prompt version: the candidate the model gave, "
    "or that its answer was not one, with the validators' issues and the candidate id its "
    "rule.candidate.created names. Kept as written (pipeline_rule_extraction_guard). Regulatory "
    "data, no tenant."
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
        CheckConstraint(f"length(name) <= {MAX_NAME_CHARS}", name="ck_source_name_length"),
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
    name: Mapped[str] = mapped_column(Text, server_default="")


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
        CheckConstraint(
            f"parser_version = '' OR parser_version ~ '{PARSER_VERSION_PATTERN}'",
            name="ck_raw_document_parser_version",
        ),
        CheckConstraint(
            f"doc_type IS NULL OR {sql_in_list('doc_type', DOCUMENT_TYPES)}",
            name="ck_raw_document_doc_type",
        ),
        CheckConstraint(
            "transcript_key IS NULL OR length(transcript_key) > 0",
            name="ck_raw_document_transcript_key",
        ),
        Index("ix_raw_document_source_published", "source_key", "published_on"),
        Index("ix_raw_document_status_fetched", "status", "fetched_at"),
        Index("ix_raw_document_source_url", "source_key", "source_url"),
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
    parser_version: Mapped[str] = mapped_column(String(40), server_default="")
    doc_type: Mapped[str | None] = mapped_column(String(16))
    transcript_key: Mapped[str | None] = mapped_column(String(MAX_STORAGE_KEY_CHARS))


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


class PipelineTaskRow(Base):
    __tablename__ = "pipeline_task"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_pipeline_task"),
        ForeignKeyConstraint(
            ["document_id"],
            ["raw_document.id"],
            name="fk_pipeline_task_document_id_raw_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_key"],
            ["source.key"],
            name="fk_pipeline_task_source_key_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(sql_in_list("kind", TASK_KINDS), name="ck_pipeline_task_kind"),
        CheckConstraint(sql_in_list("status", TASK_STATUSES), name="ck_pipeline_task_status"),
        CheckConstraint(
            "(status = 'open') = (resolved_at IS NULL)", name="ck_pipeline_task_resolved"
        ),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= opened_at", name="ck_pipeline_task_order"
        ),
        CheckConstraint(
            "status <> 'open' OR resolved_by IS NULL", name="ck_pipeline_task_open_unresolved"
        ),
        CheckConstraint(
            "resolution IS NULL OR (status = 'resolved' AND jsonb_typeof(resolution) = 'object')",
            name="ck_pipeline_task_resolution",
        ),
        CheckConstraint(
            f"length(reason) <= {MAX_REASON_CHARS}", name="ck_pipeline_task_reason_length"
        ),
        CheckConstraint(f"length(note) <= {MAX_NOTE_CHARS}", name="ck_pipeline_task_note_length"),
        Index(
            "uq_pipeline_task_open",
            "document_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_pipeline_task_status_kind_opened", "status", "kind", "opened_at", "id"),
        Index("ix_pipeline_task_document", "document_id"),
        {"comment": TASK_COMMENT},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(16))
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_key: Mapped[str] = mapped_column(String(63))
    status: Mapped[str] = mapped_column(String(16), server_default=TaskStatus.OPEN.value)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text, server_default="")
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    note: Mapped[str] = mapped_column(Text, server_default="")


class DocumentClassificationRow(Base):
    __tablename__ = "document_classification"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", name="pk_document_classification"),
        ForeignKeyConstraint(
            ["document_id"],
            ["raw_document.id"],
            name="fk_document_classification_document_id_raw_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id"],
            ["pipeline_task.id"],
            name="fk_document_classification_task_id_pipeline_task",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            sql_in_list("doc_type", DOCUMENT_TYPES), name="ck_document_classification_doc_type"
        ),
        CheckConstraint(
            sql_in_list("relevance", RELEVANCES), name="ck_document_classification_relevance"
        ),
        CheckConstraint(
            sql_in_list("confidence", CONFIDENCES), name="ck_document_classification_confidence"
        ),
        CheckConstraint(
            "jsonb_typeof(reasons) = 'array' AND jsonb_array_length(reasons) "
            f"BETWEEN 1 AND {MAX_REASONS}",
            name="ck_document_classification_reasons",
        ),
        CheckConstraint("length(classifier) > 0", name="ck_document_classification_classifier"),
        CheckConstraint(
            "decided_by IS NULL OR classifier = 'triage'",
            name="ck_document_classification_decided_by",
        ),
        Index("ix_document_classification_task", "task_id"),
        {"comment": CLASSIFICATION_COMMENT},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    doc_type: Mapped[str] = mapped_column(String(16))
    relevance: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[str] = mapped_column(String(16))
    reasons: Mapped[list[str]] = mapped_column(JSONB)
    classifier: Mapped[str] = mapped_column(String(40))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RuleExtractionRow(Base):
    __tablename__ = "rule_extraction"
    __table_args__ = (
        PrimaryKeyConstraint("document_id", "prompt_version", name="pk_rule_extraction"),
        UniqueConstraint("candidate_id", name="uq_rule_extraction_candidate_id"),
        ForeignKeyConstraint(
            ["document_id"],
            ["raw_document.id"],
            name="fk_rule_extraction_document_id_raw_document",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_key"],
            ["source.key"],
            name="fk_rule_extraction_source_key_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"prompt_version ~ '{PROMPT_VERSION_PATTERN}'",
            name="ck_rule_extraction_prompt_version",
        ),
        CheckConstraint(sql_in_list("outcome", OUTCOMES), name="ck_rule_extraction_outcome"),
        CheckConstraint(sql_in_list("doc_type", RULE_KINDS), name="ck_rule_extraction_doc_type"),
        CheckConstraint("length(model) > 0", name="ck_rule_extraction_model"),
        CheckConstraint("attempts >= 1", name="ck_rule_extraction_attempts"),
        CheckConstraint(
            "(outcome = 'extracted') = (fields IS NOT NULL) "
            "AND (fields IS NULL OR jsonb_typeof(fields) = 'object')",
            name="ck_rule_extraction_fields",
        ),
        CheckConstraint("jsonb_typeof(issues) = 'array'", name="ck_rule_extraction_issues"),
        CheckConstraint("citation_count >= 0", name="ck_rule_extraction_citation_count"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_rule_extraction_confidence"
        ),
        CheckConstraint("outcome = 'extracted' OR needs_review", name="ck_rule_extraction_review"),
        CheckConstraint(
            f"length(answer) <= {MAX_ANSWER_CHARS}", name="ck_rule_extraction_answer_length"
        ),
        Index("ix_rule_extraction_extracted", "extracted_at", "document_id"),
        {"comment": EXTRACTION_COMMENT},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    prompt_version: Mapped[str] = mapped_column(String(80))
    candidate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(SmallInteger)
    source_key: Mapped[str] = mapped_column(String(63))
    doc_type: Mapped[str] = mapped_column(String(16))
    regulator: Mapped[str] = mapped_column(String(40))
    fields: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    issues: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    citation_count: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean)
    answer: Mapped[str] = mapped_column(Text, server_default="")
    ontology_version: Mapped[str] = mapped_column(String(40))
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
