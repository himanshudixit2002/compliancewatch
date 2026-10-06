"""Histories recorded before the store, before the crawl, before manual parse and before the
classify step replay on today's ingest workflow.

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
"""

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
from pipeline.workflows import ExtractKnowledgeWorkflow, IngestDocumentWorkflow, IngestRequest
from pipeline.workflows.ingest_document import GIVEN_PATCH, STORE_PATCH, IngestResult

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
RECORDED = [
    *BEFORE_THE_STORE,
    *BEFORE_THE_CRAWL,
    *WITH_THE_CRAWL,
    UNPARSED,
    *BEFORE_THE_CLASSIFY_STEP,
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


@pytest.mark.parametrize("path", RECORDED, ids=lambda path: path.stem)
async def test_a_recorded_history_replays_on_todays_workflow(path: Path) -> None:
    replayed = await replayer(IngestDocumentWorkflow, ExtractKnowledgeWorkflow).replay_workflow(
        history(path)
    )
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
