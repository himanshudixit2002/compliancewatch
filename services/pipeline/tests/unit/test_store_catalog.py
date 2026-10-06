"""The store-backed catalog the worker resolves sources through, the adapter types as the API
checks them, and the Temporal starter of the crawl."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from domain_kernel.documents import DocumentType, document_id_for
from domain_kernel.ids import SourceId
from pipeline.application.crawl import CrawlRequest
from pipeline.application.sources import SyncSources
from pipeline.domain.crawl import CrawlRunId
from pipeline.domain.errors import (
    CrawlUnavailableError,
    IngestUnavailableError,
    SourceInvalidError,
    UnknownSourceError,
)
from pipeline.domain.ports import CrawlStart, IngestStart
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.schedule import CRAWL_TIMEOUT, INGEST_TIMEOUT, CrawlTrigger
from pipeline.domain.sources import Source, source_id_of
from pipeline.infrastructure.adapters import (
    ADAPTER_TYPES,
    SOURCES,
    RegistryAdapterTypes,
    StoreCatalog,
)
from pipeline.infrastructure.adapters.cbic import CbicAdapter
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.temporal import (
    BACKLOG_WORKFLOW,
    CRAWL_WORKFLOW,
    INGEST_WORKFLOW,
    TemporalBacklog,
    TemporalCrawls,
    TemporalIngests,
    backlog_payload,
    crawl_outcome,
    crawl_payload,
    ingest_payload,
)
from pipeline.testing import RecordedAdapter, recorded_client, recorded_types
from pipeline.workflows import IngestRequest
from py_common.settings import Settings

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)


def synced() -> MemoryStore:
    store = MemoryStore()
    SyncSources(store, [spec.definition() for spec in SOURCES.values()]).run()
    return store


def test_a_source_is_resolved_from_its_row_by_its_id() -> None:
    store = synced()
    catalog = StoreCatalog(store, recorded_client())
    resolved = catalog.resolve(source_id_of("cbic_circulars"))
    assert isinstance(resolved.adapter, CbicAdapter)
    assert resolved.definition.doc_type is DocumentType.CIRCULAR
    assert (resolved.definition.regulator, resolved.definition.name) == (
        "CBIC",
        "CBIC CGST circulars",
    )
    assert catalog.resolve(source_id_of("cbic_circulars")).adapter is resolved.adapter
    with pytest.raises(UnknownSourceError, match="no stored source"):
        catalog.resolve(SourceId(UUID(int=1)))


def test_an_edited_row_gets_a_new_adapter() -> None:
    store = synced()
    with store() as unit:
        unit.sources.add(
            Source(
                key="recorded_cbic",
                adapter_type="recorded",
                parameters={"numbers": ["01/2026-Central Tax"]},
                cadence=timedelta(hours=2),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    catalog = StoreCatalog(store, recorded_client(), types=recorded_types())
    first = catalog.resolve(source_id_of("recorded_cbic")).adapter
    assert isinstance(first, RecordedAdapter)
    with store() as unit:
        row = unit.sources.get("recorded_cbic")
        assert row is not None
        unit.sources.save(row.edited(NOW, cadence=timedelta(hours=4)))
    assert catalog.resolve(source_id_of("recorded_cbic")).adapter is first, "same parameters"
    with store() as unit:
        row = unit.sources.get("recorded_cbic")
        assert row is not None
        unit.sources.save(row.edited(NOW, parameters={"numbers": ["17/2025-Central Tax"]}))
    assert catalog.resolve(source_id_of("recorded_cbic")).adapter is not first


def test_a_row_the_code_cannot_read_is_an_unknown_source() -> None:
    store = synced()
    with store() as unit:
        for key, kind, parameters in (
            ("retired", "gone", {}),
            ("broken", "cbic", {"listing": "notifications", "category": "Cess"}),
        ):
            unit.sources.add(
                Source(
                    key=key,
                    adapter_type=kind,
                    parameters=parameters,
                    cadence=timedelta(hours=1),
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    catalog = StoreCatalog(store, recorded_client())
    with pytest.raises(UnknownSourceError, match="no adapter type 'gone'"):
        catalog.resolve(source_id_of("retired"))
    with pytest.raises(UnknownSourceError, match="refuses its parameters"):
        catalog.resolve(source_id_of("broken"))


def test_the_adapter_types_check_parameters_and_say_what_they_give() -> None:
    types = RegistryAdapterTypes()
    assert list(types.names()) == sorted(ADAPTER_TYPES)
    kind = types.describe("cbic", {"listing": "circulars", "category": "Circulars CGST"})
    assert (kind.regulator, kind.site, kind.doc_type) == (
        "CBIC",
        "taxinformation.cbic.gov.in",
        DocumentType.CIRCULAR,
    )
    assert types.describe("gstn", {}).doc_type is DocumentType.PRESS_RELEASE
    with pytest.raises(SourceInvalidError, match="known: cbic, gstcouncil, gstn, mahagst"):
        types.describe("nowhere", {})
    with pytest.raises(SourceInvalidError, match="listing: Input should be"):
        types.describe("cbic", {"listing": "rulings", "category": "Central Tax"})
    recorded = RegistryAdapterTypes(recorded_types())
    with pytest.raises(SourceInvalidError, match="no recorded PDF for 99/2026"):
        recorded.describe("recorded", {"numbers": ["99/2026-Central Tax"]})


START = CrawlStart(
    "pipeline-crawl-gstn_advisories-20261006T060000Z",
    CrawlRunId(UUID(int=7)),
    "gstn_advisories",
    CrawlTrigger.SCHEDULE,
)


class FakeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, Any, dict[str, Any]]] = []

    async def start_workflow(self, workflow: str, payload: Any, **options: Any) -> None:
        self.calls.append((workflow, payload, options))
        if self.error is not None:
            raise self.error


def starter_with(client: FakeClient) -> TemporalCrawls:
    async def connect(_: Settings) -> Client:
        return client  # type: ignore[return-value]

    return TemporalCrawls(Settings(_env_file=None, service_name="pipeline"), connector=connect)


def test_the_crawl_workflow_starts_once_per_id_with_its_timeout() -> None:
    client = FakeClient()
    assert starter_with(client).start(START) is True
    ((workflow, payload, options),) = client.calls
    assert workflow == CRAWL_WORKFLOW == "pipeline.crawl_source"
    assert (
        payload
        == crawl_payload(START)
        == {
            "source_key": "gstn_advisories",
            "run_id": str(UUID(int=7)),
            "trigger": "schedule",
        }
    )
    assert options["id"] == START.workflow_id
    assert options["task_queue"] == "pipeline"
    assert options["id_reuse_policy"] is WorkflowIDReusePolicy.REJECT_DUPLICATE
    assert options["execution_timeout"] == CRAWL_TIMEOUT


def test_a_taken_id_is_refused_and_an_unreachable_temporal_is_unavailable() -> None:
    taken = WorkflowAlreadyStartedError(START.workflow_id, CRAWL_WORKFLOW)
    assert starter_with(FakeClient(taken)).start(START) is False
    with pytest.raises(CrawlUnavailableError, match="did not start the crawl: RuntimeError"):
        starter_with(FakeClient(RuntimeError("no route to host"))).start(START)

    async def slow(_: Settings) -> Client:
        await asyncio.sleep(1)
        raise AssertionError("never reached")

    hanging = TemporalCrawls(
        Settings(_env_file=None, service_name="pipeline"), connector=slow, timeout_seconds=0.01
    )
    with pytest.raises(CrawlUnavailableError, match="TimeoutError"):
        hanging.start(START)


def test_an_ingest_of_a_stored_document_starts_with_its_request() -> None:
    digest = "ab" * 32
    record = RawDocumentRecord(
        document_id=document_id_for(digest),
        source_key="cgst_rules",
        source_url=f"upload://cgst_rules/{digest}",
        fetched_at=NOW,
        content_type="application/pdf",
        size=10,
        sha256=digest,
        storage_key=f"ab/{digest}",
        title="Example statute",
    )
    start = IngestStart(
        workflow_id="pipeline-manual-parse-1",
        record=record,
        source_id=source_id_of("cgst_rules"),
        regulator="CBIC",
        raw_uri=f"memory://ab/{digest}",
        duplicate=True,
        transcript_key="cd/" + "cd" * 32,
        knowledge=True,
    )
    client = FakeClient()

    async def connect(_: Settings) -> Client:
        return client  # type: ignore[return-value]

    ingests = TemporalIngests(Settings(_env_file=None, service_name="pipeline"), connector=connect)
    assert ingests.start(start) is True
    ((workflow, payload, options),) = client.calls
    assert workflow == INGEST_WORKFLOW == "pipeline.ingest_document"
    request = IngestRequest.model_validate(payload)
    assert payload == ingest_payload(start)
    assert request.stored is not None
    assert (request.stored.document_id, request.transcript_key, request.regulator) == (
        record.document_id.value,
        start.transcript_key,
        "CBIC",
    )
    assert options["id_reuse_policy"] is WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
    assert options["execution_timeout"] == INGEST_TIMEOUT
    assert ingests.start(replace(start, workflow_id="pipeline-retry-1-1", once=True)) is True
    assert client.calls[-1][2]["id_reuse_policy"] is WorkflowIDReusePolicy.REJECT_DUPLICATE, (
        "a retry's attempt never runs twice"
    )
    taken = WorkflowAlreadyStartedError(start.workflow_id, INGEST_WORKFLOW)
    refused = TemporalIngests(
        Settings(_env_file=None, service_name="pipeline"),
        connector=lambda _: _ready(FakeClient(taken)),
    )
    assert refused.start(start) is False


async def _ready(client: "FakeClient") -> Client:
    return client  # type: ignore[return-value]


class Described:
    def __init__(self, status: WorkflowExecutionStatus) -> None:
        self.status = status


class FakeHandle:
    def __init__(self, client: "AskedClient", workflow_id: str) -> None:
        self._client = client
        self._id = workflow_id

    async def describe(self) -> Described:
        found = self._client.statuses.get(self._id)
        if isinstance(found, Exception):
            raise found
        if found is None:
            raise RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")
        return Described(found)

    async def result(self) -> Any:
        return self._client.results[self._id]


class AskedClient(FakeClient):
    def __init__(self) -> None:
        super().__init__()
        self.statuses: dict[str, WorkflowExecutionStatus | Exception] = {}
        self.results: dict[str, Any] = {}

    def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
        return FakeHandle(self, workflow_id)


def settings_for() -> Settings:
    return Settings(_env_file=None, service_name="pipeline")


def test_running_names_the_ingests_whose_workflow_runs() -> None:
    client = AskedClient()
    client.statuses = {
        "pipeline-retry-a-1": WorkflowExecutionStatus.COMPLETED,
        "pipeline-retry-a-2": WorkflowExecutionStatus.RUNNING,
    }
    ingests = TemporalIngests(settings_for(), connector=lambda _: _ready(client))
    asked = ["pipeline-retry-a-1", "pipeline-retry-a-2", "pipeline-extract-a-v1"]
    assert ingests.running(asked) == {"pipeline-retry-a-2"}
    assert ingests.running([]) == frozenset()
    client.statuses["pipeline-extract-a-v1"] = RPCError("away", RPCStatusCode.UNAVAILABLE, b"")
    with pytest.raises(IngestUnavailableError, match="did not answer which ingests run"):
        ingests.running(asked)


def test_a_crawl_is_waited_for_and_read_as_its_outcome() -> None:
    client = AskedClient()
    client.results["pipeline-crawl-x-backfill-1"] = {
        "status": "completed",
        "listed": 3,
        "stored": 2,
        "duplicates": 1,
        "failed": 0,
        "deferred": 4,
        "error": "",
    }
    crawls = TemporalCrawls(settings_for(), connector=lambda _: _ready(client))
    outcome = crawls.wait("pipeline-crawl-x-backfill-1")
    assert (outcome.status, outcome.stored, outcome.duplicates, outcome.deferred) == (
        "completed",
        2,
        1,
        4,
    )
    assert crawl_outcome("y", {"listed": "?"}).listed == 0
    with pytest.raises(CrawlUnavailableError, match="did not answer the crawl"):
        crawls.wait("pipeline-crawl-x-nobody")


def test_a_backfill_crawl_names_its_window_and_limit() -> None:
    start = CrawlStart(
        "pipeline-crawl-cbic_notifications-backfill-1",
        CrawlRunId(UUID(int=8)),
        "cbic_notifications",
        CrawlTrigger.BACKFILL,
        since=date(2020, 1, 1),
        until=date(2020, 12, 31),
        refs=("82/2020-Central Tax",),
        limit=200,
    )
    payload = crawl_payload(start)
    request = CrawlRequest.model_validate(payload)
    assert (request.since, request.until, request.refs, request.limit) == (
        date(2020, 1, 1),
        date(2020, 12, 31),
        ["82/2020-Central Tax"],
        200,
    )
    assert request.trigger is CrawlTrigger.BACKFILL
    assert request.window.narrows


def test_the_backlog_sweep_starts_once_with_its_documents() -> None:
    client = FakeClient()
    backlog = TemporalBacklog(settings_for(), connector=lambda _: _ready(client))
    payload = backlog_payload([{"document_id": str(UUID(int=1))}], 3)
    assert backlog.start("pipeline-extract-backlog-1", payload) is True
    ((workflow, sent, options),) = client.calls
    assert (workflow, sent["concurrency"]) == (BACKLOG_WORKFLOW, 3)
    assert options["id_reuse_policy"] is WorkflowIDReusePolicy.REJECT_DUPLICATE


def test_a_retry_from_the_classify_stage_asks_the_ingest_to_read_again() -> None:
    digest = "cd" * 32
    record = RawDocumentRecord(
        document_id=document_id_for(digest),
        source_key="cbic_notifications",
        source_url=f"upload://cbic_notifications/{digest}",
        fetched_at=NOW,
        content_type="text/html",
        size=10,
        sha256=digest,
        storage_key=f"cd/{digest}",
    )
    start = IngestStart(
        workflow_id="pipeline-retry-x-1",
        record=record,
        source_id=source_id_of("cbic_notifications"),
        regulator="CBIC",
        raw_uri=f"memory://cd/{digest}",
        duplicate=True,
        reclassify=True,
    )
    assert IngestRequest.model_validate(ingest_payload(start)).reclassify
