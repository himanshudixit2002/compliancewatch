"""Histories recorded before the store, before the crawl, before manual parse, before the
classify step, and with the classify step, a retry's fresh reading and a backfill's crawl, replay
on today's ingest and crawl workflows.

``tests/fixtures/histories`` holds runs of ``pipeline.ingest_document``, each pair one with
knowledge off and one with registration, embedding and the extraction child:

- ``ingest-before-store*`` as the worker ran it before ``FetchAndStore``: both fetched with
  ``pipeline.fetch_document``, whose result carries the bytes. ``workflow.patched(STORE_PATCH)``
  keeps a workflow like them on that path, so a worker deployed with the store finishes them; a
  workflow that took the new activity unconditionally would not replay them.
- ``ingest-with-store*`` as it ran with the store and before the crawl handed an ingest its
  document (``GIVEN_PATCH``): both discovered the document first.
- ``ingest-with-crawl*`` as it ran once a crawl handed an ingest its document, and before a
  document that does not parse opened a manual-parse task; beside the pair,
  ``ingest-with-crawl-unparsed`` was handed a PDF with no text layer, so its parse failed and the
  ingest failed with it.
- ``ingest-with-parse*`` as it ran with the parser chain, uploads and manual parse, before the
  classify step and rule extraction: handed its document by a crawl with knowledge off and on,
  an upload's stored document (``STORED_PATCH``), an analyst's transcript of a statute (stored,
  registered and embedded, never extracted), and a scan no parser reads, which opened its
  manual-parse task (``PARSE_PATCH``).
- ``ingest-with-classify*`` as it ran with the classify step (``CLASSIFY_PATCH``) and the rule
  extraction, handed its document by a crawl: with knowledge off it ends after its
  classification; with knowledge on it is registered and embedded, runs its knowledge child and
  starts its rule extraction child (``EXTRACTION_PATCH``).
- ``ingest-with-reclassify``, a retry from the classify stage of a stored document, which the
  detector read again (``RECLASSIFY_PATCH``) and placed on its way to the extraction.
- ``crawl-with-backfill``, a run of ``pipeline.crawl_source``: a backfill's crawl that listed its
  own window (``BACKFILL_PATCH``) and ingested the document in a child.
"""

import base64
import json
from pathlib import Path

import pytest
from temporalio import workflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ActivityError
from temporalio.worker import Replayer

from pipeline.application.activities import (
    DiscoverDocument,
    DiscoverRequest,
    FetchAndStore,
    OpenManualParse,
    ParseDocument,
    ParseFailure,
    ParseRequest,
)
from pipeline.application.classify import ClassifyDocument, ClassifyRequest
from pipeline.workflows import (
    CrawlSourceWorkflow,
    ExtractKnowledgeWorkflow,
    ExtractRulesWorkflow,
    IngestDocumentWorkflow,
    IngestRequest,
)
from pipeline.workflows.crawl_source import BACKFILL_PATCH
from pipeline.workflows.ingest_document import (
    CLASSIFY_PATCH,
    EXTRACTION_PATCH,
    GIVEN_PATCH,
    RECLASSIFY_PATCH,
    STORE_PATCH,
    STORED_PATCH,
    IngestResult,
)

HISTORIES = Path(__file__).resolve().parents[1] / "fixtures" / "histories"
BEFORE_THE_STORE = [
    HISTORIES / "ingest-before-store.json",
    HISTORIES / "ingest-before-store-knowledge.json",
]
BEFORE_THE_CRAWL = [
    HISTORIES / "ingest-with-store.json",
    HISTORIES / "ingest-with-store-knowledge.json",
]
WITH_THE_CRAWL = [
    HISTORIES / "ingest-with-crawl.json",
    HISTORIES / "ingest-with-crawl-knowledge.json",
]
UNPARSED = HISTORIES / "ingest-with-crawl-unparsed.json"
BEFORE_THE_CLASSIFY_STEP = [
    HISTORIES / "ingest-with-parse.json",
    HISTORIES / "ingest-with-parse-knowledge.json",
    HISTORIES / "ingest-with-parse-upload.json",
    HISTORIES / "ingest-with-parse-statute.json",
    HISTORIES / "ingest-with-parse-unparsed.json",
]
WITH_THE_CLASSIFY_STEP = [
    HISTORIES / "ingest-with-classify.json",
    HISTORIES / "ingest-with-classify-knowledge.json",
]
RECLASSIFIED = HISTORIES / "ingest-with-reclassify.json"
BACKFILLED = HISTORIES / "crawl-with-backfill.json"
RECORDED = [
    *BEFORE_THE_STORE,
    *BEFORE_THE_CRAWL,
    *WITH_THE_CRAWL,
    UNPARSED,
    *BEFORE_THE_CLASSIFY_STEP,
    *WITH_THE_CLASSIFY_STEP,
    RECLASSIFIED,
    BACKFILLED,
]


def history(path: Path) -> WorkflowHistory:
    return WorkflowHistory.from_json(path.stem, path.read_text(encoding="utf-8"))


def replayer(*workflows: type) -> Replayer:
    return Replayer(
        workflows=list(workflows),
        data_converter=pydantic_data_converter,
    )


def scheduled_activities(path: Path) -> list[str]:
    events = json.loads(path.read_text(encoding="utf-8"))["events"]
    return [
        event["activityTaskScheduledEventAttributes"]["activityType"]["name"]
        for event in events
        if event["eventType"] == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    ]


def event_types(path: Path) -> list[str]:
    events = json.loads(path.read_text(encoding="utf-8"))["events"]
    return [str(event["eventType"]).removeprefix("EVENT_TYPE_") for event in events]


def patches(path: Path) -> list[str]:
    """The patch ids the history's markers recorded."""
    found: list[str] = []
    for event in json.loads(path.read_text(encoding="utf-8"))["events"]:
        details = event.get("markerRecordedEventAttributes", {}).get("details", {})
        for payloads in details.values():
            for payload in payloads.get("payloads", []):
                item = json.loads(base64.b64decode(payload["data"]))
                if isinstance(item, dict) and "id" in item:
                    found.append(str(item["id"]))
    return found


def children(path: Path) -> list[str]:
    events = json.loads(path.read_text(encoding="utf-8"))["events"]
    return [
        event["startChildWorkflowExecutionInitiatedEventAttributes"]["workflowType"]["name"]
        for event in events
        if event["eventType"] == "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED"
    ]


def test_the_recorded_histories_fetched_before_the_store() -> None:
    assert sorted(HISTORIES.glob("*.json")) == sorted(RECORDED)
    for path in BEFORE_THE_STORE:
        names = scheduled_activities(path)
        assert "pipeline.fetch_document" in names
        assert "pipeline.fetch_and_store" not in names
    assert "pipeline.register_document" in scheduled_activities(BEFORE_THE_STORE[1])


def test_the_histories_with_the_store_discovered_their_document() -> None:
    for path in BEFORE_THE_CRAWL:
        names = scheduled_activities(path)
        assert names[:3] == [
            "pipeline.discover_document",
            "pipeline.fetch_and_store",
            "pipeline.parse_document",
        ]
    assert "pipeline.register_document" in scheduled_activities(BEFORE_THE_CRAWL[1])


def test_the_histories_with_the_crawl_were_handed_their_document() -> None:
    for path in [*WITH_THE_CRAWL, UNPARSED]:
        names = scheduled_activities(path)
        assert names[:2] == ["pipeline.fetch_and_store", "pipeline.parse_document"]
    assert "pipeline.register_document" in scheduled_activities(WITH_THE_CRAWL[1])
    assert scheduled_activities(UNPARSED) == ["pipeline.fetch_and_store", "pipeline.parse_document"]
    types = event_types(UNPARSED)
    assert "ACTIVITY_TASK_FAILED" in types
    assert types[-1] == "WORKFLOW_EXECUTION_FAILED"


def test_the_histories_before_the_classify_step_took_each_path() -> None:
    crawled, knowledge, upload, statute, unparsed = BEFORE_THE_CLASSIFY_STEP
    assert scheduled_activities(crawled) == ["pipeline.fetch_and_store", "pipeline.parse_document"]
    assert scheduled_activities(knowledge) == [
        "pipeline.fetch_and_store",
        "pipeline.parse_document",
        "pipeline.register_document",
        "pipeline.embed_clauses",
    ]
    assert "START_CHILD_WORKFLOW_EXECUTION_INITIATED" in event_types(knowledge)
    assert scheduled_activities(upload) == [
        "pipeline.parse_document",
        "pipeline.register_document",
        "pipeline.embed_clauses",
    ]
    assert scheduled_activities(statute) == scheduled_activities(upload)
    assert "START_CHILD_WORKFLOW_EXECUTION_INITIATED" not in event_types(statute)
    assert scheduled_activities(unparsed) == [
        "pipeline.fetch_and_store",
        "pipeline.parse_document",
        "pipeline.open_manual_parse",
    ]
    assert event_types(unparsed)[-1] == "WORKFLOW_EXECUTION_COMPLETED"


def test_the_histories_with_the_classify_step_took_its_paths() -> None:
    off, on = WITH_THE_CLASSIFY_STEP
    assert scheduled_activities(off) == [
        "pipeline.fetch_and_store",
        "pipeline.parse_document",
        "pipeline.classify_document",
    ]
    assert CLASSIFY_PATCH in patches(off)
    assert children(off) == []
    assert scheduled_activities(on) == [
        *scheduled_activities(off),
        "pipeline.register_document",
        "pipeline.embed_clauses",
    ]
    assert {CLASSIFY_PATCH, EXTRACTION_PATCH} <= set(patches(on))
    assert children(on) == ["pipeline.extract_knowledge", "pipeline.extract_rules"]
    assert scheduled_activities(RECLASSIFIED) == [
        "pipeline.parse_document",
        "pipeline.classify_document",
    ]
    assert {STORED_PATCH, CLASSIFY_PATCH, RECLASSIFY_PATCH} <= set(patches(RECLASSIFIED))


def test_the_backfill_history_listed_its_own_window() -> None:
    assert scheduled_activities(BACKFILLED) == [
        "pipeline.list_new_documents",
        "pipeline.finish_crawl",
    ]
    assert patches(BACKFILLED) == [BACKFILL_PATCH]
    assert children(BACKFILLED) == ["pipeline.ingest_document"]


@pytest.mark.parametrize("path", RECORDED, ids=lambda path: path.stem)
async def test_a_recorded_history_replays_on_todays_workflow(path: Path) -> None:
    replayed = await replayer(
        IngestDocumentWorkflow, ExtractKnowledgeWorkflow, ExtractRulesWorkflow, CrawlSourceWorkflow
    ).replay_workflow(history(path))
    assert replayed.replay_failure is None


@workflow.defn(name="pipeline.ingest_document", sandboxed=False)
class IngestWithoutTheGuard:
    """The ingest as it would be had FetchAndStore replaced FetchDocument without a patch. Out
    of the sandbox, which cannot import a test module by its path."""

    @workflow.run
    async def run(self, request: IngestRequest) -> IngestResult:
        discovered = await DiscoverDocument.schedule(
            DiscoverRequest(source_id=request.source_id, since=request.discover_since())
        )
        stored = await FetchAndStore.schedule(discovered)
        return IngestResult(
            document_id=stored.document_id,
            sha256=stored.sha256,
            url=stored.url,
            clause_count=1,
            clause_refs=["p1"],
        )


async def test_without_the_guard_the_old_histories_would_not_replay() -> None:
    replayed = await replayer(IngestWithoutTheGuard).replay_workflow(
        history(BEFORE_THE_STORE[0]), raise_on_replay_failure=False
    )
    assert isinstance(replayed.replay_failure, workflow.NondeterminismError)


@workflow.defn(name="pipeline.ingest_document", sandboxed=False)
class IngestWithoutTheParseGuard:
    """The ingest as it would be had a parse failure opened a manual-parse task without
    ``PARSE_PATCH``."""

    @workflow.run
    async def run(self, request: IngestRequest) -> IngestResult:
        assert request.discovered is not None
        workflow.patched(GIVEN_PATCH)
        workflow.patched(STORE_PATCH)
        stored = await FetchAndStore.schedule(request.discovered)
        try:
            await ParseDocument.schedule(
                ParseRequest(document_id=stored.document_id, stored=stored)
            )
        except ActivityError:
            await OpenManualParse.schedule(ParseFailure(document_id=stored.document_id))
        return IngestResult(
            document_id=stored.document_id,
            sha256=stored.sha256,
            url=stored.url,
            clause_count=0,
            clause_refs=[],
        )


async def test_without_the_parse_guard_a_failed_parse_would_not_replay() -> None:
    replayed = await replayer(IngestWithoutTheParseGuard).replay_workflow(
        history(UNPARSED), raise_on_replay_failure=False
    )
    assert isinstance(replayed.replay_failure, workflow.NondeterminismError)


@workflow.defn(name="pipeline.ingest_document", sandboxed=False)
class IngestWithoutTheClassifyGuard:
    """The ingest as it would be had the classify step followed the parse without
    ``CLASSIFY_PATCH``."""

    @workflow.run
    async def run(self, request: IngestRequest) -> IngestResult:
        assert request.stored is not None
        workflow.patched(STORED_PATCH)
        parse = ParseRequest(document_id=request.stored.document_id, stored=request.stored)
        parsed = await ParseDocument.schedule(parse)
        await ClassifyDocument.schedule(ClassifyRequest(parse=parse))
        return IngestResult(
            document_id=parsed.document_id,
            sha256=request.stored.sha256,
            url=request.stored.url,
            clause_count=parsed.clause_count,
            clause_refs=parsed.clause_refs,
        )


async def test_without_the_classify_guard_an_upload_before_it_would_not_replay() -> None:
    upload = BEFORE_THE_CLASSIFY_STEP[2]
    replayed = await replayer(IngestWithoutTheClassifyGuard).replay_workflow(
        history(upload), raise_on_replay_failure=False
    )
    assert isinstance(replayed.replay_failure, workflow.NondeterminismError)
