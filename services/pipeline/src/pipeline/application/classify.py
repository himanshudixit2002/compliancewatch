"""The classify step of the ingest (``pipeline.classify_document``): what a parsed document is,
and where it goes next.

``ClassifyDocument`` parses the stored document again the way its parse did (``hints_for``),
reads it with the detector (``application.detector``: the type its opening names, how sure that
is, and whether it is a regulatory document at all, by the title the registration gives it: the
listed one, else the parse's) and records the classification
(``domain.classification``) in one transaction with the document's status, its
``document.classified`` and, for a conflict, its ``triage`` task:

- an irrelevant document is set aside (``irrelevant``) and the ingest ends;
- a conflict is held for a person (``triage``, with its task) and the ingest ends;
- a press release or a statute is kept for reference (``reference``): registered and embedded,
  nothing extracted;
- a notification, circular or act amendment is ``classified`` and goes on to the rule
  extraction, while ``CW_PIPELINE_EXTRACTION_ENABLED`` is on (``Classified.extracts``).

A document classified before (a retry, a second ingest of the same bytes, a person's triage) keeps
its classification: nothing is read again or written, and the result says ``created=False``. A
retry from the classify stage asks for it ``fresh``: the detector reads the document again and,
when it reads it another way, its classification replaces the detector's earlier one, with the
status, a document.classified and, for a conflict, a triage task. A person's decision (a triage,
a type given on a retry) is never read again: the detector does not replace a person.
"""

import dataclasses
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import ClassVar, Final
from uuid import UUID

from temporalio.common import RetryPolicy

from domain_kernel.events import utc_now
from domain_kernel.ids import DocumentId, SourceId
from pipeline.application.activities import (
    Frozen,
    ParseRequest,
    hints_for,
    on_thread,
    parse_request,
)
from pipeline.application.detector import detect
from pipeline.domain.classification import Classification, Route
from pipeline.domain.errors import ClassifiedMeanwhileError, DocumentNotFoundError
from pipeline.domain.events import DocumentClassified
from pipeline.domain.ports import DocumentParsers, RawStore
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.domain.tasks import MAX_REASON_CHARS, PipelineTask, TaskKind
from py_common.logging import get_logger
from py_common.temporal import ActivityBase

log = get_logger(__name__)

CLASSIFY_RETRIES: Final = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=10,
    non_retryable_error_types=[
        "UnsupportedDocumentError",
        "UnparsedDocumentError",
        "TranscriptInvalidError",
        "RawObjectMissingError",
        "RawObjectCorruptError",
        "DocumentNotFoundError",
        "InvariantViolationError",
    ],
)
"""The detector gives the same answer every time; a retry waits out the raw store or the
database, or finds the classification another ingest of the same bytes recorded meanwhile."""


class ClassifyRequest(Frozen):
    """The parsed document to classify: the parse's own request. ``fresh`` reads it again with
    the detector even when it was classified before by the detector (a retry from the classify
    stage)."""

    parse: ParseRequest
    fresh: bool = False


class Classified(Frozen):
    """The document's classification and its route (``domain.classification.Route``):
    ``task_id`` is the triage task a conflict holds the document for; ``created`` says it was
    classified now, its document.classified written; ``extraction_enabled`` is the worker's
    ``CW_PIPELINE_EXTRACTION_ENABLED``."""

    document_id: UUID
    doc_type: str
    relevance: str
    confidence: str
    route: str
    reasons: list[str]
    classifier: str
    task_id: UUID | None = None
    created: bool = False
    extraction_enabled: bool = False

    @property
    def stops(self) -> bool:
        """Whether the ingest ends here: set aside, or held for a person's triage."""
        return Route(self.route).stops

    @property
    def extracts(self) -> bool:
        """Whether the rule extraction reads the document: a rule kind, placed, and the
        extraction on."""
        return Route(self.route) is Route.EXTRACT and self.extraction_enabled


def classified(
    classification: Classification, *, created: bool, extraction_enabled: bool
) -> Classified:
    return Classified(
        document_id=classification.document_id.value,
        doc_type=classification.doc_type.value,
        relevance=classification.relevance.value,
        confidence=classification.confidence.value,
        route=classification.route.value,
        reasons=list(classification.reasons),
        classifier=classification.classifier,
        task_id=None if classification.task_id is None else classification.task_id.value,
        created=created,
        extraction_enabled=extraction_enabled,
    )


class ClassifyDocument(ActivityBase[ClassifyRequest, Classified]):
    """Classify the parsed document and record it, in one transaction with its status, its
    document.classified and, for a conflict, its triage task; a document classified before
    keeps its classification."""

    name: ClassVar[str] = "pipeline.classify_document"
    input_type: ClassVar[type[ClassifyRequest]] = ClassifyRequest
    output_type: ClassVar[type[Classified]] = Classified
    start_to_close: ClassVar[timedelta] = timedelta(minutes=5)
    retry_policy: ClassVar[RetryPolicy] = CLASSIFY_RETRIES

    def __init__(
        self,
        parser: DocumentParsers,
        raw_store: RawStore,
        units: UnitOfWorkFactory,
        *,
        extraction: bool,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._parser = parser
        self._raw = raw_store
        self._units = units
        self._extraction = extraction
        self._clock = clock

    async def run(self, input: ClassifyRequest) -> Classified:
        return await on_thread(self, lambda: self.classify(input.parse, fresh=input.fresh))

    def classify(self, request: ParseRequest, *, fresh: bool = False) -> Classified:
        document_id = DocumentId(request.document_id)
        with self._units() as unit:
            stored = unit.classifications.get(document_id)
        if stored is not None and (not fresh or stored.by_person):
            return classified(stored, created=False, extraction_enabled=self._extraction)
        record, hints = hints_for(request, self._units, self._raw)
        if record is None:
            raise DocumentNotFoundError(f"no stored document has the id {document_id}")
        parsed = parse_request(self._parser, request, self._raw, hints)
        detection = detect(
            parsed,
            own_ref=request.external_ref,
            given_type=record.doc_type,
            listed_title=request.title,
        )
        now = self._clock()
        classification = Classification(
            document_id=document_id,
            doc_type=detection.doc_type,
            relevance=detection.relevance,
            confidence=detection.confidence,
            reasons=detection.reasons,
            classified_at=now,
        )
        if stored is not None:
            return self._read_again(stored, classification, record.source_key, request)
        with self._units() as unit:
            found = unit.classifications.get(document_id)
            if found is not None:
                return classified(found, created=False, extraction_enabled=self._extraction)
            if classification.route is Route.TRIAGE:
                task = unit.tasks.open(
                    PipelineTask.opened(
                        TaskKind.TRIAGE,
                        document_id,
                        record.source_key,
                        at=now,
                        reason=classification.reasons[0][:MAX_REASON_CHARS],
                    )
                )
                classification = dataclasses.replace(classification, task_id=task.id)
            if not unit.classifications.add(classification):
                raise ClassifiedMeanwhileError(
                    f"another ingest classified document {document_id} meanwhile"
                )
            unit.documents.set_status(document_id, classification.route.status)
            unit.events.publish(
                DocumentClassified.of(
                    classification,
                    source_id=SourceId(request.source_id),
                    source_key=record.source_key,
                )
            )
        log.info(
            "pipeline.document_classified",
            document_id=str(document_id),
            doc_type=classification.doc_type.value,
            relevance=classification.relevance.value,
            confidence=classification.confidence.value,
            route=classification.route.value,
            task_id=None if classification.task_id is None else str(classification.task_id),
        )
        return classified(classification, created=True, extraction_enabled=self._extraction)

    def _read_again(
        self,
        stored: Classification,
        fresh: Classification,
        source_key: str,
        request: ParseRequest,
    ) -> Classified:
        """The detector's new reading of a document it classified before: kept as it was when
        it reads the same, else written over the earlier one with the status, a
        document.classified and, for a conflict, the triage task (an open one is kept). A
        person's decision written meanwhile stands."""
        document_id = stored.document_id
        if fresh.same_reading(stored):
            return classified(stored, created=False, extraction_enabled=self._extraction)
        with self._units() as unit:
            current = unit.classifications.get(document_id)
            if current is None or current.by_person or current.same_reading(fresh):
                kept = current or stored
                return classified(kept, created=False, extraction_enabled=self._extraction)
            if fresh.route is Route.TRIAGE:
                task = unit.tasks.open(
                    PipelineTask.opened(
                        TaskKind.TRIAGE,
                        document_id,
                        source_key,
                        at=fresh.classified_at,
                        reason=fresh.reasons[0][:MAX_REASON_CHARS],
                    )
                )
                fresh = dataclasses.replace(fresh, task_id=task.id)
            unit.classifications.save(fresh)
            unit.documents.set_status(document_id, fresh.route.status)
            unit.events.publish(
                DocumentClassified.of(
                    fresh, source_id=SourceId(request.source_id), source_key=source_key
                )
            )
        log.info(
            "pipeline.document_classified_again",
            document_id=str(document_id),
            was=stored.route.value,
            doc_type=fresh.doc_type.value,
            relevance=fresh.relevance.value,
            confidence=fresh.confidence.value,
            route=fresh.route.value,
        )
        return classified(fresh, created=True, extraction_enabled=self._extraction)
