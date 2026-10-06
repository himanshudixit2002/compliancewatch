"""Histories recorded before the store replay on today's ingest workflow.

``tests/fixtures/histories`` holds two runs of ``pipeline.ingest_document`` as the worker ran it
before ``FetchAndStore``: one with knowledge off, one with registration, embedding and the
extraction child. Both fetched with ``pipeline.fetch_document``, whose result carries the bytes.
``workflow.patched(STORE_PATCH)`` keeps a workflow like them on that path, so a worker deployed
with the store finishes them; a workflow that took the new activity unconditionally would not
replay them.
"""

import json
from pathlib import Path

import pytest
from temporalio import workflow
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

from pipeline.application.activities import DiscoverDocument, DiscoverRequest, FetchAndStore
from pipeline.workflows import ExtractKnowledgeWorkflow, IngestDocumentWorkflow, IngestRequest
from pipeline.workflows.ingest_document import IngestResult

HISTORIES = Path(__file__).resolve().parents[1] / "fixtures" / "histories"
BEFORE_THE_STORE = [
    HISTORIES / "ingest-before-store.json",
    HISTORIES / "ingest-before-store-knowledge.json",
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


def test_the_recorded_histories_fetched_before_the_store() -> None:
    assert sorted(HISTORIES.glob("*.json")) == sorted(BEFORE_THE_STORE)
    for path in BEFORE_THE_STORE:
        names = scheduled_activities(path)
        assert "pipeline.fetch_document" in names
        assert "pipeline.fetch_and_store" not in names
    assert "pipeline.register_document" in scheduled_activities(BEFORE_THE_STORE[1])


@pytest.mark.parametrize("path", BEFORE_THE_STORE, ids=lambda path: path.stem)
async def test_a_history_from_before_the_store_replays(path: Path) -> None:
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
            DiscoverRequest(source_id=request.source_id, since=request.since)
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
