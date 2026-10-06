"""The classified backlog swept on a local Temporal dev server.

The recorded notification 01/2026-Central Tax and a synthetic notification are ingested while the
worker's extraction is off: both are classified, registered in a memory rulebook and left waiting
as ``classified``. A sweep while the worker's extraction is still off asks the worker first and
starts nothing, so no extraction id is used. With the extraction on, the backlog command's sweep
extracts both as children (the recorded one from a scripted model answering the draft label of
its golden case, nobody reviewed it: it shows the plumbing, not the law; the synthetic one from a
model whose answer is no candidate) and fails a document the rulebook does not hold. A second
sweep finds the extracted ones done and asks no model again. A child that a worker with the
extraction off ran anyway (its check said on) counts as disabled, not as running. The sweeps'
histories replay."""

import base64
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from domain_kernel.documents import DocumentRef, DocumentType, RawDocument
from domain_kernel.ids import DocumentId
from ontology import load as load_ontology
from pipeline.application.activities import Stored
from pipeline.application.backlog import ExtractionBacklog
from pipeline.application.extraction import (
    RULE_PROMPT,
    RULE_PROMPT_REF,
    CheckExtraction,
    ExtractionRequest,
    RuleExtractionStage,
)
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.domain.extraction import extraction_workflow_id
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source
from pipeline.infrastructure.adapters import (
    SOURCES,
    RegistryAdapterTypes,
    RegistryCatalog,
    source_id_for,
)
from pipeline.infrastructure.http import PoliteClient
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.prompts import load_prompt
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.label import load_case
from pipeline.settings import PipelineSettings
from pipeline.testing import MemoryRulebook, ScriptedEmbedder, ScriptedProvider
from pipeline.worker import activities
from pipeline.workflows import (
    BacklogRequest,
    BacklogResult,
    ExtractBacklogWorkflow,
    ExtractKnowledgeWorkflow,
    ExtractRulesWorkflow,
    IngestDocumentWorkflow,
    IngestRequest,
)
from py_common.temporal.client import default_interceptors

REPO = Path(__file__).resolve().parents[4]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CASE = load_case(REPO / "evals/golden/extraction/cbic_notifications/cases/01-2026-central-tax.yaml")
NOW = datetime(2000, 1, 3, 6, 0, tzinfo=UTC)
SYNTHETIC = (
    b"<html><head><title>Notification No. 1/2000-Central Tax</title></head><body>"
    b"<h1>Notification No. 1/2000-Central Tax</h1>"
    b"<p>Example: the example return is furnished by the twentieth day of the month.</p>"
    b"</body></html>"
)
WORKFLOWS = [
    IngestDocumentWorkflow,
    ExtractKnowledgeWorkflow,
    ExtractRulesWorkflow,
    ExtractBacklogWorkflow,
]


def settings(*, extraction: bool) -> PipelineSettings:
    return PipelineSettings(
        _env_file=None,
        service_name="pipeline-worker",
        pipeline_knowledge_enabled=True,
        pipeline_extraction_enabled=extraction,
    )


def recorded_notification() -> bytes:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-01-2026.pdf.json").read_text())
    return base64.b64decode(wrapper["data"])


@pytest.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter, interceptors=default_interceptors()
    ) as env:
        yield env


class Pipeline:
    def __init__(self) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.rulebook = MemoryRulebook()
        self.catalog = RegistryCatalog(PoliteClient())
        assert CASE.expected is not None
        self.model = ScriptedProvider({str(CASE.document.document_id): json.dumps(CASE.expected)})
        self.queue = f"pipeline-backlog-{uuid.uuid4().hex[:8]}"
        with self.store() as unit:
            for spec in SOURCES.values():
                unit.sources.add(Source.of(spec.definition(), NOW))

    def upload(self, content: bytes, media_type: str, title: str) -> Stored:
        key = "cbic_notifications"
        ref = DocumentRef(source_id_for(key), f"upload://{key}/{uuid.uuid4().hex}")
        raw = RawDocument.from_bytes(ref, content, media_type, NOW)
        storage_key = self.raw.put(raw)
        document_id = uuid.UUID(raw.sha256[:32])
        with self.store() as unit:
            unit.documents.add(
                RawDocumentRecord(
                    document_id=DocumentId(document_id),
                    source_key=key,
                    source_url=ref.url,
                    fetched_at=NOW,
                    content_type=media_type,
                    size=len(content),
                    sha256=raw.sha256,
                    storage_key=storage_key,
                    title=title,
                )
            )
        return Stored(
            document_id=document_id,
            source_id=source_id_for(key).value,
            source_key=key,
            regulator="CBIC",
            url=ref.url,
            media_type=media_type,
            sha256=raw.sha256,
            size=len(content),
            fetched_at=NOW,
            storage_key=storage_key,
            raw_uri=self.raw.uri(storage_key),
            duplicate=True,
            title=title,
        )

    @asynccontextmanager
    async def worker(
        self, environment: WorkflowEnvironment, *, extraction: bool, says: bool | None = None
    ) -> AsyncIterator[None]:
        """The worker with its extraction on or off; ``says`` makes its check answer otherwise,
        as a worker whose flag turned off after the check, or another worker, would run it."""
        stage = RuleExtractionStage(
            LlmRuleExtractor(self.model, load_prompt(*RULE_PROMPT), load_ontology())
        )
        wired = [
            CheckExtraction(enabled=says)
            if says is not None and isinstance(activity, CheckExtraction)
            else activity
            for activity in activities(
                settings(extraction=extraction),
                sink=self.rulebook,
                embedder=ScriptedEmbedder(),
                sources=self.catalog,
                parser=ParserChain(self.catalog),
                units=self.store,
                raw_store=self.raw,
                extraction=stage,
            )
        ]
        async with Worker(
            environment.client,
            task_queue=self.queue,
            workflows=WORKFLOWS,
            activities=[activity.definition() for activity in wired],
        ):
            yield

    async def sweep(
        self, environment: WorkflowEnvironment, documents: list[ExtractionRequest]
    ) -> tuple[BacklogResult, WorkflowHistory]:
        handle = await environment.client.start_workflow(
            ExtractBacklogWorkflow.run,
            BacklogRequest(documents=documents, concurrency=2),
            id=f"pipeline-extract-backlog-{uuid.uuid4().hex}",
            task_queue=self.queue,
        )
        return await handle.result(), await handle.fetch_history()


async def test_the_classified_backlog_is_extracted_once_by_the_sweep(
    environment: WorkflowEnvironment,
) -> None:
    pipeline = Pipeline()
    recorded = pipeline.upload(
        recorded_notification(), "application/pdf", "Seeks to extend the due date of FORM GSTR-3B"
    )
    synthetic = pipeline.upload(SYNTHETIC, "text/html", "Notification No. 1/2000-Central Tax")
    async with pipeline.worker(environment, extraction=False):
        for stored in (recorded, synthetic):
            handle = await environment.client.start_workflow(
                IngestDocumentWorkflow.run,
                IngestRequest(
                    source_id=stored.source_id, stored=stored, knowledge=True, regulator="CBIC"
                ),
                id=f"ingest-{uuid.uuid4()}",
                task_queue=pipeline.queue,
            )
            result = await handle.result()
            assert (result.classification, result.registered, result.extraction) == (
                "extract",
                True,
                "off",
            )
        backlog = ExtractionBacklog(pipeline.store, RegistryAdapterTypes()).run()
        assert backlog.waiting == {"cbic_notifications": 2}
        skipped, off = await pipeline.sweep(environment, list(backlog.requests))
    assert (skipped.documents, skipped.skipped, skipped.extracted) == (2, 2, 0)
    assert skipped.extraction_enabled is False
    assert "START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in event_types(off)
    for request in backlog.requests:
        with pytest.raises(RPCError) as unknown:
            await environment.client.get_workflow_handle(
                extraction_workflow_id(request.document_id, RULE_PROMPT_REF)
            ).describe()
        assert unknown.value.status is RPCStatusCode.NOT_FOUND, "no extraction id was used"
    missing = ExtractionRequest(
        document_id=uuid.uuid4(),
        source_id=recorded.source_id,
        source_key="cbic_notifications",
        regulator="CBIC",
        doc_type=DocumentType.NOTIFICATION,
    )
    async with pipeline.worker(environment, extraction=True):
        swept, history = await pipeline.sweep(environment, [*backlog.requests, missing])
        assert (swept.documents, swept.extracted, swept.unparseable, swept.failed) == (3, 1, 1, 1)
        assert str(missing.document_id) in swept.failures[0]
        asked = len(pipeline.model.requests)
        again, _ = await pipeline.sweep(environment, list(backlog.requests))
    assert (again.running, again.extracted, again.failed) == (2, 0, 0), "extracted once"
    assert len(pipeline.model.requests) == asked, "no model is asked again"
    for stored in (recorded, synthetic):
        assert pipeline.store.documents[DocumentId(stored.document_id)].status is (
            DocumentStatus.EXTRACTED
        )
    assert ExtractionBacklog(pipeline.store, RegistryAdapterTypes()).run().total == 0
    replayer = Replayer(workflows=WORKFLOWS, data_converter=pydantic_data_converter)
    assert (await replayer.replay_workflow(history)).replay_failure is None
    assert (await replayer.replay_workflow(off)).replay_failure is None


def event_types(history: WorkflowHistory) -> list[str]:
    events = json.loads(history.to_json())["events"]
    return [str(event["eventType"]).removeprefix("EVENT_TYPE_") for event in events]


async def test_a_child_a_worker_with_the_extraction_off_ran_counts_as_disabled(
    environment: WorkflowEnvironment,
) -> None:
    """The check said on, the worker that ran the child's extraction had it off: the child ends
    disabled and is counted so, apart from the running ones; its id is used from then on."""
    pipeline = Pipeline()
    document = ExtractionRequest(
        document_id=uuid.uuid4(),
        source_id=source_id_for("cbic_notifications").value,
        source_key="cbic_notifications",
        regulator="CBIC",
        doc_type=DocumentType.NOTIFICATION,
    )
    async with pipeline.worker(environment, extraction=False, says=True):
        swept, history = await pipeline.sweep(environment, [document])
    assert (swept.disabled, swept.running, swept.extracted, swept.failed) == (1, 0, 0, 0)
    assert swept.extraction_enabled is True
    async with pipeline.worker(environment, extraction=True):
        again, _ = await pipeline.sweep(environment, [document])
    assert (again.running, again.extracted) == (1, 0), "the disabled child's id is used"
    assert pipeline.model.requests == [], "no model was asked"
    replayer = Replayer(workflows=WORKFLOWS, data_converter=pydantic_data_converter)
    assert (await replayer.replay_workflow(history)).replay_failure is None
