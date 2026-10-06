"""``FetchAndStore`` in the ingest workflow on a local Temporal dev server: a new run takes the
patched path, the bytes stay out of the history, the parse is recorded with its document.parsed,
a refetch is a duplicate announced once, and the new history replays. The replay of histories
recorded before the store is in tests/unit/test_workflow_replay.py.
"""

import base64
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer

from pipeline.domain.events import DocumentClassified, DocumentDiscovered, DocumentParsed
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.infrastructure.fakes import SAMPLE_TEXT
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.testing import sample_activities
from pipeline.workflows import (
    ExtractKnowledgeWorkflow,
    IngestDocumentWorkflow,
    IngestRequest,
    IngestResult,
)
from pipeline.workflows.ingest_document import CLASSIFY_PATCH, STORE_PATCH
from py_common.temporal.client import default_interceptors
from py_common.temporal.worker import WorkerConfig, build_worker

REQUEST = IngestRequest(source_id=uuid.UUID(int=1), since=datetime(2026, 9, 1, tzinfo=UTC))


@pytest.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter, interceptors=default_interceptors()
    ) as env:
        yield env


async def ingest(
    environment: WorkflowEnvironment, store: MemoryStore, raw_store: MemoryRawStore
) -> tuple[IngestResult, WorkflowHistory]:
    task_queue = f"pipeline-test-{uuid.uuid4().hex[:8]}"
    worker = build_worker(
        environment.client,
        WorkerConfig(task_queue=task_queue),
        workflows=[IngestDocumentWorkflow],
        activities=sample_activities(units=store, raw_store=raw_store),
    )
    async with worker:
        handle = await environment.client.start_workflow(
            IngestDocumentWorkflow.run,
            REQUEST,
            id=f"ingest-{uuid.uuid4()}",
            task_queue=task_queue,
        )
        result = await handle.result()
        return result, await handle.fetch_history()


def decoded(payloads: dict[str, Any]) -> list[Any]:
    return [json.loads(base64.b64decode(p["data"])) for p in payloads.get("payloads", [])]


def history_events(history: WorkflowHistory) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = json.loads(history.to_json())["events"]
    return events


def scheduled(history: WorkflowHistory) -> list[tuple[str, Any]]:
    """Each scheduled activity's type with its decoded input."""
    found = []
    for event in history_events(history):
        attributes = event.get("activityTaskScheduledEventAttributes")
        if attributes is not None:
            (argument,) = decoded(attributes["input"])
            found.append((attributes["activityType"]["name"], argument))
    return found


def payload_texts(history: WorkflowHistory) -> list[str]:
    """Every payload of the history, decoded to text, wherever in an event it is."""
    texts: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "metadata" in node and "data" in node:
                texts.append(base64.b64decode(node["data"]).decode("utf-8", errors="replace"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(history_events(history))
    return texts


def patches(history: WorkflowHistory) -> list[str]:
    """The ids of the patches the history's markers record."""
    found: list[str] = []
    for event in history_events(history):
        attributes = event.get("markerRecordedEventAttributes")
        if attributes is not None:
            for payloads in attributes.get("details", {}).values():
                found.extend(
                    str(item["id"])
                    for item in decoded(payloads)
                    if isinstance(item, dict) and "id" in item
                )
    return found


async def test_a_new_run_stores_the_document_and_passes_on_its_key(
    environment: WorkflowEnvironment,
) -> None:
    store, raw_store = MemoryStore(), MemoryRawStore()
    result, history = await ingest(environment, store, raw_store)
    assert (result.clause_count, result.duplicate) == (3, False)
    assert raw_store.files == {result.storage_key: SAMPLE_TEXT.encode()}
    (record,) = store.documents.values()
    assert record.document_id.value == result.document_id
    assert (record.status, record.parser_version) == (DocumentStatus.CLASSIFIED, "fake@1")
    discovered, parsed, classified = store.events
    assert isinstance(discovered, DocumentDiscovered)
    assert discovered.document_id.value == result.document_id
    assert isinstance(parsed, DocumentParsed)
    assert (parsed.parser_version, parsed.clause_count) == ("fake@1", 3)
    assert isinstance(classified, DocumentClassified)
    assert (result.classification, result.doc_type) == ("extract", "notification")

    assert patches(history) == [STORE_PATCH, CLASSIFY_PATCH]
    activities = scheduled(history)
    assert [name for name, _ in activities] == [
        "pipeline.discover_document",
        "pipeline.fetch_and_store",
        "pipeline.parse_document",
        "pipeline.classify_document",
    ]
    (_, parse_input) = activities[2]
    assert parse_input["fetched"] is None
    assert parse_input["stored"]["storage_key"] == result.storage_key
    body = "In exercise of the powers conferred"
    assert body in SAMPLE_TEXT
    assert not [text for text in payload_texts(history) if body in text], "no bytes in history"

    replayer = Replayer(
        workflows=[IngestDocumentWorkflow, ExtractKnowledgeWorkflow],
        data_converter=pydantic_data_converter,
    )
    replayed = await replayer.replay_workflow(history)
    assert replayed.replay_failure is None


async def test_a_refetch_is_a_duplicate_announced_once(environment: WorkflowEnvironment) -> None:
    store, raw_store = MemoryStore(), MemoryRawStore()
    first, _ = await ingest(environment, store, raw_store)
    again, _ = await ingest(environment, store, raw_store)
    assert (first.duplicate, again.duplicate) == (False, True)
    assert (again.document_id, again.storage_key) == (first.document_id, first.storage_key)
    assert again.clause_refs == first.clause_refs, "the duplicate still parses from the store"
    assert len(store.documents) == 1
    assert [type(event) for event in store.events] == [
        DocumentDiscovered,
        DocumentParsed,
        DocumentClassified,
    ], "the second ingest finds the document parsed and classified"
    assert raw_store.puts == 1
