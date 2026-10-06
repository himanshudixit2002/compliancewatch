"""``pipeline.fetch_and_store`` on the memory store and the memory raw store: a new document is
stored, recorded and announced once, a refetch writes nothing, and a failure part of the way
leaves no row and no event."""

import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from temporalio.testing import ActivityEnvironment

from domain_kernel.documents import DiscoveredDocument, DocumentRef, RawDocument, document_id_for
from domain_kernel.ids import SourceId
from pipeline.application.activities import Discovered, FetchAndStore, Stored
from pipeline.application.store_document import StoreDocument, StoreRequest
from pipeline.domain.errors import RawStoreError
from pipeline.domain.events import DocumentDiscovered
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.repository import UnitOfWork
from pipeline.infrastructure.adapters import RegistryCatalog, source_id_for
from pipeline.infrastructure.fakes import SAMPLE_TEXT, FakeSourceAdapter, sample_catalog
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.testing import CBIC_PDF, recorded_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE = Discovered(
    source_id=UUID(int=1),
    url="https://example.invalid/notifications/17-2026",
    external_ref="17/2026",
    title="Notification No. 17/2026 - Central Tax",
    published_at=date(2026, 9, 15),
)
NOW = datetime(2026, 10, 6, 4, 30, tzinfo=UTC)


def activity(
    adapter: FakeSourceAdapter | None = None,
    *,
    store: MemoryStore | None = None,
    raw_store: MemoryRawStore | None = None,
) -> tuple[FetchAndStore, MemoryStore, MemoryRawStore]:
    store = store or MemoryStore()
    raw_store = raw_store or MemoryRawStore()
    use_case = StoreDocument(sample_catalog(adapter), store, raw_store, clock=lambda: NOW)
    return FetchAndStore(use_case), store, raw_store


async def test_a_new_document_is_stored_recorded_and_announced_once() -> None:
    fetch_and_store, store, raw_store = activity()
    stored = await ActivityEnvironment().run(fetch_and_store.definition(), SAMPLE)
    assert isinstance(stored, Stored)
    content = SAMPLE_TEXT.encode()
    assert raw_store.files == {stored.storage_key: content}
    assert (stored.duplicate, stored.size, stored.media_type) == (False, len(content), "text/plain")
    assert (stored.source_key, stored.regulator, stored.url) == ("sample", "CBIC", SAMPLE.url)
    assert stored.document_id == document_id_for(stored.sha256).value
    assert stored.raw_uri == f"memory://{stored.storage_key}"

    (record,) = store.documents.values()
    assert record.document_id.value == stored.document_id
    assert (record.source_key, record.source_url, record.storage_key) == (
        "sample",
        SAMPLE.url,
        stored.storage_key,
    )
    assert (record.external_ref, record.title, record.published_on) == (
        "17/2026",
        SAMPLE.title,
        date(2026, 9, 15),
    )
    assert record.status is DocumentStatus.DISCOVERED
    assert store.sources["sample"].created_at == NOW

    (event,) = store.events
    assert isinstance(event, DocumentDiscovered)
    assert (event.document_id, event.source_id) == (record.document_id, SourceId(UUID(int=1)))
    assert (event.regulator, event.url, event.external_ref) == ("CBIC", SAMPLE.url, "17/2026")
    assert (event.sha256, event.media_type, event.raw_uri) == (
        stored.sha256,
        "text/plain",
        stored.raw_uri,
    )
    assert (event.title, event.published_at) == (SAMPLE.title, date(2026, 9, 15))
    assert event.partition_key == str(UUID(int=1))


async def test_a_refetch_is_a_duplicate_and_writes_nothing() -> None:
    fetch_and_store, store, raw_store = activity()
    first = await fetch_and_store.run(SAMPLE)
    again = await fetch_and_store.run(SAMPLE)
    assert (first.duplicate, again.duplicate) == (False, True)
    assert (again.document_id, again.storage_key) == (first.document_id, first.storage_key)
    assert raw_store.puts == 1, "the duplicate is found before the raw store is asked"
    assert len(store.documents) == len(store.events) == 1


async def test_the_same_bytes_at_another_url_are_the_same_document() -> None:
    adapter = FakeSourceAdapter.with_sample()
    elsewhere = DocumentRef(adapter.source_id, "https://example.invalid/mirror/17-2026", "17/2026")
    adapter.documents = (
        *adapter.documents,
        (DiscoveredDocument(elsewhere), SAMPLE_TEXT.encode(), "text/plain"),
    )
    fetch_and_store, store, _ = activity(adapter)
    first = await fetch_and_store.run(SAMPLE)
    mirror = await fetch_and_store.run(
        Discovered(source_id=UUID(int=1), url=elsewhere.url, external_ref="17/2026")
    )
    assert mirror.duplicate is True
    assert mirror.url == elsewhere.url, "the result says where this fetch found it"
    (record,) = store.documents.values()
    assert record.source_url == first.url, "the record keeps where it was first found"
    assert len(store.events) == 1


class FailingRawStore(MemoryRawStore):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def put(self, raw: RawDocument) -> str:
        if self.failures:
            self.failures -= 1
            raise RawStoreError("S3 PUT raw/ab/...: 503 SlowDown")
        return super().put(raw)


async def test_a_raw_store_failure_writes_no_row_and_the_retry_stores_it() -> None:
    raw_store = FailingRawStore(failures=1)
    fetch_and_store, store, _ = activity(raw_store=raw_store)
    with pytest.raises(RawStoreError, match="503"):
        await fetch_and_store.run(SAMPLE)
    assert (store.documents, store.events, raw_store.files) == ({}, [], {})
    retried = await fetch_and_store.run(SAMPLE)
    assert retried.duplicate is False
    assert len(store.documents) == len(store.events) == 1


class FailingWrites(MemoryStore):
    """A store whose next write unit fails at the commit, after its writes."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_next_write = True
        self.units = 0

    def __call__(self) -> AbstractContextManager[UnitOfWork]:
        return self._failing()

    @contextmanager
    def _failing(self) -> Iterator[UnitOfWork]:
        self.units += 1
        with super().__call__() as unit:
            yield unit
            if unit.events.pending and self.fail_next_write:  # type: ignore[attr-defined]
                self.fail_next_write = False
                raise ConnectionError("the database went away at the commit")


async def test_a_failed_transaction_leaves_the_file_and_no_row_or_event() -> None:
    store = FailingWrites()
    fetch_and_store, _, raw_store = activity(store=store)
    with pytest.raises(ConnectionError):
        await fetch_and_store.run(SAMPLE)
    assert (store.documents, store.events, store.sources) == ({}, [], {})
    assert len(raw_store.files) == 1, "the file is kept; storing it again stores nothing"
    retried = await fetch_and_store.run(SAMPLE)
    assert retried.duplicate is False
    assert len(raw_store.files) == 1
    assert len(store.documents) == len(store.events) == 1


class RacingStore(MemoryStore):
    """Runs ``rival``, another fetch of the same bytes, to its commit just before the second
    unit of work opens: between the look-up that found nothing and the insert."""

    def __init__(self, rival: Callable[[], object]) -> None:
        super().__init__()
        self._rival = rival
        self.opened = 0

    def __call__(self) -> AbstractContextManager[UnitOfWork]:
        self.opened += 1
        if self.opened == 2:
            self._rival()
        return super().__call__()


async def test_a_lost_race_is_a_duplicate_and_announces_nothing() -> None:
    raw_store = MemoryRawStore()

    def rival() -> object:
        request = StoreRequest(SourceId(SAMPLE.source_id), SAMPLE.url, SAMPLE.external_ref)
        return StoreDocument(sample_catalog(), store, raw_store).run(request)

    store = RacingStore(rival)
    loser = await FetchAndStore(StoreDocument(sample_catalog(), store, raw_store)).run(SAMPLE)
    assert store.opened == 4, "the loser's look-up and insert, the rival's two in between"
    assert loser.duplicate is True
    assert len(store.documents) == len(store.events) == 1


async def test_the_activity_heartbeats_while_the_fetch_runs() -> None:
    class SlowAdapter(FakeSourceAdapter):
        def fetch(self, ref: DocumentRef) -> RawDocument:
            time.sleep(0.2)
            return super().fetch(ref)

    sample = FakeSourceAdapter.with_sample()
    slow = SlowAdapter(sample.source_id, sample.documents)
    store = StoreDocument(sample_catalog(slow), MemoryStore(), MemoryRawStore())
    environment = ActivityEnvironment()
    beats: list[object] = []
    environment.on_heartbeat = lambda *details: beats.append(details)
    fetch_and_store = FetchAndStore(store, heartbeat_seconds=0.05)
    stored = await environment.run(fetch_and_store.definition(), SAMPLE)
    assert stored.duplicate is False
    assert len(beats) >= 2


async def test_a_recorded_cbic_notification_is_stored_as_its_source_lists_it() -> None:
    client = PoliteClient(
        ClientConfig(min_delay_seconds=0, respect_robots=False),
        transport=recorded_sources(FIXTURES),
        sleep=lambda _: None,
    )
    store, raw_store = MemoryStore(), MemoryRawStore()
    fetch_and_store = FetchAndStore(StoreDocument(RegistryCatalog(client), store, raw_store))
    discovered = Discovered(
        source_id=source_id_for("cbic_notifications").value,
        url=CBIC_PDF + "gst-ct-17-2025.pdf",
        external_ref="17/2025-Central Tax",
        title="Seeks to extend the due date for FORM GSTR-3B",
        published_at=date(2025, 9, 18),
    )
    stored = await fetch_and_store.run(discovered)
    assert (stored.source_key, stored.regulator, stored.media_type) == (
        "cbic_notifications",
        "CBIC",
        "application/pdf",
    )
    assert raw_store.files[stored.storage_key].startswith(b"%PDF-")
    assert dict(store.sources["cbic_notifications"].parameters) == {
        "listing": "notifications",
        "category": "Central Tax",
    }
    (event,) = store.events
    assert isinstance(event, DocumentDiscovered)
    assert event.source_id == source_id_for("cbic_notifications")
