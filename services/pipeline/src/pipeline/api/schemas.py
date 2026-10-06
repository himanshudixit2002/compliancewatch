"""Request and response bodies of the source manager's routes."""

from datetime import date, timedelta
from typing import Any, Final, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from domain_kernel.documents import DocumentType
from domain_kernel.ids import DocumentId
from pipeline.application.sources import (
    MAX_REASON_CHARS,
    MIN_REASON_CHARS,
    SourceEdit,
    SourceView,
)
from pipeline.domain.crawl import CrawlRun, CrawlStatus
from pipeline.domain.ports import CrawlStart
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.repository import DocumentKey
from pipeline.domain.schedule import CrawlTrigger, Freshness, FreshnessState, SourceStatus
from pipeline.domain.sources import (
    ADAPTER_TYPE_PATTERN,
    MAX_CADENCE,
    MAX_NAME_CHARS,
    MIN_CADENCE,
    SOURCE_KEY_PATTERN,
)

MIN_CADENCE_SECONDS: Final = int(MIN_CADENCE.total_seconds())
MAX_CADENCE_SECONDS: Final = int(MAX_CADENCE.total_seconds())
ACTOR_ID: Final = (
    "The admin taking the step; a signed-in user's token overrides it, and the audit entry "
    "names whoever acted"
)
REASON: Final = "Why: kept verbatim in the audit entry"


class AdminWriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: UUID = Field(description=ACTOR_ID)
    reason: str = Field(
        min_length=MIN_REASON_CHARS, max_length=MAX_REASON_CHARS, description=REASON
    )


class SourceIn(AdminWriteIn):
    """A source to add: its key, name, adapter type with the type's parameters, and cadence."""

    key: str = Field(pattern=SOURCE_KEY_PATTERN, examples=["cbic_notifications"])
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    adapter_type: str = Field(
        pattern=ADAPTER_TYPE_PATTERN,
        examples=["cbic"],
        description="An adapter type of the registry: cbic, gstcouncil, gstn or mahagst",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The adapter type's parameters, which it checks: cbic takes listing (notifications "
            "or circulars) and category (one with a recorded listing); the others take none"
        ),
        examples=[{"listing": "notifications", "category": "Central Tax"}],
    )
    cadence_seconds: int = Field(ge=MIN_CADENCE_SECONDS, le=MAX_CADENCE_SECONDS)
    enabled: bool = True
    paused: bool = False


class SourceEditIn(AdminWriteIn):
    """What to change; a field left out stays as it is."""

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_CHARS)
    cadence_seconds: int | None = Field(
        default=None, ge=MIN_CADENCE_SECONDS, le=MAX_CADENCE_SECONDS
    )
    enabled: bool | None = None
    paused: bool | None = None
    parameters: dict[str, Any] | None = Field(
        default=None, description="All of the adapter type's parameters, checked again"
    )

    def edit(self) -> SourceEdit:
        return SourceEdit(
            name=self.name,
            cadence=(
                None if self.cadence_seconds is None else timedelta(seconds=self.cadence_seconds)
            ),
            enabled=self.enabled,
            paused=self.paused,
            parameters=self.parameters,
        )


class FetchIn(AdminWriteIn):
    """An admin's fetch of the source now."""


class FreshnessOut(BaseModel):
    state: FreshnessState = Field(
        description=(
            "fresh within one cadence of the last listing, late within two, stale beyond (the "
            "SourceStale alert pages then), never before the first"
        )
    )
    age_seconds: int | None = Field(description="Seconds since a crawl last listed the source")
    cadence_seconds: int
    cadences: float | None = Field(description="The age in cadences, two decimals")

    @classmethod
    def of(cls, freshness: Freshness) -> Self:
        ratio = freshness.cadences
        return cls(
            state=freshness.state,
            age_seconds=None if freshness.age is None else int(freshness.age.total_seconds()),
            cadence_seconds=int(freshness.cadence.total_seconds()),
            cadences=None if ratio is None else round(ratio, 2),
        )


class CrawlRunOut(BaseModel):
    run_id: UUID
    status: CrawlStatus
    started_at: AwareDatetime
    finished_at: AwareDatetime | None
    listed: int
    stored: int
    duplicates: int
    failed: int
    error: str

    @classmethod
    def of(cls, run: CrawlRun) -> Self:
        return cls(
            run_id=run.id.value,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            listed=run.counts.listed,
            stored=run.counts.stored,
            duplicates=run.counts.duplicates,
            failed=run.counts.failed,
            error=run.error,
        )


class SourceOut(BaseModel):
    key: str
    name: str = Field(description="The source's name, or its key when it has none")
    adapter_type: str
    parameters: dict[str, Any]
    regulator: str | None = Field(
        description="From the adapter type; null when the code cannot read the source's type"
    )
    site: str | None
    doc_type: DocumentType | None
    cadence_seconds: int
    enabled: bool
    paused: bool
    status: SourceStatus = Field(
        description=(
            "fetching while a crawl runs, else paused while paused or disabled, failing when "
            "the last crawl recorded an error, healthy otherwise"
        )
    )
    document_count: int
    last_fetch_at: AwareDatetime | None = Field(description="When a crawl last listed the source")
    freshness: FreshnessOut
    last_error: str
    watermark: date | None = Field(
        description="The newest publication date up to which every listed document is stored"
    )
    latest_run: CrawlRunOut | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def of(cls, view: SourceView) -> Self:
        source, kind = view.source, view.kind
        return cls(
            key=source.key,
            name=source.label,
            adapter_type=source.adapter_type,
            parameters=dict(source.parameters),
            regulator=None if kind is None else kind.regulator,
            site=None if kind is None else kind.site,
            doc_type=None if kind is None else kind.doc_type,
            cadence_seconds=int(source.cadence.total_seconds()),
            enabled=source.enabled,
            paused=source.paused,
            status=view.status,
            document_count=view.document_count,
            last_fetch_at=source.last_fetch_at,
            freshness=FreshnessOut.of(view.freshness),
            last_error=source.last_error,
            watermark=source.watermark_date,
            latest_run=None if view.latest_run is None else CrawlRunOut.of(view.latest_run),
            created_at=source.created_at,
            updated_at=source.updated_at,
        )


class SourcesOut(BaseModel):
    items: list[SourceOut] = Field(description="Every source, by key")


class FetchOut(BaseModel):
    """The crawl started: its run (``latest_run`` of the source shows it) and its workflow."""

    run_id: UUID
    workflow_id: str
    source_key: str
    trigger: CrawlTrigger

    @classmethod
    def of(cls, start: CrawlStart) -> Self:
        return cls(
            run_id=start.run_id.value,
            workflow_id=start.workflow_id,
            source_key=start.source_key,
            trigger=start.trigger,
        )


class DocumentOut(BaseModel):
    document_id: UUID
    source_key: str
    source_url: str
    external_ref: str
    title: str
    published_on: date | None
    fetched_at: AwareDatetime = Field(description="When the bytes were first fetched")
    content_type: str
    size: int
    sha256: str
    storage_key: str
    status: DocumentStatus
    raw_path: str = Field(description="Where the stored bytes are served")

    @classmethod
    def of(cls, record: RawDocumentRecord) -> Self:
        return cls(
            document_id=record.document_id.value,
            source_key=record.source_key,
            source_url=record.source_url,
            external_ref=record.external_ref,
            title=record.title,
            published_on=record.published_on,
            fetched_at=record.fetched_at,
            content_type=record.content_type,
            size=record.size,
            sha256=record.sha256,
            storage_key=record.storage_key,
            status=record.status,
            raw_path=f"/v1/pipeline/documents/{record.document_id}/raw",
        )


class DocumentCursor(BaseModel):
    """The keyset of a source's document list: publication date, first fetch, id."""

    p: date | None
    f: AwareDatetime
    i: UUID

    @classmethod
    def of(cls, record: RawDocumentRecord) -> Self:
        return cls(p=record.published_on, f=record.fetched_at, i=record.document_id.value)

    def key(self) -> DocumentKey:
        return DocumentKey(self.p, self.f, DocumentId(self.i))
