"""Request and response bodies of the operations routes: crawl runs, every source's documents, a
retry, and the outbox's dead rows."""

from typing import Any, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from domain_kernel.documents import DocumentType
from domain_kernel.ids import DocumentId
from pipeline.api.schemas import AdminWriteIn, CrawlRunOut, DocumentOut
from pipeline.application.operations import DocumentView, Requeued, RetryOutcome
from pipeline.domain.classification import Classification, Relevance, Route, TypeConfidence
from pipeline.domain.crawl import CrawlRun, CrawlRunId
from pipeline.domain.extraction import ExtractionOutcome, RuleExtraction
from pipeline.domain.outbox import DeadEventKey, OutboxEvent, OutboxStatus
from pipeline.domain.repository import FetchKey, RunKey
from pipeline.domain.retry import DocumentRetry, RetryStage


class RunOut(CrawlRunOut):
    """A crawl run with its source."""

    source_key: str

    @classmethod
    def of_run(cls, run: CrawlRun) -> Self:
        return cls(**CrawlRunOut.of(run).model_dump(), source_key=run.source_key)


class RunCursor(BaseModel):
    """The keyset of the run list: when the run started, and its id."""

    s: AwareDatetime
    i: UUID

    @classmethod
    def of(cls, run: CrawlRun) -> Self:
        return cls(s=run.started_at, i=run.id.value)

    def key(self) -> RunKey:
        return RunKey(self.s, CrawlRunId(self.i))


class ClassificationOut(BaseModel):
    doc_type: DocumentType
    relevance: Relevance
    confidence: TypeConfidence
    route: Route = Field(
        description=(
            "Where it goes: extract (on to the rule extraction), reference (registered, nothing "
            "extracted), irrelevant (set aside), triage (held for a person)"
        )
    )
    reasons: list[str]
    classifier: str = Field(
        description=(
            "detector@1 for the rule-based detector, triage for a person's triage, retry for "
            "the type a person gave on a retry"
        )
    )
    decided_by: UUID | None = Field(description="The person whose decision it is, if one's")
    task_id: UUID | None
    classified_at: AwareDatetime

    @classmethod
    def of(cls, classification: Classification) -> Self:
        return cls(
            doc_type=classification.doc_type,
            relevance=classification.relevance,
            confidence=classification.confidence,
            route=classification.route,
            reasons=list(classification.reasons),
            classifier=classification.classifier,
            decided_by=classification.decided_by,
            task_id=None if classification.task_id is None else classification.task_id.value,
            classified_at=classification.classified_at,
        )


class ExtractionOut(BaseModel):
    """The document's rule extraction by the current prompt."""

    prompt_version: str
    outcome: ExtractionOutcome = Field(
        description="extracted (a candidate), or unparseable (the model gave none, twice)"
    )
    candidate_id: UUID = Field(description="The candidate its rule.candidate.created names")
    needs_review: bool
    issue_count: int
    model: str
    extracted_at: AwareDatetime

    @classmethod
    def of(cls, extraction: RuleExtraction) -> Self:
        return cls(
            prompt_version=extraction.prompt_version,
            outcome=extraction.outcome,
            candidate_id=extraction.candidate_id.value,
            needs_review=extraction.needs_review,
            issue_count=len(extraction.issues),
            model=extraction.model,
            extracted_at=extraction.extracted_at,
        )


class RetryOut(BaseModel):
    """One retry of a document: its attempt, stage, the type a person gave, why, by whom and
    when, and its ingest's workflow."""

    attempt: int
    stage: RetryStage
    doc_type: DocumentType | None = Field(
        description="The type the person gave the document; null when its classification stood"
    )
    reason: str
    requested_by: UUID | None = Field(
        description="Who asked, when a person's token or id named one"
    )
    requested_at: AwareDatetime
    workflow_id: str = Field(description="pipeline-retry-<document>-<attempt>")

    @classmethod
    def of(cls, retry: DocumentRetry) -> Self:
        return cls(
            attempt=retry.attempt,
            stage=retry.stage,
            doc_type=retry.doc_type,
            reason=retry.reason,
            requested_by=retry.requested_by,
            requested_at=retry.requested_at,
            workflow_id=retry.workflow_id,
        )


class PipelineDocumentOut(DocumentOut):
    """A stored document with how the pipeline reads it."""

    read_as: DocumentType | None = Field(
        description=(
            "The type the pipeline reads it as: its classification's, else its uploader's, else "
            "its source's; null for a source the code cannot read"
        )
    )
    classification: ClassificationOut | None = Field(description="Null before its classify step")
    extraction: ExtractionOut | None = Field(
        description="Its rule extraction by the current prompt; null before one is stored"
    )

    @classmethod
    def of_view(cls, view: DocumentView) -> Self:
        return cls(
            **DocumentOut.of(view.record).model_dump(),
            read_as=view.read_as,
            classification=(
                None if view.classification is None else ClassificationOut.of(view.classification)
            ),
            extraction=None if view.extraction is None else ExtractionOut.of(view.extraction),
        )


class DocumentDetailOut(PipelineDocumentOut):
    """One stored document with how the pipeline reads it and the retries people asked for."""

    retries: list[RetryOut] = Field(description="Its retries by attempt; empty before one")

    @classmethod
    def of_detail(cls, view: DocumentView) -> Self:
        return cls(
            **PipelineDocumentOut.of_view(view).model_dump(),
            retries=[RetryOut.of(retry) for retry in view.retries],
        )


class FetchCursor(BaseModel):
    """The keyset of every source's documents: the first fetch, and the id."""

    f: AwareDatetime
    i: UUID

    @classmethod
    def of(cls, view: DocumentView) -> Self:
        return cls(f=view.record.fetched_at, i=view.record.document_id.value)

    def key(self) -> FetchKey:
        return FetchKey(self.f, DocumentId(self.i))


class RetryIn(AdminWriteIn):
    """A retry of a stored document: the stage its ingest starts again from, and, to reclassify
    it, the type a person gives it."""

    stage: RetryStage = Field(
        description=(
            "parse: the stored document's whole ingest again (parse, classify, register, "
            "extract); classify: the same with the detector's classification read again; "
            "extract: the rule extraction of a document classified on its way to it"
        )
    )
    doc_type: DocumentType | None = Field(
        default=None,
        description=(
            "The document's type, as a person reads it: it reclassifies the document (relevant, "
            "certain, by retry), beats the detector, and brings back a document set aside as "
            "irrelevant or whose triage was dismissed"
        ),
    )


class RetryAcceptedOut(BaseModel):
    """The retry and its ingest: ``started`` is false when the ingest was started before (a
    request sent again under its Idempotency-Key, whose answer is replayed)."""

    document: DocumentDetailOut
    retry: RetryOut
    workflow_id: str
    started: bool
    reclassified: bool = Field(description="Whether the person's type reclassified the document")

    @classmethod
    def of(cls, outcome: RetryOutcome) -> Self:
        return cls(
            document=DocumentDetailOut.of_detail(outcome.document),
            retry=RetryOut.of(outcome.retry),
            workflow_id=outcome.retry.workflow_id,
            started=outcome.started,
            reclassified=outcome.reclassified,
        )


class OutboxEventOut(BaseModel):
    """An outbox row without its body."""

    event_id: UUID
    topic: str
    schema_version: str
    key: str = Field(description="The Kafka message key (the event's source)")
    status: OutboxStatus
    attempts: int = Field(description="Failed sends since it was written or last requeued")
    last_error: str
    occurred_at: AwareDatetime
    created_at: AwareDatetime
    published_at: AwareDatetime | None
    dead_at: AwareDatetime | None = Field(description="When the relay marked it dead")
    summary: dict[str, Any] = Field(
        description=(
            "What the event is about, from its payload: the document, source, candidate, type "
            "or outcome it names; never the body"
        )
    )
    payload_bytes: int

    @classmethod
    def of(cls, event: OutboxEvent) -> Self:
        return cls(
            event_id=event.event_id,
            topic=event.topic,
            schema_version=event.schema_version,
            key=event.partition_key,
            status=event.status,
            attempts=event.attempts,
            last_error=event.last_error,
            occurred_at=event.occurred_at,
            created_at=event.created_at,
            published_at=event.published_at,
            dead_at=event.dead_at,
            summary=dict(event.summary),
            payload_bytes=event.payload_bytes,
        )


class DeadCursor(BaseModel):
    """The keyset of the dead rows: when each went dead, and its id."""

    d: AwareDatetime
    i: UUID

    @classmethod
    def of(cls, event: OutboxEvent) -> Self:
        key = DeadEventKey.of(event)
        return cls(d=key.dead_at, i=key.event_id)

    def key(self) -> DeadEventKey:
        return DeadEventKey(self.d, self.i)


class RequeueIn(AdminWriteIn):
    """A dead outbox row put back to pending, so the relay sends it again."""


class RequeueOut(BaseModel):
    """The row as it stands now: ``requeued`` is false for a row that was not dead (pending, or
    published), which nothing changed."""

    event: OutboxEventOut
    requeued: bool

    @classmethod
    def of(cls, requeued: Requeued) -> Self:
        return cls(event=OutboxEventOut.of(requeued.event), requeued=requeued.requeued)
