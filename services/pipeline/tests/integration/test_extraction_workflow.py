"""Classification, triage and the rule extraction on a local Temporal dev server.

The ingest classifies each stored document after its parse: the recorded notification
01/2026-Central Tax is a notification its source publishes, so it is registered and its rule
candidate extracted in a child the ingest leaves running, with the extraction prompt and a
scripted model that answers with the case's draft label (evals/golden/extraction, a draft
nobody reviewed: it shows the plumbing, not the law). A synthetic circular among the
notifications waits for a person's triage, and the triage's resolution continues it to its
extraction. A statute and a press release are kept for reference, a portal manual is set aside.
A used-up budget is waited out by the extraction workflow and asked about again. Each new
history replays on the workflows; the histories recorded before these steps replay in
tests/unit/test_workflow_replay.py."""

import base64
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from temporalio.client import WorkflowFailureError, WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from cw_contracts.events import TOPICS
from domain_kernel.audit import AuditActor
from domain_kernel.documents import (
    DocumentRef,
    DocumentType,
    ParsedDocument,
    RawDocument,
    clause_id_for,
)
from domain_kernel.ids import DocumentId, UserId
from domain_kernel.protocols import LLMProvider
from ontology import load as load_ontology
from pipeline.application.activities import Stored
from pipeline.application.extraction import (
    RULE_PROMPT,
    RULE_PROMPT_REF,
    ExtractionRequest,
    RuleExtractionStage,
)
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.application.sources import AdminAction
from pipeline.application.tasks import ResolveTask
from pipeline.domain.classification import Relevance, TriageDecision
from pipeline.domain.errors import ModelBudgetExhaustedError
from pipeline.domain.events import DocumentClassified, RuleCandidateCreated
from pipeline.domain.knowledge import DocumentRecord
from pipeline.domain.prompt import PromptText
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source
from pipeline.domain.tasks import TaskId, TaskKind, TaskStatus
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
from pipeline.infrastructure.temporal import ingest_payload
from pipeline.label import load_case
from pipeline.settings import PipelineSettings
from pipeline.testing import (
    AnswersInTurn,
    MemoryIngests,
    MemoryRulebook,
    ScriptedEmbedder,
    ScriptedProvider,
)
from pipeline.worker import activities
from pipeline.workflows import (
    ExtractionResult,
    ExtractKnowledgeWorkflow,
    ExtractRulesWorkflow,
    IngestDocumentWorkflow,
    IngestRequest,
    IngestResult,
)
from pipeline.workflows.extract_rules import extraction_workflow_id
from pipeline.workflows.ingest_document import CLASSIFY_PATCH, EXTRACTION_PATCH
from py_common.events import to_message
from py_common.temporal.client import default_interceptors

REPO = Path(__file__).resolve().parents[4]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CASE = load_case(REPO / "evals/golden/extraction/cbic_notifications/cases/01-2026-central-tax.yaml")
NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
ON = PipelineSettings(
    _env_file=None,
    service_name="pipeline-worker",
    pipeline_knowledge_enabled=True,
    pipeline_extraction_enabled=True,
)
CIRCULAR = (
    b"<html><head><title>Circular No. 5/2026-GST</title></head><body>"
    b"<h1>Circular No. 5/2026-GST</h1>"
    b"<p>Subject: Example clarification on the furnishing of an example return.</p>"
    b"<p>2. Example: the board clarifies that the example return is furnished monthly.</p>"
    b"</body></html>"
)
CIRCULAR_ANSWER = {
    "title": "Example clarification on an example return",
    "summary": "An example circular clarifies how an example return is furnished.",
    "doc_kind": "circular",
    "change_kind": "none",
    "effective_from": None,
    "effective_to": None,
    "references": [],
    "applies_to": [],
    "obligation": None,
    "recurrence": None,
    "amounts": [],
    "citations": [{"clause_ref": "en.p4", "quote": "the example return is furnished monthly"}],
    "confidence": 0.9,
}


def recorded_notification() -> bytes:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-01-2026.pdf.json").read_text())
    return base64.b64decode(wrapper["data"])


def page(title: str, text: str) -> bytes:
    return (
        f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{text}</p>"
        "</body></html>"
    ).encode()


@pytest.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter, interceptors=default_interceptors()
    ) as env:
        yield env


class Pipeline:
    """Memory stores with the built-in sources, the parser chain, a rulebook, and the
    extraction's model."""

    def __init__(self, model: LLMProvider, settings: PipelineSettings = ON) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.rulebook = MemoryRulebook()
        self.catalog = RegistryCatalog(PoliteClient())
        self.model = model
        self.settings = settings
        self.queue = f"pipeline-test-{uuid.uuid4().hex[:8]}"
        with self.store() as unit:
            for spec in SOURCES.values():
                unit.sources.add(Source.of(spec.definition(), NOW))

    def upload(self, content: bytes, media_type: str, *, key: str = "cbic_notifications") -> Stored:
        """What an upload does before it starts the ingest."""
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
                    title="Example upload",
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
            title="Example upload",
        )

    @asynccontextmanager
    async def worker(self, environment: WorkflowEnvironment) -> AsyncIterator[None]:
        relations = RelationStage(
            LlmRelationExtractor(
                ScriptedProvider({}, default='{"relations": []}'),
                PromptText("extraction.rule_relations", "1", "regulatory-intelligence", "R."),
            )
        )
        extraction = RuleExtractionStage(
            LlmRuleExtractor(self.model, load_prompt(*RULE_PROMPT), load_ontology())
        )
        wired = activities(
            self.settings,
            sink=self.rulebook,
            stage=relations,
            embedder=ScriptedEmbedder(),
            sources=self.catalog,
            parser=ParserChain(self.catalog),
            units=self.store,
            raw_store=self.raw,
            extraction=extraction,
        )
        async with Worker(
            environment.client,
            task_queue=self.queue,
            workflows=[IngestDocumentWorkflow, ExtractKnowledgeWorkflow, ExtractRulesWorkflow],
            activities=[activity.definition() for activity in wired],
        ):
            yield

    async def ingest(
        self, environment: WorkflowEnvironment, request: IngestRequest
    ) -> tuple[IngestResult, WorkflowHistory]:
        handle = await environment.client.start_workflow(
            IngestDocumentWorkflow.run,
            request,
            id=f"ingest-{uuid.uuid4()}",
            task_queue=self.queue,
        )
        return await handle.result(), await handle.fetch_history()

    async def extraction(
        self, environment: WorkflowEnvironment, workflow_id: str
    ) -> tuple[ExtractionResult, WorkflowHistory]:
        handle = environment.client.get_workflow_handle_for(ExtractRulesWorkflow.run, workflow_id)
        return await handle.result(), await handle.fetch_history()

    def candidates(self) -> list[RuleCandidateCreated]:
        return [e for e in self.store.events if isinstance(e, RuleCandidateCreated)]

    def classified(self) -> list[DocumentClassified]:
        return [e for e in self.store.events if isinstance(e, DocumentClassified)]


def ingest(stored: Stored) -> IngestRequest:
    return IngestRequest(
        source_id=stored.source_id, stored=stored, knowledge=True, regulator="CBIC"
    )


def events_of(history: WorkflowHistory) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = json.loads(history.to_json())["events"]
    return found


def scheduled(history: WorkflowHistory) -> list[str]:
    return [
        event["activityTaskScheduledEventAttributes"]["activityType"]["name"]
        for event in events_of(history)
        if "activityTaskScheduledEventAttributes" in event
    ]


def patches(history: WorkflowHistory) -> list[str]:
    found: list[str] = []
    for event in events_of(history):
        details = event.get("markerRecordedEventAttributes", {}).get("details", {})
        for payloads in details.values():
            for payload in payloads.get("payloads", []):
                item = json.loads(base64.b64decode(payload["data"]))
                if isinstance(item, dict) and "id" in item:
                    found.append(str(item["id"]))
    return found


async def replays(history: WorkflowHistory) -> None:
    replayer = Replayer(
        workflows=[IngestDocumentWorkflow, ExtractKnowledgeWorkflow, ExtractRulesWorkflow],
        data_converter=pydantic_data_converter,
    )
    replayed = await replayer.replay_workflow(history)
    assert replayed.replay_failure is None


async def test_a_recorded_notification_is_classified_registered_and_its_candidate_extracted(
    environment: WorkflowEnvironment,
) -> None:
    assert CASE.expected is not None
    assert CASE.label_status == "draft"
    model = ScriptedProvider({str(CASE.document.document_id): json.dumps(CASE.expected)})
    pipeline = Pipeline(model)
    stored = pipeline.upload(recorded_notification(), "application/pdf")
    assert stored.document_id == CASE.document.document_id.value
    async with pipeline.worker(environment):
        result, history = await pipeline.ingest(environment, ingest(stored))
        assert (result.classification, result.doc_type, result.registered) == (
            "extract",
            "notification",
            True,
        )
        workflow_id = extraction_workflow_id(stored.document_id, RULE_PROMPT_REF)
        assert (result.extraction, result.extraction_workflow_id) == ("started", workflow_id)
        extracted, child = await pipeline.extraction(environment, workflow_id)
        assert (extracted.outcome, extracted.created, extracted.needs_review) == (
            "extracted",
            True,
            False,
        )
        again, _ = await pipeline.ingest(environment, ingest(stored))
    assert (again.classification, again.extraction) == ("extract", "running")
    assert scheduled(history)[:3] == [
        "pipeline.parse_document",
        "pipeline.classify_document",
        "pipeline.register_document",
    ]
    assert {CLASSIFY_PATCH, EXTRACTION_PATCH} <= set(patches(history))
    assert scheduled(child) == ["pipeline.extract_rules", "pipeline.store_extraction"]
    (classified,) = pipeline.classified()
    assert (classified.confidence.value, classified.relevance.value) == ("certain", "relevant")
    (candidate,) = pipeline.candidates()
    message = to_message(candidate)
    TOPICS[message.topic].model.model_validate(message.payload)
    assert message.payload["candidate"] == CASE.expected
    assert message.payload["suggested_rule_key"] == "gstr3b_monthly"
    assert message.payload["clause_ids"] == [
        str(clause_id_for(DocumentId(stored.document_id), ref)) for ref in ("en.p3", "en.p4")
    ]
    record = pipeline.store.documents[DocumentId(stored.document_id)]
    assert record.status is DocumentStatus.EXTRACTED
    assert len(pipeline.candidates()) == 1, "a second ingest extracts nothing again"
    await replays(history)
    await replays(child)


async def test_a_conflict_waits_for_triage_and_its_resolution_extracts_the_circular(
    environment: WorkflowEnvironment,
) -> None:
    pipeline = Pipeline(AnswersInTurn(json.dumps(CIRCULAR_ANSWER)))
    stored = pipeline.upload(CIRCULAR, "text/html")
    document_id = DocumentId(stored.document_id)
    async with pipeline.worker(environment):
        held, history = await pipeline.ingest(environment, ingest(stored))
        assert (held.classification, held.doc_type, held.registered, held.extraction) == (
            "triage",
            "circular",
            False,
            "",
        )
        assert held.task_id is not None
        assert pipeline.rulebook.records == {}, "nothing of it is registered meanwhile"
        task = pipeline.store.tasks[TaskId(held.task_id)]
        assert (task.kind, task.status) == (TaskKind.TRIAGE, TaskStatus.OPEN)
        ingests = MemoryIngests()
        resolution = ResolveTask(
            pipeline.store,
            pipeline.raw,
            ingests,
            RegistryAdapterTypes(),
            knowledge=True,
        ).run(
            task.id,
            None,
            AdminAction(actor=AuditActor.user(UserId.new()), reason="Read the text: a circular"),
            triage=TriageDecision(Relevance.RELEVANT, DocumentType.CIRCULAR),
        )
        assert resolution.started
        continued = IngestRequest.model_validate(ingest_payload(ingests.started[-1]))
        result, continued_history = await pipeline.ingest(environment, continued)
        assert (result.classification, result.doc_type, result.registered) == (
            "extract",
            "circular",
            True,
        )
        assert result.extraction == "started"
        extracted, _ = await pipeline.extraction(environment, result.extraction_workflow_id)
    assert (extracted.outcome, extracted.created) == ("extracted", True)
    registered = pipeline.rulebook.records[document_id]
    assert registered.document.doc_type is DocumentType.CIRCULAR, "registered as triaged"
    (candidate,) = pipeline.candidates()
    assert (candidate.doc_type, candidate.suggested_rule_key) == (DocumentType.CIRCULAR, None)
    conflict, decided = pipeline.classified()
    assert (conflict.confidence.value, decided.classifier) == ("conflict", "triage")
    assert pipeline.store.documents[document_id].doc_type is None, "the stored type stays"
    await replays(history)
    await replays(continued_history)


@pytest.mark.parametrize(
    ("content", "key", "classification", "registered"),
    [
        (page("Example rules", "Rule 1. Example text of a rule."), "cgst_rules", "reference", True),
        (
            page("Press release", "Recommendations of the 99th meeting of the GST Council"),
            "gstcouncil_press",
            "reference",
            True,
        ),
        (page("Reset Password User Manual", "Step 1"), "cbic_notifications", "irrelevant", False),
    ],
    ids=["statute", "press-release", "user-manual"],
)
async def test_statutes_and_press_releases_are_kept_for_reference_and_never_extracted(
    environment: WorkflowEnvironment,
    content: bytes,
    key: str,
    classification: str,
    registered: bool,
) -> None:
    model = AnswersInTurn()
    pipeline = Pipeline(model)
    stored = pipeline.upload(content, "text/html", key=key)
    async with pipeline.worker(environment):
        result, history = await pipeline.ingest(environment, ingest(stored))
    assert (result.classification, result.registered) == (classification, registered)
    assert (result.extraction, result.extraction_workflow_id) == ("", "")
    assert "pipeline.classify_document" in scheduled(history)
    assert (model.requests, pipeline.candidates()) == ([], []), "no model, no candidate"
    expected = DocumentStatus.REFERENCE if registered else DocumentStatus.IRRELEVANT
    assert pipeline.store.documents[DocumentId(stored.document_id)].status is expected
    await replays(history)


def registered_notification(pipeline: Pipeline) -> ExtractionRequest:
    """The recorded notification stored, classified and registered, as an ingest leaves it."""
    stored = pipeline.upload(recorded_notification(), "application/pdf")
    document: ParsedDocument = CASE.document
    pipeline.rulebook.register_document(
        DocumentRecord(
            document=document,
            source_id=source_id_for("cbic_notifications"),
            sha256=stored.sha256,
            regulator="CBIC",
            url=stored.url,
            media_type=stored.media_type,
            fetched_at=NOW,
        )
    )
    with pipeline.store() as unit:
        unit.documents.record_parse(DocumentId(stored.document_id), "pdf@1")
        unit.documents.set_status(DocumentId(stored.document_id), DocumentStatus.CLASSIFIED)
    return ExtractionRequest(
        document_id=stored.document_id,
        source_id=stored.source_id,
        source_key=stored.source_key,
        regulator="CBIC",
        doc_type=DocumentType.NOTIFICATION,
        min_wait_seconds=1,
        max_wait_seconds=2,
    )


async def test_a_used_up_budget_is_waited_out_and_asked_about_again(
    environment: WorkflowEnvironment,
) -> None:
    assert CASE.expected is not None
    model = AnswersInTurn(
        ModelBudgetExhaustedError("the extraction budget is used up", retry_after_seconds=1.0),
        json.dumps(CASE.expected),
    )
    pipeline = Pipeline(model)
    request = registered_notification(pipeline)
    async with pipeline.worker(environment):
        handle = await environment.client.start_workflow(
            ExtractRulesWorkflow.run,
            request,
            id=f"extract-{uuid.uuid4()}",
            task_queue=pipeline.queue,
        )
        result = await handle.result()
        history = await handle.fetch_history()
    assert (result.outcome, result.budget_waits, result.created) == ("extracted", 1, True)
    assert len(model.requests) == 2
    assert scheduled(history) == [
        "pipeline.extract_rules",
        "pipeline.extract_rules",
        "pipeline.store_extraction",
    ]
    types = [str(event["eventType"]).removeprefix("EVENT_TYPE_") for event in events_of(history)]
    assert {"ACTIVITY_TASK_FAILED", "TIMER_STARTED", "TIMER_FIRED"} <= set(types)
    assert len(pipeline.candidates()) == 1
    await replays(history)


async def test_with_no_wait_left_a_used_up_budget_fails_the_extraction(
    environment: WorkflowEnvironment,
) -> None:
    model = AnswersInTurn(ModelBudgetExhaustedError("used up", retry_after_seconds=1.0))
    pipeline = Pipeline(model)
    request = registered_notification(pipeline).model_copy(update={"max_waits": 0})
    async with pipeline.worker(environment):
        handle = await environment.client.start_workflow(
            ExtractRulesWorkflow.run,
            request,
            id=f"extract-{uuid.uuid4()}",
            task_queue=pipeline.queue,
        )
        with pytest.raises(WorkflowFailureError):
            await handle.result()
    assert (len(model.requests), pipeline.candidates()) == (1, [])
    record = pipeline.store.documents[DocumentId(request.document_id)]
    assert record.status is DocumentStatus.CLASSIFIED, "it waits for a later extraction"
