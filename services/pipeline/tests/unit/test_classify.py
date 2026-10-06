"""The classify step: a parsed document's classification, recorded once with its status, its
document.classified and, for a conflict, its triage task.

The documents are synthetic HTML pages stored at the built-in sources (the chain parses them
with html@1), so the opening each is classified by is the one written here."""

from datetime import UTC, datetime

import pytest

from domain_kernel.documents import DocumentRef, DocumentType, RawDocument, document_id_for
from domain_kernel.ids import DocumentId
from pipeline.application.activities import ParseRequest, Stored
from pipeline.application.classify import ClassifyDocument, ClassifyRequest
from pipeline.domain.classification import Classification, Relevance, Route
from pipeline.domain.errors import ClassifiedMeanwhileError, DocumentNotFoundError
from pipeline.domain.events import DocumentClassified
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source
from pipeline.domain.tasks import TaskKind, TaskStatus
from pipeline.infrastructure.adapters import SOURCES, RegistryCatalog, source_id_for
from pipeline.infrastructure.http import PoliteClient
from pipeline.infrastructure.memory import MemoryClassificationRepository, MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.raw_store import MemoryRawStore

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)


def page(title: str, *paragraphs: str) -> bytes:
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    return (
        f"<html><head><title>{title}</title></head><body><h1>{title}</h1>{body}</body></html>"
    ).encode()


NOTIFICATION = page(
    "Notification No. 99/2026 - Central Tax",
    "In exercise of the powers conferred by section 39, the Commissioner extends the due date "
    "of an example return.",
)
CIRCULAR = page(
    "Circular No. 5/2026-GST",
    "Subject: Example clarification on Notification No. 12/2024 - Central Tax.",
)
MANUAL = page("Reset Password User Manual", "Step 1: open the portal.")


class Pipeline:
    """A memory store with the built-in sources, the raw store and the chain."""

    def __init__(self, *, extraction: bool = True) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.chain = ParserChain(RegistryCatalog(PoliteClient()))
        with self.store() as unit:
            for spec in SOURCES.values():
                unit.sources.add(Source.of(spec.definition(), NOW))
        self.activity = ClassifyDocument(
            self.chain, self.raw, self.store, extraction=extraction, clock=lambda: NOW
        )

    def stored(
        self, content: bytes, *, key: str = "cbic_notifications", **record: object
    ) -> ParseRequest:
        """What an upload stores, parsed: the bytes, the record set parsed, the request."""
        ref = DocumentRef(source_id_for(key), "upload://example", "")
        raw = RawDocument.from_bytes(ref, content, "text/html", NOW)
        storage_key = self.raw.put(raw)
        document_id = document_id_for(raw.sha256)
        values: dict[str, object] = {
            "document_id": document_id,
            "source_key": key,
            "source_url": f"upload://{key}/{raw.sha256}",
            "fetched_at": NOW,
            "content_type": raw.media_type,
            "size": len(content),
            "sha256": raw.sha256,
            "storage_key": storage_key,
            "status": DocumentStatus.PARSED,
            "parser_version": "html@1",
        }
        values.update(record)
        with self.store() as unit:
            unit.documents.add(RawDocumentRecord(**values))  # type: ignore[arg-type]
        return ParseRequest(
            document_id=document_id.value,
            stored=Stored(
                document_id=document_id.value,
                source_id=source_id_for(key).value,
                source_key=key,
                regulator="CBIC",
                url=f"upload://{key}/{raw.sha256}",
                media_type=raw.media_type,
                sha256=raw.sha256,
                size=len(content),
                fetched_at=NOW,
                storage_key=storage_key,
                raw_uri=self.raw.uri(storage_key),
            ),
        )

    async def classify(self, request: ParseRequest) -> tuple[Route, DocumentStatus]:
        found = await self.activity.run(ClassifyRequest(parse=request))
        status = self.store.documents[DocumentId(request.document_id)].status
        return Route(found.route), status

    def events(self) -> list[DocumentClassified]:
        return [e for e in self.store.events if isinstance(e, DocumentClassified)]


async def test_a_notification_its_source_publishes_goes_on_to_the_extraction() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(NOTIFICATION)
    found = await pipeline.activity.run(ClassifyRequest(parse=request))
    assert (found.route, found.doc_type, found.confidence, found.relevance) == (
        "extract",
        "notification",
        "certain",
        "relevant",
    )
    assert (found.created, found.stops, found.extracts, found.task_id) == (
        True,
        False,
        True,
        None,
    )
    (event,) = pipeline.events()
    assert (event.doc_type, event.source_key, event.classifier) == (
        DocumentType.NOTIFICATION,
        "cbic_notifications",
        "detector@1",
    )
    assert event.reasons == tuple(found.reasons)
    record = pipeline.store.documents[DocumentId(request.document_id)]
    assert record.status is DocumentStatus.CLASSIFIED
    assert pipeline.store.tasks == {}


async def test_with_the_extraction_off_a_classified_document_waits() -> None:
    pipeline = Pipeline(extraction=False)
    found = await pipeline.activity.run(ClassifyRequest(parse=pipeline.stored(NOTIFICATION)))
    assert (found.route, found.extracts, found.extraction_enabled) == ("extract", False, False)


async def test_a_conflict_opens_a_triage_task_with_its_classification_and_event() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(CIRCULAR)
    found = await pipeline.activity.run(ClassifyRequest(parse=request))
    assert (found.route, found.doc_type, found.confidence, found.stops) == (
        "triage",
        "circular",
        "conflict",
        True,
    )
    (task,) = pipeline.store.tasks.values()
    assert (task.id.value, task.kind, task.status) == (
        found.task_id,
        TaskKind.TRIAGE,
        TaskStatus.OPEN,
    )
    assert task.reason == (
        "its opening names it a circular, but its source publishes the type notification"
    )
    (event,) = pipeline.events()
    assert event.task_id == task.id
    assert pipeline.store.documents[DocumentId(request.document_id)].status is (
        DocumentStatus.TRIAGE
    )
    stored = pipeline.store.classifications[DocumentId(request.document_id)]
    assert stored.task_id == task.id


@pytest.mark.parametrize(
    ("content", "key", "record", "route", "status"),
    [
        (MANUAL, "cbic_notifications", {}, Route.IRRELEVANT, DocumentStatus.IRRELEVANT),
        (NOTIFICATION, "gstcouncil_press", {}, Route.TRIAGE, DocumentStatus.TRIAGE),
        (
            page("Example press release", "The Council met."),
            "gstcouncil_press",
            {},
            Route.REFERENCE,
            DocumentStatus.REFERENCE,
        ),
        (NOTIFICATION, "cgst_rules", {}, Route.REFERENCE, DocumentStatus.REFERENCE),
        (
            CIRCULAR,
            "cbic_notifications",
            {"doc_type": DocumentType.STATUTE},
            Route.REFERENCE,
            DocumentStatus.REFERENCE,
        ),
        (
            CIRCULAR,
            "cbic_notifications",
            {"doc_type": DocumentType.CIRCULAR},
            Route.EXTRACT,
            DocumentStatus.CLASSIFIED,
        ),
    ],
    ids=[
        "user-manual",
        "notification-among-press-releases",
        "press-release",
        "statute-source",
        "uploaded-as-statute",
        "uploaded-as-circular",
    ],
)
async def test_where_each_document_goes(
    content: bytes,
    key: str,
    record: dict[str, object],
    route: Route,
    status: DocumentStatus,
) -> None:
    pipeline = Pipeline()
    assert await pipeline.classify(pipeline.stored(content, key=key, **record)) == (route, status)
    (event,) = pipeline.events()
    assert event.source_key == key


async def test_a_document_classified_before_keeps_its_classification() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(CIRCULAR)
    first = await pipeline.activity.run(ClassifyRequest(parse=request))
    again = await pipeline.activity.run(ClassifyRequest(parse=request))
    assert again.created is False
    assert again.model_dump(exclude={"created"}) == first.model_dump(exclude={"created"})
    assert len(pipeline.events()) == 1
    assert len(pipeline.store.tasks) == 1, "a retry opens no second task"


async def test_a_triage_decision_stands_for_a_later_ingest() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(CIRCULAR)
    await pipeline.activity.run(ClassifyRequest(parse=request))
    task = next(iter(pipeline.store.tasks.values()))
    decided = Classification.triaged(
        DocumentId(request.document_id),
        relevance=Relevance.RELEVANT,
        doc_type=DocumentType.CIRCULAR,
        by=None,
        task_id=task.id,
        at=NOW,
        reason="Read the text: it clarifies the law",
    )
    with pipeline.store() as unit:
        unit.classifications.save(decided)
    again = await pipeline.activity.run(ClassifyRequest(parse=request))
    assert (again.route, again.confidence, again.classifier, again.created) == (
        "extract",
        "certain",
        "triage",
        False,
    )


async def test_a_document_nobody_stored_is_refused() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(NOTIFICATION)
    pipeline.store.documents.clear()
    with pytest.raises(DocumentNotFoundError):
        await pipeline.activity.run(ClassifyRequest(parse=request))


async def test_a_classification_another_ingest_recorded_meanwhile_rolls_this_one_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = Pipeline()
    request = pipeline.stored(CIRCULAR)
    monkeypatch.setattr(MemoryClassificationRepository, "add", lambda self, found: False)
    with pytest.raises(ClassifiedMeanwhileError):
        await pipeline.activity.run(ClassifyRequest(parse=request))
    assert (pipeline.store.tasks, pipeline.events()) == ({}, [])
    assert pipeline.store.documents[DocumentId(request.document_id)].status is (
        DocumentStatus.PARSED
    )
