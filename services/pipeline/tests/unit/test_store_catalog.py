"""The store-backed catalog the worker resolves sources through, the adapter types as the API
checks them, and the Temporal starter of the crawl."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from domain_kernel.documents import DocumentType
from domain_kernel.ids import SourceId
from pipeline.application.sources import SyncSources
from pipeline.domain.crawl import CrawlRunId
from pipeline.domain.errors import CrawlUnavailableError, SourceInvalidError, UnknownSourceError
from pipeline.domain.ports import CrawlStart
from pipeline.domain.schedule import CRAWL_TIMEOUT, CrawlTrigger
from pipeline.domain.sources import Source, source_id_of
from pipeline.infrastructure.adapters import (
    ADAPTER_TYPES,
    SOURCES,
    RegistryAdapterTypes,
    StoreCatalog,
)
from pipeline.infrastructure.adapters.cbic import CbicAdapter
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.temporal import CRAWL_WORKFLOW, TemporalCrawls, crawl_payload
from pipeline.testing import RecordedAdapter, recorded_client, recorded_types
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
