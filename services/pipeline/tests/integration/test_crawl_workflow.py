"""The crawl on a local Temporal dev server, over recorded CBIC notifications.

The source is of the test adapter type ``recorded`` (``pipeline.testing.RECORDED_TYPE``): it lists
three recorded Central Tax notifications from the recorded listing files and fetches their
recorded PDFs through the fixture transport, so nothing reaches the network. The worker runs the
pipeline's real activities, parsers included, on memory stores; the run is recorded by
``StartCrawl`` as the API does. A crawl stores the new documents through child ingests, skips the
URLs stored before, records the run and moves the watermark; the next crawl finds nothing new; a
listing that fails is recorded on the run and the source. The tick, started twice in one cadence
slot against the dev server through ``TemporalCrawls``, starts each source's crawl once.
"""

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from domain_kernel.audit import AuditActor
from domain_kernel.documents import document_id_for
from domain_kernel.ids import UserId
from pipeline.application.crawl import (
    CrawlRequest,
    CrawlResult,
    FetchRequest,
    ListNewDocuments,
    ScheduleCrawls,
    StartCrawl,
)
from pipeline.application.sources import SyncSources
from pipeline.domain.crawl import CrawlStatus
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source, watermark_of
from pipeline.infrastructure.adapters import SOURCES, RegistryAdapterTypes, StoreCatalog
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import MemoryRawStore, storage_key_for
from pipeline.infrastructure.temporal import TemporalCrawls
from pipeline.settings import PipelineSettings
from pipeline.testing import MemoryCrawls, recorded_client, recorded_types
from pipeline.worker import activities
from pipeline.workflows import (
    CrawlSourceWorkflow,
    ExtractKnowledgeWorkflow,
    IngestDocumentWorkflow,
)
from py_common.temporal import ActivityBase
from py_common.temporal.client import default_interceptors

KEY = "recorded_cbic"
NUMBERS = ["01/2026-Central Tax", "17/2025-Central Tax", "15/2025-Central Tax"]
CBIC_PDF = "https://taxinformation.cbic.gov.in/content/pdf/tax_repository/gst/notifications/"
ACTOR = AuditActor.user(UserId(UUID(int=7)))
TODAY = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
SETTINGS = PipelineSettings(_env_file=None, service_name="pipeline-worker")
TYPES = RegistryAdapterTypes(recorded_types())


@pytest.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter, interceptors=default_interceptors()
    ) as env:
        yield env


class Pipeline:
    """Memory stores with the built-in sources and the recorded one, and the worker over them."""

    def __init__(self, watermark: date | None = date(2025, 9, 20)) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        SyncSources(self.store, [spec.definition() for spec in SOURCES.values()]).run()
        with self.store() as unit:
            unit.sources.add(
                Source(
                    key=KEY,
                    adapter_type="recorded",
                    parameters={"numbers": NUMBERS},
                    cadence=timedelta(hours=2),
                    created_at=TODAY,
                    updated_at=TODAY,
                    watermark=watermark_of(watermark),
                    name="Recorded CBIC notifications",
                )
            )
        self.catalog = StoreCatalog(self.store, recorded_client(), types=recorded_types())

    def activities(self) -> list[ActivityBase[Any, Any]]:
        wired = activities(SETTINGS, sources=self.catalog, units=self.store, raw_store=self.raw)
        return [
            ListNewDocuments(self.store, self.catalog, clock=lambda: TODAY)
            if isinstance(activity, ListNewDocuments)
            else activity
            for activity in wired
        ]

    @asynccontextmanager
    async def worker(self, client: Client) -> AsyncIterator[str]:
        task_queue = f"pipeline-crawl-{uuid.uuid4().hex[:8]}"
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=[CrawlSourceWorkflow, IngestDocumentWorkflow, ExtractKnowledgeWorkflow],
            activities=[activity.definition() for activity in self.activities()],
        )
        async with worker:
            yield task_queue

    def fetch_now(self, key: str = KEY) -> UUID:
        start = StartCrawl(self.store, MemoryCrawls(), types=TYPES, enabled=True).run(
            FetchRequest(key, ACTOR, "Crawl the recorded source for the test")
        )
        return start.run_id.value

    def documents(self) -> list[RawDocumentRecord]:
        return sorted(self.store.documents.values(), key=lambda d: d.external_ref)


async def crawl(environment: WorkflowEnvironment, pipeline: Pipeline) -> CrawlResult:
    run_id = pipeline.fetch_now()
    async with pipeline.worker(environment.client) as task_queue:
        result: CrawlResult = await environment.client.execute_workflow(
            CrawlSourceWorkflow.run,
            CrawlRequest(source_key=KEY, run_id=run_id),
            id=f"pipeline-crawl-test-{uuid.uuid4().hex[:8]}",
            task_queue=task_queue,
        )
    return result


async def test_a_crawl_stores_what_is_new_skips_what_is_known_and_moves_the_watermark(
    environment: WorkflowEnvironment,
) -> None:
    pipeline = Pipeline()
    known = CBIC_PDF + "centaltax-15-2025.pdf"
    digest = hashlib.sha256(b"%PDF stored before").hexdigest()
    with pipeline.store() as unit:
        unit.documents.add(
            RawDocumentRecord(
                document_id=document_id_for(digest),
                source_key=KEY,
                source_url=known,
                fetched_at=TODAY - timedelta(days=20),
                content_type="application/pdf",
                size=18,
                sha256=digest,
                storage_key=storage_key_for(digest),
                external_ref="15/2025-Central Tax",
                published_on=date(2025, 9, 17),
            )
        )
    result = await crawl(environment, pipeline)
    assert (result.status, result.listed, result.stored, result.duplicates, result.failed) == (
        CrawlStatus.COMPLETED,
        3,
        2,
        0,
        0,
    )
    assert result.watermark == date(2026, 4, 21)
    stored = [d for d in pipeline.documents() if d.source_url != known]
    assert [d.external_ref for d in stored] == ["01/2026-Central Tax", "17/2025-Central Tax"]
    assert all(d.status is DocumentStatus.CLASSIFIED for d in stored), "each a notification"
    assert {d.parser_version for d in stored} == {"pdf@1"}, "prose stays with the text layer"
    assert all(pipeline.raw.files[d.storage_key].startswith(b"%PDF") for d in stored)
    topics = sorted(event.topic for event in pipeline.store.events)
    assert topics == (
        ["document.classified"] * 2 + ["document.discovered"] * 2 + ["document.parsed"] * 2
    ), "one each per new"
    (run,) = [r for r in pipeline.store.crawl_runs.values() if r.source_key == KEY]
    assert (run.status, run.counts.listed, run.counts.stored) == (CrawlStatus.COMPLETED, 3, 2)
    source = pipeline.store.sources[KEY]
    assert source.last_fetch_at is not None
    assert (source.watermark_date, source.last_error) == (date(2026, 4, 21), "")

    again = await crawl(environment, pipeline)
    assert (again.listed, again.stored, again.duplicates, again.failed) == (1, 0, 0, 0)
    assert len(pipeline.store.documents) == 3, "nothing stored twice"


async def test_a_listing_that_fails_is_recorded_on_the_run_and_the_source(
    environment: WorkflowEnvironment,
) -> None:
    pipeline = Pipeline()
    with pipeline.store() as unit:
        broken = unit.sources.get(KEY)
        assert broken is not None
        unit.sources.save(broken.edited(TODAY, parameters={"numbers": ["99/2026-Central Tax"]}))
    result = await crawl(environment, pipeline)
    assert result.status is CrawlStatus.FAILED
    assert result.error.startswith("UnknownSourceError: source recorded_cbic: adapter type")
    assert pipeline.store.sources[KEY].last_error == result.error
    assert pipeline.store.sources[KEY].last_fetch_at is None
    assert pipeline.store.documents == {}


async def test_a_double_tick_starts_each_crawl_once(environment: WorkflowEnvironment) -> None:
    pipeline = Pipeline()
    target = environment.client.service_client.config.target_host
    settings = PipelineSettings(
        _env_file=None, service_name="pipeline-worker", temporal_address=target
    )
    ticks = [
        ScheduleCrawls(
            pipeline.store,
            TemporalCrawls(settings),
            types=TYPES,
            enabled=True,
            clock=lambda: TODAY,
        )
        for _ in range(2)
    ]
    first, second = await asyncio.gather(*(asyncio.to_thread(tick.run) for tick in ticks))
    started = [*first.started, *second.started]
    assert sorted(started) == sorted(set(started)), "no workflow id was started twice"
    listable = [key for key, spec in SOURCES.items() if spec.kind.listable]
    assert len(started) == len(listable) + 1, "the upload-only sources are never crawled"
    assert (first.failed, second.failed) == ((), ())
    for workflow_id in started:
        described = await environment.client.get_workflow_handle(workflow_id).describe()
        assert described.status is WorkflowExecutionStatus.RUNNING
        await environment.client.get_workflow_handle(workflow_id).terminate("test over")
    again = await asyncio.to_thread(ticks[0].run)
    assert again.started == (), "the runs are recorded: nothing is due"
