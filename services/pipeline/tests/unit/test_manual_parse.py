"""The parse of a stored document as its record says, and a manual parse.

``pipeline.parse_document`` records the parser on the document with its document.parsed, parses
the document the way it parsed it before, as the type its uploader gave, and from its transcript
once an analyst typed one; ``pipeline.open_manual_parse`` sets a document no parser reads failed
and opens one task for it; ``pipeline.register_document`` sends the clauses the parse gave."""

import base64
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pypdf import PdfWriter

from domain_kernel.documents import (
    DocumentRef,
    DocumentType,
    ParsedDocument,
    RawDocument,
    document_id_for,
)
from domain_kernel.ids import DocumentId
from pipeline.application.activities import (
    OpenManualParse,
    ParseDocument,
    ParseFailure,
    ParseRequest,
    Stored,
)
from pipeline.application.knowledge_activities import RegisterDocument, RegisterRequest
from pipeline.domain.errors import DocumentNotFoundError, UnparsedDocumentError
from pipeline.domain.events import DocumentParsed
from pipeline.domain.ports import ParseHints
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source
from pipeline.domain.tasks import PipelineTask, TaskKind, TaskStatus
from pipeline.domain.transcripts import TRANSCRIPT_MEDIA_TYPE, read_transcript
from pipeline.infrastructure.adapters import SOURCES, RegistryCatalog, source_id_for
from pipeline.infrastructure.http import PoliteClient
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain, PdfParser
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.testing import MemoryRulebook

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
KEY = "cbic_notifications"
TRANSCRIPT = read_transcript(
    {
        "title": "Example transcribed notice",
        "blocks": [
            {"type": "heading", "text": "Example heading"},
            {"type": "paragraph", "number": "1.", "text": "Example transcribed text."},
            {"type": "table", "rows": [["1", "Example item", "5%"]]},
        ],
    }
)


def table_notification() -> bytes:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-10-2025.pdf.json").read_text())
    return base64.b64decode(wrapper["data"])


def scan() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class Pipeline:
    """A memory store holding one stored document of ``cbic_notifications``, and the chain."""

    def __init__(self, content: bytes, **record: object) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.chain = ParserChain(RegistryCatalog(PoliteClient()))
        ref = DocumentRef(source_id_for(KEY), "https://example.invalid/notice.pdf", "10/2025")
        raw = RawDocument.from_bytes(ref, content, "application/pdf", NOW)
        self.key = self.raw.put(raw)
        self.document_id = document_id_for(raw.sha256)
        values: dict[str, object] = {
            "document_id": self.document_id,
            "source_key": KEY,
            "source_url": ref.url,
            "fetched_at": NOW,
            "content_type": raw.media_type,
            "size": len(content),
            "sha256": raw.sha256,
            "storage_key": self.key,
            "external_ref": "10/2025",
        }
        values.update(record)
        with self.store() as unit:
            unit.sources.add(Source.of(SOURCES[KEY].definition(), NOW))
            unit.documents.add(RawDocumentRecord(**values))  # type: ignore[arg-type]
        self.stored = Stored(
            document_id=self.document_id.value,
            source_id=source_id_for(KEY).value,
            source_key=KEY,
            regulator="CBIC",
            url=ref.url,
            external_ref="10/2025",
            media_type=raw.media_type,
            sha256=raw.sha256,
            size=len(content),
            fetched_at=NOW,
            storage_key=self.key,
            raw_uri=self.raw.uri(self.key),
        )

    def request(self, **overrides: object) -> ParseRequest:
        values: dict[str, object] = {"document_id": self.stored.document_id, "stored": self.stored}
        values.update(overrides)
        return ParseRequest.model_validate(values)

    def parse(self) -> ParseDocument:
        return ParseDocument(self.chain, self.raw, units=self.store, clock=lambda: NOW)

    def record(self) -> RawDocumentRecord:
        found = self.store.documents[self.document_id]
        return found

    def transcript_key(self) -> str:
        ref = DocumentRef(source_id_for(KEY), "transcript:example")
        return self.raw.put(
            RawDocument.from_bytes(ref, TRANSCRIPT.encoded(), TRANSCRIPT_MEDIA_TYPE)
        )


async def test_a_parse_is_recorded_once_with_its_document_parsed() -> None:
    pipeline = Pipeline(table_notification())
    parsed = await pipeline.parse().run(pipeline.request(title="Notification No. 10/2025"))
    assert parsed.parser_version == "pdf-tables@1"
    record = pipeline.record()
    assert (record.status, record.parser_version) == (DocumentStatus.PARSED, "pdf-tables@1")
    (event,) = pipeline.store.events
    assert isinstance(event, DocumentParsed)
    assert (event.title, event.parser_version, event.clause_count) == (
        "Notification No. 10/2025",
        "pdf-tables@1",
        parsed.clause_count,
    )
    assert list(event.clause_refs) == parsed.clause_refs
    again = await pipeline.parse().run(pipeline.request())
    assert again == parsed
    assert len(pipeline.store.events) == 1, "nothing changed, nothing announced"


async def test_a_document_pdf_1_parsed_before_is_parsed_by_it_again() -> None:
    pipeline = Pipeline(table_notification(), parser_version="pdf@1")
    parsed = await pipeline.parse().run(pipeline.request())
    assert parsed.parser_version == "pdf@1"
    assert parsed.clause_count == len(PdfParser().parse(_raw(table_notification())).clauses)


async def test_an_uploaded_type_wins_over_the_sources() -> None:
    pipeline = Pipeline(table_notification(), doc_type=DocumentType.STATUTE)
    parsed = await pipeline.parse().run(pipeline.request())
    assert parsed.doc_type == "statute"


async def test_a_transcript_is_parsed_recorded_and_used_from_then_on() -> None:
    pipeline = Pipeline(scan())
    key = pipeline.transcript_key()
    parsed = await pipeline.parse().run(pipeline.request(transcript_key=key))
    assert (parsed.parser_version, parsed.clause_count) == ("manual@1", 3)
    record = pipeline.record()
    assert (record.parser_version, record.transcript_key) == ("manual@1", key)
    again = await pipeline.parse().run(pipeline.request())
    assert again == parsed, "the record names the transcript"


async def test_a_parse_closes_the_manual_parse_it_makes_needless() -> None:
    pipeline = Pipeline(table_notification(), status=DocumentStatus.FAILED)
    waiting = PipelineTask.opened(TaskKind.MANUAL_PARSE, pipeline.document_id, KEY, at=NOW)
    with pipeline.store() as unit:
        unit.tasks.open(waiting)
    await pipeline.parse().run(pipeline.request())
    closed = pipeline.store.tasks[waiting.id]
    assert (closed.status, closed.resolved_by, closed.note) == (
        TaskStatus.RESOLVED,
        None,
        "parsed by pdf-tables@1",
    )


async def test_a_scan_fails_the_parse_and_records_nothing() -> None:
    pipeline = Pipeline(scan())
    with pytest.raises(UnparsedDocumentError, match="no text layer"):
        await pipeline.parse().run(pipeline.request())
    assert pipeline.record().status is DocumentStatus.DISCOVERED
    assert pipeline.store.events == []


async def test_a_document_no_parser_reads_gets_one_manual_parse_task() -> None:
    pipeline = Pipeline(scan())
    activity = OpenManualParse(pipeline.store, clock=lambda: NOW)
    failure = ParseFailure(document_id=pipeline.document_id.value, reason="pdf@1: no text layer")
    first = await activity.run(failure)
    again = await activity.run(failure)
    assert (first.created, again.created, again.task_id) == (True, False, first.task_id)
    (task,) = pipeline.store.tasks.values()
    assert (task.kind, task.status, task.reason, task.source_key) == (
        TaskKind.MANUAL_PARSE,
        TaskStatus.OPEN,
        "pdf@1: no text layer",
        KEY,
    )
    assert pipeline.record().status is DocumentStatus.FAILED


async def test_a_parsed_or_unknown_document_opens_no_task() -> None:
    pipeline = Pipeline(table_notification(), status=DocumentStatus.PARSED)
    activity = OpenManualParse(pipeline.store, clock=lambda: NOW)
    nothing = await activity.run(ParseFailure(document_id=pipeline.document_id.value))
    assert (nothing.task_id, nothing.created) == (None, False)
    assert pipeline.store.tasks == {}
    with pytest.raises(DocumentNotFoundError):
        await activity.run(ParseFailure(document_id=DocumentId.new().value))


async def test_registration_sends_the_parse_the_record_names() -> None:
    pipeline = Pipeline(table_notification(), parser_version="pdf@1")
    rulebook = MemoryRulebook()
    register = RegisterDocument(
        pipeline.chain, rulebook, enabled=True, raw_store=pipeline.raw, units=pipeline.store
    )
    outcome = await register.run(
        RegisterRequest(parse=pipeline.request(published_at=date(2025, 3, 13)), regulator="CBIC")
    )
    assert (outcome.created, outcome.parser_version) == (True, "pdf@1")
    record = rulebook.records[pipeline.document_id]
    assert record.document.parser_version == "pdf@1"
    assert record.document.clauses == PdfParser().parse(_raw(table_notification())).clauses


def test_hints_name_what_the_chain_is_given() -> None:
    pipeline = Pipeline(scan(), doc_type=DocumentType.STATUTE, parser_version="pdf@1")
    seen: list[ParseHints] = []

    class Spy:
        def parse_as(self, raw: RawDocument, hints: ParseHints) -> ParsedDocument:
            seen.append(hints)
            raise UnparsedDocumentError("spy")

    with pytest.raises(UnparsedDocumentError):
        ParseDocument(Spy(), pipeline.raw, units=pipeline.store)._parse(pipeline.request())
    assert seen == [ParseHints(doc_type=DocumentType.STATUTE, parser_version="pdf@1")]


def _raw(content: bytes) -> RawDocument:
    ref = DocumentRef(source_id_for(KEY), "https://example.invalid/notice.pdf")
    return RawDocument.from_bytes(ref, content, "application/pdf", NOW)
