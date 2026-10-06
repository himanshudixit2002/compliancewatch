"""The classify step: a parsed document's classification, recorded once with its status, its
document.classified and, for a conflict, its triage task.

The documents are synthetic HTML pages (and one synthetic PDF) stored at the built-in sources
(the chain parses them with html@1 and pdf@1), so the opening each is classified by is the one
written here."""

from datetime import UTC, datetime
from typing import Any

import pytest

from domain_kernel.documents import DocumentRef, DocumentType, RawDocument, document_id_for
from domain_kernel.ids import DocumentId
from pipeline.application.activities import ParseRequest, Stored
from pipeline.application.classify import ClassifyDocument, ClassifyRequest
from pipeline.domain.classification import Classification, Relevance, Route, TypeConfidence
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


def text_pdf(*pages: str) -> bytes:
    """A PDF with a text layer: one line of Helvetica on each page."""
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(len(pages)))
    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, line in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 770 Td ({line}) Tj ET".encode()
        bodies.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * index} 0 R >>".encode()
        )
        bodies.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(bodies, 1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(bodies) + 1,
        xref,
    )
    return bytes(pdf)


PORTAL_MANUAL = text_pdf(
    "User Manual",
    "Login to the portal and open the returns dashboard to file FORM GSTR-1.",
)
"""A portal manual whose cover line, 11 characters, is too short to be the PDF's title: the
parse titles it by the next line, which does not read as a manual."""


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
        self,
        content: bytes,
        *,
        key: str = "cbic_notifications",
        media_type: str = "text/html",
        title: str = "",
        **record: object,
    ) -> ParseRequest:
        """What an upload stores, parsed: the bytes, the record set parsed, the request, with the
        title the document is listed under."""
        ref = DocumentRef(source_id_for(key), "upload://example", "")
        raw = RawDocument.from_bytes(ref, content, media_type, NOW)
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
            "title": title,
            "status": DocumentStatus.PARSED,
            "parser_version": "html@1",
        }
        values.update(record)
        with self.store() as unit:
            unit.documents.add(RawDocumentRecord(**values))  # type: ignore[arg-type]
        return ParseRequest(
            document_id=document_id.value,
            title=title,
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
    record: dict[str, Any],
    route: Route,
    status: DocumentStatus,
) -> None:
    pipeline = Pipeline()
    assert await pipeline.classify(pipeline.stored(content, key=key, **record)) == (route, status)
    (event,) = pipeline.events()
    assert event.source_key == key


async def test_a_user_manual_is_irrelevant_by_the_title_it_is_listed_under() -> None:
    listed = "User Manual for filing FORM GSTR-1 on the portal"
    pipeline = Pipeline()
    request = pipeline.stored(
        PORTAL_MANUAL, media_type="application/pdf", title=listed, parser_version="pdf@1"
    )
    assert await pipeline.classify(request) == (Route.IRRELEVANT, DocumentStatus.IRRELEVANT)
    (event,) = pipeline.events()
    assert event.reasons[1] == (
        "its title reads as a user manual or a how-to guide for the portal, not a regulator's "
        "document"
    )
    unlisted = Pipeline()
    by_its_parse = unlisted.stored(
        PORTAL_MANUAL, media_type="application/pdf", parser_version="pdf@1"
    )
    assert await unlisted.classify(by_its_parse) == (Route.EXTRACT, DocumentStatus.CLASSIFIED), (
        "the parse's own title, the line after the cover, reads as no manual"
    )


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


# ---------------------------------------------------------------- a retry's fresh reading


def earlier(request: ParseRequest, **values: Any) -> Classification:
    """A classification stored before, as an older detector read the document."""
    defaults: dict[str, Any] = {
        "document_id": DocumentId(request.document_id),
        "doc_type": DocumentType.NOTIFICATION,
        "relevance": Relevance.IRRELEVANT,
        "confidence": TypeConfidence.CERTAIN,
        "reasons": ("an older detector read its title as a user manual",),
        "classified_at": NOW,
    }
    defaults.update(values)
    return Classification(**defaults)


def store_earlier(
    pipeline: Pipeline, classification: Classification, status: DocumentStatus
) -> None:
    with pipeline.store() as unit:
        unit.classifications.add(classification)
        unit.documents.set_status(classification.document_id, status)


async def test_a_fresh_reading_replaces_the_detectors_earlier_one() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(NOTIFICATION, title="Notification No. 99/2026 - Central Tax")
    store_earlier(pipeline, earlier(request), DocumentStatus.IRRELEVANT)
    kept = await pipeline.activity.run(ClassifyRequest(parse=request))
    assert (kept.route, kept.created) == ("irrelevant", False), "kept unless read fresh"
    found = await pipeline.activity.run(ClassifyRequest(parse=request, fresh=True))
    assert (found.route, found.relevance, found.created) == ("extract", "relevant", True)
    document_id = DocumentId(request.document_id)
    assert pipeline.store.documents[document_id].status is DocumentStatus.CLASSIFIED
    assert pipeline.store.classifications[document_id].relevance is Relevance.RELEVANT
    assert [e.relevance for e in pipeline.events()] == [Relevance.RELEVANT]
    again = await pipeline.activity.run(ClassifyRequest(parse=request, fresh=True))
    assert (again.route, again.created) == ("extract", False), "the same reading writes nothing"
    assert len(pipeline.events()) == 1


async def test_a_fresh_reading_never_replaces_a_persons_decision() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(MANUAL, title="Reset Password User Manual")
    given = Classification.given(
        DocumentId(request.document_id),
        doc_type=DocumentType.CIRCULAR,
        by=None,
        at=NOW,
        reason="Example: an analyst read it as a circular",
    )
    store_earlier(pipeline, given, DocumentStatus.CLASSIFIED)
    found = await pipeline.activity.run(ClassifyRequest(parse=request, fresh=True))
    assert (found.route, found.doc_type, found.classifier, found.created) == (
        "extract",
        "circular",
        "retry",
        False,
    )
    assert pipeline.events() == []


async def test_a_fresh_conflict_opens_its_triage_task() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(CIRCULAR, title="Circular No. 5/2026-GST")
    store_earlier(pipeline, earlier(request), DocumentStatus.IRRELEVANT)
    found = await pipeline.activity.run(ClassifyRequest(parse=request, fresh=True))
    assert (found.route, found.created) == ("triage", True)
    (task,) = pipeline.store.tasks.values()
    assert (task.kind, task.status, found.task_id) == (
        TaskKind.TRIAGE,
        TaskStatus.OPEN,
        task.id.value,
    )
    assert pipeline.store.documents[DocumentId(request.document_id)].status is DocumentStatus.TRIAGE


async def test_a_person_deciding_while_the_detector_reads_again_stands() -> None:
    pipeline = Pipeline()
    request = pipeline.stored(NOTIFICATION, title="Notification No. 99/2026 - Central Tax")
    stored = earlier(request)
    store_earlier(pipeline, stored, DocumentStatus.IRRELEVANT)
    given = Classification.given(
        stored.document_id,
        doc_type=DocumentType.CIRCULAR,
        by=None,
        at=NOW,
        reason="Example: an analyst decided meanwhile",
    )
    fresh = earlier(request, relevance=Relevance.RELEVANT)
    with pipeline.store() as unit:
        unit.classifications.save(given)
    found = pipeline.activity._read_again(stored, fresh, "cbic_notifications", request)
    assert (found.classifier, found.created) == ("retry", False)
