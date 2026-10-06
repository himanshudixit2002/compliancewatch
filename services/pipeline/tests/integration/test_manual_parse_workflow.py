"""The ingest on a local Temporal dev server with the parser chain: a document no parser reads
opens a manual-parse task and is never registered; an upload's ingest starts from the stored
document; the ingest a resolution starts parses the analyst's transcript as manual@1, and a
statute is registered and embedded but not extracted. Each new history replays on the workflow.
The histories recorded before these paths are in tests/unit/test_workflow_replay.py."""

import base64
import io
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer

from domain_kernel.documents import DiscoveredDocument, DocumentRef, DocumentType, RawDocument
from domain_kernel.ids import DocumentId, SourceId
from pipeline.application.activities import Discovered, Stored
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.domain.ports import ResolvedSource
from pipeline.domain.prompt import PromptText
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source
from pipeline.domain.tasks import TaskKind, TaskStatus
from pipeline.domain.transcripts import TRANSCRIPT_MEDIA_TYPE, read_transcript
from pipeline.infrastructure.fakes import SAMPLE_SOURCE, FakeSourceAdapter, StaticCatalog
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.settings import PipelineSettings
from pipeline.testing import MemoryRulebook, ScriptedEmbedder, ScriptedProvider
from pipeline.worker import activities
from pipeline.workflows import (
    ExtractKnowledgeWorkflow,
    IngestDocumentWorkflow,
    IngestRequest,
    IngestResult,
)
from pipeline.workflows.ingest_document import PARSE_PATCH, STORE_PATCH, STORED_PATCH
from py_common.temporal.client import default_interceptors
from py_common.temporal.worker import WorkerConfig, build_worker

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SOURCE = SourceId(uuid.UUID(int=1))
NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
SCAN_URL = "https://example.invalid/notifications/19-2026-scanned"
KNOWLEDGE = PipelineSettings(
    _env_file=None, service_name="pipeline-worker", pipeline_knowledge_enabled=True
)
TRANSCRIPT = read_transcript(
    {
        "title": "Example statute",
        "blocks": [
            {"type": "heading", "text": "Example chapter"},
            {"type": "paragraph", "number": "1.", "text": "Example text of the first section."},
            {"type": "table", "header": ["Example", "Rate"], "rows": [["Example item", "5%"]]},
        ],
    }
)


@pytest.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter, interceptors=default_interceptors()
    ) as env:
        yield env


def scan() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def table_notification() -> bytes:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-10-2025.pdf.json").read_text())
    return base64.b64decode(wrapper["data"])


class Pipeline:
    """Memory stores, the sample source serving ``documents``, the chain, a rulebook."""

    def __init__(self, *documents: tuple[str, str, bytes]) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.rulebook = MemoryRulebook()
        self.embedder = ScriptedEmbedder()
        listed = tuple(
            (DiscoveredDocument(DocumentRef(SOURCE, url, ref)), content, "application/pdf")
            for url, ref, content in documents
        )
        adapter = FakeSourceAdapter(SOURCE, listed)
        self.catalog = StaticCatalog.of(ResolvedSource(SOURCE, SAMPLE_SOURCE, adapter))
        with self.store() as unit:
            unit.sources.add(Source.of(SAMPLE_SOURCE, NOW))

    def store_upload(self, content: bytes, **record: object) -> Stored:
        """What an upload does before it starts the ingest: the bytes in the raw store and the
        record in the store."""
        ref = DocumentRef(SOURCE, f"upload://sample/{uuid.uuid4().hex}")
        raw = RawDocument.from_bytes(ref, content, "application/pdf", NOW)
        key = self.raw.put(raw)
        values: dict[str, object] = {
            "document_id": DocumentId(uuid.UUID(raw.sha256[:32])),
            "source_key": SAMPLE_SOURCE.key,
            "source_url": ref.url,
            "fetched_at": NOW,
            "content_type": raw.media_type,
            "size": len(content),
            "sha256": raw.sha256,
            "storage_key": key,
            "title": "Example upload",
        }
        values.update(record)
        with self.store() as unit:
            unit.documents.add(RawDocumentRecord(**values))  # type: ignore[arg-type]
        return Stored(
            document_id=uuid.UUID(raw.sha256[:32]),
            source_id=SOURCE.value,
            source_key=SAMPLE_SOURCE.key,
            regulator="CBIC",
            url=ref.url,
            media_type=raw.media_type,
            sha256=raw.sha256,
            size=len(content),
            fetched_at=NOW,
            storage_key=key,
            raw_uri=self.raw.uri(key),
            title="Example upload",
        )

    def transcript_key(self) -> str:
        ref = DocumentRef(SOURCE, "transcript:example")
        return self.raw.put(
            RawDocument.from_bytes(ref, TRANSCRIPT.encoded(), TRANSCRIPT_MEDIA_TYPE)
        )

    async def ingest(
        self, environment: WorkflowEnvironment, request: IngestRequest
    ) -> tuple[IngestResult, WorkflowHistory]:
        prompt = PromptText("extraction.rule_relations", "1", "regulatory-intelligence", "Relate.")
        stage = RelationStage(
            LlmRelationExtractor(ScriptedProvider({}, default='{"relations": []}'), prompt)
        )
        wired = activities(
            KNOWLEDGE,
            sink=self.rulebook,
            stage=stage,
            embedder=self.embedder,
            sources=self.catalog,
            parser=ParserChain(self.catalog),
            units=self.store,
            raw_store=self.raw,
        )
        task_queue = f"pipeline-test-{uuid.uuid4().hex[:8]}"
        worker = build_worker(
            environment.client,
            WorkerConfig(task_queue=task_queue),
            workflows=[IngestDocumentWorkflow, ExtractKnowledgeWorkflow],
            activities=wired,
        )
        async with worker:
            handle = await environment.client.start_workflow(
                IngestDocumentWorkflow.run,
                request,
                id=f"ingest-{uuid.uuid4()}",
                task_queue=task_queue,
            )
            result = await handle.result()
            return result, await handle.fetch_history()


def events(history: WorkflowHistory) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = json.loads(history.to_json())["events"]
    return found


def scheduled(history: WorkflowHistory) -> list[str]:
    return [
        event["activityTaskScheduledEventAttributes"]["activityType"]["name"]
        for event in events(history)
        if "activityTaskScheduledEventAttributes" in event
    ]


def patches(history: WorkflowHistory) -> list[str]:
    found: list[str] = []
    for event in events(history):
        details = event.get("markerRecordedEventAttributes", {}).get("details", {})
        for payloads in details.values():
            for payload in payloads.get("payloads", []):
                item = json.loads(base64.b64decode(payload["data"]))
                if isinstance(item, dict) and "id" in item:
                    found.append(str(item["id"]))
    return found


async def replays(history: WorkflowHistory) -> None:
    replayer = Replayer(
        workflows=[IngestDocumentWorkflow, ExtractKnowledgeWorkflow],
        data_converter=pydantic_data_converter,
    )
    replayed = await replayer.replay_workflow(history)
    assert replayed.replay_failure is None


def children(history: WorkflowHistory) -> Sequence[str]:
    return [
        event["startChildWorkflowExecutionInitiatedEventAttributes"]["workflowType"]["name"]
        for event in events(history)
        if "startChildWorkflowExecutionInitiatedEventAttributes" in event
    ]


async def test_a_document_no_parser_reads_opens_a_task_and_is_not_registered(
    environment: WorkflowEnvironment,
) -> None:
    pipeline = Pipeline((SCAN_URL, "19/2026", scan()))
    request = IngestRequest(
        source_id=SOURCE.value,
        discovered=Discovered(source_id=SOURCE.value, url=SCAN_URL, external_ref="19/2026"),
        knowledge=True,
        regulator="CBIC",
    )
    result, history = await pipeline.ingest(environment, request)
    assert (result.parse_failed, result.registered, result.clause_count) == (True, False, 0)
    assert result.task_id is not None
    (task,) = pipeline.store.tasks.values()
    assert (task.id.value, task.kind, task.status) == (
        result.task_id,
        TaskKind.MANUAL_PARSE,
        TaskStatus.OPEN,
    )
    assert task.reason.startswith("UnparsedDocumentError: pdf@1: UnparsedDocumentError")
    (record,) = pipeline.store.documents.values()
    assert record.status is DocumentStatus.FAILED
    assert (pipeline.rulebook.calls, pipeline.rulebook.records) == (0, {})
    assert scheduled(history) == [
        "pipeline.fetch_and_store",
        "pipeline.parse_document",
        "pipeline.open_manual_parse",
    ]
    assert PARSE_PATCH in patches(history)
    await replays(history)

    again, _ = await pipeline.ingest(environment, request)
    assert (again.parse_failed, again.task_id, again.duplicate) == (True, result.task_id, True)
    assert len(pipeline.store.tasks) == 1, "the open task is found, not opened twice"


async def test_an_upload_ingests_from_the_stored_document(
    environment: WorkflowEnvironment,
) -> None:
    pipeline = Pipeline()
    stored = pipeline.store_upload(table_notification())
    result, history = await pipeline.ingest(
        environment,
        IngestRequest(source_id=SOURCE.value, stored=stored, knowledge=True, regulator="CBIC"),
    )
    assert (result.parse_failed, result.registered, result.parser_version) == (
        False,
        True,
        "pdf-tables@1",
    )
    assert result.storage_key == stored.storage_key
    assert scheduled(history)[:2] == ["pipeline.parse_document", "pipeline.register_document"]
    assert "pipeline.fetch_and_store" not in scheduled(history)
    assert STORED_PATCH in patches(history)
    assert STORE_PATCH not in patches(history)
    record = pipeline.rulebook.records[DocumentId(stored.document_id)]
    assert (record.document.parser_version, record.document.title) == (
        "pdf-tables@1",
        "Example upload",
    )
    assert pipeline.store.documents[DocumentId(stored.document_id)].status is DocumentStatus.PARSED
    await replays(history)


async def test_a_resolutions_ingest_registers_the_transcript_of_a_statute(
    environment: WorkflowEnvironment,
) -> None:
    pipeline = Pipeline()
    stored = pipeline.store_upload(
        scan(), doc_type=DocumentType.STATUTE, status=DocumentStatus.FAILED
    )
    key = pipeline.transcript_key()
    result, history = await pipeline.ingest(
        environment,
        IngestRequest(
            source_id=SOURCE.value,
            stored=stored,
            transcript_key=key,
            knowledge=True,
            regulator="CBIC",
        ),
    )
    assert (result.registered, result.parser_version, result.clause_count) == (
        True,
        "manual@1",
        4,
    )
    record = pipeline.rulebook.records[DocumentId(stored.document_id)]
    assert record.document.doc_type is DocumentType.STATUTE
    assert [c.text for c in record.document.clauses][-1] == "Example item | 5%"
    assert result.clauses_embedded == 4, "a statute is embedded"
    assert (result.relations_outcome, children(history)) == ("disabled", []), "never extracted"
    stored_record = pipeline.store.documents[DocumentId(stored.document_id)]
    assert (stored_record.status, stored_record.transcript_key) == (DocumentStatus.PARSED, key)
    await replays(history)
