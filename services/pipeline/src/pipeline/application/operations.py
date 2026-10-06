"""The pipeline's operations, as the regulatory team runs them: every source's crawl runs and
documents, a person's retry of a stored document, and the outbox's dead rows with their requeue.

- ``ListRuns``: the crawl runs, the latest started first, of a source, a status and a trigger.
- ``ListDocuments`` and ``ReadDocumentView``: every source's documents, the latest first fetch
  first, of a status, a source, a type and publication dates, each with how the pipeline reads
  it (``read_as``: its classification's type, else its uploader's, else its source's), its
  classification and its extraction by the current prompt; one document also with its retries.
- ``RetryDocument``: an ingest of the stored bytes again, from a stage, without a new fetch
  (``domain.retry``). It refuses while an ingest of the document runs (the ingests whose ids
  follow from the document: its crawl's, its earlier retries', its tasks' resolutions', its rule
  extraction), while a triage task holds it, and an extraction when there is nothing to extract.
  In one transaction, with the document's row locked, it records the attempt, and with a
  person's type the document's classification (``retry``), status and document.classified, and
  writes its ``pipeline.document.retry`` audit row; then, with the transaction closed, it starts
  the ingest ``pipeline-retry-<document>-<attempt>``. The same request again under its
  Idempotency-Key replays its attempt, and starts its ingest if it did not start; the same key
  with another body is refused.
- ``ListDeadEvents`` and ``RequeueEvent``: the outbox's dead rows, the newest dead first, and a
  dead row put back to pending (attempts reset, due at once) with its ``pipeline.outbox.requeue``
  audit row, in one transaction. A row that is not dead is answered as it stands, unchanged.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from domain_kernel.audit import AuditActor, AuditActorKind, AuditEntry
from domain_kernel.documents import DocumentType
from domain_kernel.events import utc_now
from domain_kernel.ids import DocumentId
from pipeline.application.extraction import RULE_PROMPT_REF
from pipeline.application.sources import AdminAction, require_reason
from pipeline.application.tasks import manual_parse_workflow_id, triage_workflow_id
from pipeline.domain.classification import Classification, Route, extracts_rules
from pipeline.domain.crawl import CrawlRun
from pipeline.domain.errors import (
    DocumentNotFoundError,
    IngestRunningError,
    OutboxEventNotFoundError,
    RetryInvalidError,
    RetryRefusedError,
    SourceInvalidError,
)
from pipeline.domain.events import DocumentClassified
from pipeline.domain.extraction import RuleExtraction, extraction_workflow_id
from pipeline.domain.outbox import DeadEventKey, OutboxEvent
from pipeline.domain.ports import AdapterTypes, IngestStart, IngestStarter, RawStore
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.repository import DocumentQuery, RunQuery, UnitOfWork, UnitOfWorkFactory
from pipeline.domain.retry import DocumentRetry, RetryId, RetryStage, retry_workflow_id
from pipeline.domain.schedule import ingest_workflow_id
from pipeline.domain.sources import Source, source_id_of
from pipeline.domain.tasks import PipelineTask, TaskKind, TaskStatus
from py_common.idempotency import IdempotencyKeyReusedError
from py_common.logging import get_logger

log = get_logger(__name__)

RETRY_ACTION: Final = "pipeline.document.retry"
REQUEUE_ACTION: Final = "pipeline.outbox.requeue"
DOCUMENT_SUBJECT: Final = "raw_document"
OUTBOX_SUBJECT: Final = "outbox_event"
UPLOAD_SCHEME: Final = "upload://"


def _person(actor: AuditActor) -> UUID | None:
    return UUID(actor.id) if actor.kind is AuditActorKind.USER else None


# ---------------------------------------------------------------- runs


class ListRuns:
    def __init__(self, units: UnitOfWorkFactory) -> None:
        self._units = units

    def run(self, query: RunQuery) -> Sequence[CrawlRun]:
        with self._units() as unit:
            return unit.crawl_runs.page(query)


# ---------------------------------------------------------------- documents


@dataclass(frozen=True, slots=True)
class DocumentView:
    """A stored document with how the pipeline reads it: ``read_as`` (its classification's type,
    else its uploader's, else its source's; None for a source the code cannot read), its
    classification and its extraction by the current prompt (None before either), and, read one
    at a time, its retries."""

    record: RawDocumentRecord
    read_as: DocumentType | None
    classification: Classification | None
    extraction: RuleExtraction | None
    retries: tuple[DocumentRetry, ...] = ()


def source_types(sources: Sequence[Source], types: AdapterTypes) -> dict[str, DocumentType]:
    """Each source's document type, as its adapter type reads its parameters; a source the code
    cannot read is left out."""
    found: dict[str, DocumentType] = {}
    for source in sources:
        try:
            found[source.key] = types.describe(source.adapter_type, source.parameters).doc_type
        except SourceInvalidError:
            continue
    return found


def _views(
    unit: UnitOfWork, records: Sequence[RawDocumentRecord], types: Mapping[str, DocumentType]
) -> list[DocumentView]:
    ids = [record.document_id for record in records]
    classifications = unit.classifications.of_documents(ids)
    extractions = unit.extractions.of_documents(ids, RULE_PROMPT_REF)
    views: list[DocumentView] = []
    for record in records:
        classification = classifications.get(record.document_id)
        read_as = (
            classification.doc_type
            if classification is not None
            else record.doc_type or types.get(record.source_key)
        )
        views.append(
            DocumentView(record, read_as, classification, extractions.get(record.document_id))
        )
    return views


class ListDocuments:
    def __init__(self, units: UnitOfWorkFactory, types: AdapterTypes) -> None:
        self._units = units
        self._types = types

    def run(self, query: DocumentQuery) -> list[DocumentView]:
        with self._units() as unit:
            types = source_types(unit.sources.list(), self._types)
            if query.doc_type is not None:
                wanted = query.doc_type
                query = replace(
                    query,
                    of_source_type=frozenset(key for key, kind in types.items() if kind is wanted),
                )
            return _views(unit, unit.documents.search(query), types)


class ReadDocumentView:
    def __init__(self, units: UnitOfWorkFactory, types: AdapterTypes) -> None:
        self._units = units
        self._types = types

    def run(self, document_id: DocumentId) -> DocumentView:
        with self._units() as unit:
            record = unit.documents.get(document_id)
            if record is None:
                raise DocumentNotFoundError(f"no stored document has the id {document_id}")
            return _view_of(unit, record, self._types)


def _view_of(unit: UnitOfWork, record: RawDocumentRecord, types: AdapterTypes) -> DocumentView:
    source = unit.sources.get(record.source_key)
    kinds = source_types([] if source is None else [source], types)
    (view,) = _views(unit, [record], kinds)
    return DocumentView(
        view.record,
        view.read_as,
        view.classification,
        view.extraction,
        tuple(unit.retries.of_document(record.document_id)),
    )


# ---------------------------------------------------------------- retries


@dataclass(frozen=True, slots=True)
class RetryRequest:
    """A person's retry: the document, the stage, the type they give it (None: its
    classification stands), the request's Idempotency-Key with the fingerprint of the request,
    and who asks and why."""

    document_id: DocumentId
    stage: RetryStage
    idempotency_key: str
    fingerprint: str
    admin: AdminAction
    doc_type: DocumentType | None = None


@dataclass(frozen=True, slots=True)
class RetryOutcome:
    """The retry recorded (or found, ``replayed``), the document as it stands after it, whether
    its ingest started now (False: it runs or ran), and whether the person's type reclassified
    the document."""

    retry: DocumentRetry
    document: DocumentView
    started: bool
    replayed: bool
    reclassified: bool


@dataclass(frozen=True, slots=True)
class _Recorded:
    """What the transaction did: recorded ``retry`` (``replayed``: found it under the key,
    written meanwhile), with the document as it stands after, and whether the person's type
    reclassified it."""

    record: RawDocumentRecord
    retry: DocumentRetry
    replayed: bool = False
    reclassified: bool = False


@dataclass(frozen=True, slots=True)
class _Found:
    record: RawDocumentRecord
    source: Source | None
    retries: tuple[DocumentRetry, ...]
    tasks: tuple[PipelineTask, ...]
    classification: Classification | None
    extracted: bool


class RetryDocument:
    def __init__(
        self,
        units: UnitOfWorkFactory,
        raw_store: RawStore,
        starter: IngestStarter,
        types: AdapterTypes,
        *,
        knowledge: bool,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._units = units
        self._raw = raw_store
        self._starter = starter
        self._types = types
        self._knowledge = knowledge
        self._clock = clock

    def run(self, request: RetryRequest) -> RetryOutcome:
        reason = require_reason(request.admin.reason)
        found = self._find(request.document_id)
        replayed = _by_key(found.retries, request)
        if replayed is not None:
            return self._replay(replayed)
        self._check(found, request)
        running = self._starter.running(_ingest_ids(found))
        if running:
            raise IngestRunningError(
                f"document {request.document_id}: an ingest of it runs "
                f"({', '.join(sorted(running))}); retry once it ends"
            )
        recorded = self._record(found, request, reason)
        retry = recorded.retry
        if recorded.replayed:
            return self._replay(retry)
        started = self._start(retry, recorded.record, reclassify=_reclassifies(request))
        log.info(
            "pipeline.document_retried",
            document_id=str(retry.document_id),
            attempt=retry.attempt,
            stage=retry.stage.value,
            doc_type=None if retry.doc_type is None else retry.doc_type.value,
            workflow_id=retry.workflow_id,
            started=started,
        )
        return RetryOutcome(
            retry, self._view(retry.document_id), started, False, recorded.reclassified
        )

    def _find(self, document_id: DocumentId) -> _Found:
        with self._units() as unit:
            record = unit.documents.get(document_id)
            if record is None:
                raise DocumentNotFoundError(f"no stored document has the id {document_id}")
            return _Found(
                record=record,
                source=unit.sources.get(record.source_key),
                retries=tuple(unit.retries.of_document(document_id)),
                tasks=tuple(unit.tasks.of_document(document_id)),
                classification=unit.classifications.get(document_id),
                extracted=unit.extractions.get(document_id, RULE_PROMPT_REF) is not None,
            )

    def _check(self, found: _Found, request: RetryRequest) -> None:
        """Refuse what cannot be: an extraction of a type no rule is extracted from (422), a
        document a triage task holds, nothing to extract (409)."""
        given = request.doc_type
        document_id = request.document_id
        if request.stage is RetryStage.EXTRACT and given is not None and not extracts_rules(given):
            raise RetryInvalidError(
                f"no rule is extracted from a {given.value.replace('_', ' ')}: retry it from "
                "parse or classify with that type"
            )
        held = [
            task
            for task in found.tasks
            if task.kind is TaskKind.TRIAGE and task.status is TaskStatus.OPEN
        ]
        if held:
            raise RetryRefusedError(
                f"document {document_id} waits for its triage (task {held[0].id}): resolve or "
                "dismiss the task first"
            )
        if request.stage is not RetryStage.EXTRACT or given is not None:
            return
        classification = found.classification
        if classification is None or classification.route is not Route.EXTRACT:
            route = "unclassified" if classification is None else classification.route.value
            raise RetryRefusedError(
                f"document {document_id} is {route}: only a document classified on its way to "
                "the extraction is extracted; retry from parse or classify, with its type if "
                "it needs one"
            )
        if found.extracted:
            raise RetryRefusedError(
                f"document {document_id} is extracted already by {RULE_PROMPT_REF}: nothing is "
                "left to extract"
            )

    def _record(self, found: _Found, request: RetryRequest, reason: str) -> _Recorded:
        """The attempt recorded with its audit row, and the person's type, in one transaction
        with the document's row locked. A retry of the same key written meanwhile is replayed;
        any other retry written meanwhile means its ingest runs."""
        now = self._clock()
        document_id = request.document_id
        with self._units() as unit:
            record = unit.documents.lock(document_id)
            if record is None:
                raise DocumentNotFoundError(f"no stored document has the id {document_id}")
            retries = tuple(unit.retries.of_document(document_id))
            meanwhile = _by_key(retries, request)
            if meanwhile is not None:
                return _Recorded(record, meanwhile, replayed=True)
            if len(retries) != len(found.retries):
                raise IngestRunningError(
                    f"document {document_id}: another retry of it started meanwhile "
                    f"(attempt {retries[-1].attempt}); retry once its ingest ends"
                )
            before = _audited(record, unit.classifications.get(document_id))
            attempt = 1 + max((retry.attempt for retry in retries), default=0)
            retry = DocumentRetry(
                id=RetryId.new(),
                document_id=document_id,
                attempt=attempt,
                stage=request.stage,
                reason=reason,
                requested_at=now,
                idempotency_key=request.idempotency_key,
                fingerprint=request.fingerprint,
                workflow_id=retry_workflow_id(document_id, attempt),
                doc_type=request.doc_type,
                requested_by=_person(request.admin.actor),
            )
            reclassified = False
            if request.doc_type is not None:
                record = self._reclassify(
                    unit, record, request.doc_type, request.admin, now, reason
                )
                reclassified = True
            if not unit.retries.add(retry):
                raise IngestRunningError(
                    f"document {document_id}: another retry of it started meanwhile; retry once "
                    "its ingest ends"
                )
            after = {
                **_audited(record, unit.classifications.get(document_id)),
                "stage": retry.stage.value,
                "attempt": retry.attempt,
                "workflow_id": retry.workflow_id,
            }
            unit.audit.write(
                AuditEntry(
                    action=RETRY_ACTION,
                    tenant_id=None,
                    subject_type=DOCUMENT_SUBJECT,
                    subject_id=str(document_id),
                    actor=request.admin.actor,
                    reason=reason,
                    before=before,
                    after=after,
                    occurred_at=now,
                    correlation_id=request.admin.correlation_id,
                )
            )
        return _Recorded(record, retry, reclassified=reclassified)

    def _reclassify(
        self,
        unit: UnitOfWork,
        record: RawDocumentRecord,
        doc_type: DocumentType,
        admin: AdminAction,
        now: datetime,
        reason: str,
    ) -> RawDocumentRecord:
        """The person's type as the document's classification, with its status and its
        document.classified; the stored document's own type (its uploader's) never changes."""
        given = Classification.given(
            record.document_id, doc_type=doc_type, by=_person(admin.actor), at=now, reason=reason
        )
        if unit.classifications.get(record.document_id) is None:
            unit.classifications.add(given)
        else:
            unit.classifications.save(given)
        unit.documents.set_status(record.document_id, given.route.status)
        unit.events.publish(
            DocumentClassified.of(
                given, source_id=source_id_of(record.source_key), source_key=record.source_key
            )
        )
        return unit.documents.get(record.document_id) or record

    def _replay(self, retry: DocumentRetry) -> RetryOutcome:
        """A retry recorded before under this key: its ingest, started now only if it did not
        start."""
        with self._units() as unit:
            record = unit.documents.get(retry.document_id)
        if record is None:
            raise DocumentNotFoundError(f"no stored document has the id {retry.document_id}")
        started = self._start(
            retry, record, reclassify=retry.stage is RetryStage.CLASSIFY and retry.doc_type is None
        )
        return RetryOutcome(retry, self._view(retry.document_id), started, True, False)

    def _start(self, retry: DocumentRetry, record: RawDocumentRecord, *, reclassify: bool) -> bool:
        with self._units() as unit:
            source = unit.sources.get(record.source_key)
        regulator = ""
        if source is not None:
            try:
                regulator = self._types.describe(source.adapter_type, source.parameters).regulator
            except SourceInvalidError:
                regulator = ""
        return self._starter.start(
            IngestStart(
                workflow_id=retry.workflow_id,
                record=record,
                source_id=source_id_of(record.source_key),
                regulator=regulator,
                raw_uri=self._raw.uri(record.storage_key),
                duplicate=True,
                knowledge=self._knowledge and bool(regulator),
                reclassify=reclassify,
            )
        )

    def _view(self, document_id: DocumentId) -> DocumentView:
        with self._units() as unit:
            record = unit.documents.get(document_id)
            if record is None:
                raise DocumentNotFoundError(f"no stored document has the id {document_id}")
            return _view_of(unit, record, self._types)


def _by_key(retries: Sequence[DocumentRetry], request: RetryRequest) -> DocumentRetry | None:
    """The retry recorded under the request's key; another body under the key is refused."""
    for retry in retries:
        if retry.idempotency_key == request.idempotency_key:
            if retry.fingerprint != request.fingerprint:
                raise IdempotencyKeyReusedError()
            return retry
    return None


def _reclassifies(request: RetryRequest) -> bool:
    """Whether the ingest has the detector read the document again: a retry from the classify
    stage that gives no type (a person's type stands as given)."""
    return request.stage is RetryStage.CLASSIFY and request.doc_type is None


def _ingest_ids(found: _Found) -> list[str]:
    """The ingests of the document whose ids follow from it: its earlier retries', its crawl's
    (a listed document), its tasks' resolutions' and its rule extraction's."""
    record = found.record
    ids = [retry.workflow_id for retry in found.retries]
    if not record.source_url.startswith(UPLOAD_SCHEME):
        ids.append(ingest_workflow_id(record.source_key, record.source_url))
    for task in found.tasks:
        if task.status is not TaskStatus.RESOLVED:
            continue
        if task.kind is TaskKind.MANUAL_PARSE:
            ids.append(manual_parse_workflow_id(task.id))
        else:
            ids.append(triage_workflow_id(task.id))
    ids.append(extraction_workflow_id(record.document_id, RULE_PROMPT_REF))
    return ids


def _audited(record: RawDocumentRecord, classification: Classification | None) -> dict[str, object]:
    return {
        "status": record.status.value,
        "classification": None
        if classification is None
        else {
            "doc_type": classification.doc_type.value,
            "relevance": classification.relevance.value,
            "confidence": classification.confidence.value,
            "classifier": classification.classifier,
        },
    }


# ---------------------------------------------------------------- the outbox


class ListDeadEvents:
    def __init__(self, units: UnitOfWorkFactory) -> None:
        self._units = units

    def run(
        self, *, topic: str | None, after: DeadEventKey | None, limit: int
    ) -> Sequence[OutboxEvent]:
        with self._units() as unit:
            return unit.outbox.dead(topic=topic, after=after, limit=limit)


@dataclass(frozen=True, slots=True)
class Requeued:
    """The outbox row as it stands after the requeue, and whether this request moved it."""

    event: OutboxEvent
    requeued: bool


class RequeueEvent:
    def __init__(
        self, units: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._units = units
        self._clock = clock

    def run(self, event_id: UUID, admin: AdminAction) -> Requeued:
        reason = require_reason(admin.reason)
        now = self._clock()
        with self._units() as unit:
            before = unit.outbox.get(event_id)
            if before is None:
                raise OutboxEventNotFoundError(f"the pipeline's outbox holds no event {event_id}")
            if not unit.outbox.requeue(event_id, at=now):
                return Requeued(before, False)
            after = unit.outbox.get(event_id) or before
            unit.audit.write(
                AuditEntry(
                    action=REQUEUE_ACTION,
                    tenant_id=None,
                    subject_type=OUTBOX_SUBJECT,
                    subject_id=str(event_id),
                    actor=admin.actor,
                    reason=reason,
                    before=_outbox_audited(before),
                    after=_outbox_audited(after),
                    occurred_at=now,
                    correlation_id=admin.correlation_id,
                )
            )
        log.info("pipeline.outbox_requeued", event_id=str(event_id), topic=before.topic)
        return Requeued(after, True)


def _outbox_audited(event: OutboxEvent) -> dict[str, object]:
    return {
        "topic": event.topic,
        "status": event.status.value,
        "attempts": event.attempts,
        "last_error": event.last_error[:500],
    }
