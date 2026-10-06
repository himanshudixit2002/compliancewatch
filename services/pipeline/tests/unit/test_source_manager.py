"""The source manager's use cases on the memory store: the built-in sources added once, each
source as the API shows it, an admin's additions and edits with their audit entries, and the
documents and stored bytes read back."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from domain_kernel.audit import AuditActor
from domain_kernel.documents import DocumentType, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId, UserId
from pipeline.application.sources import (
    ADD_ACTION,
    EDIT_ACTION,
    AddSource,
    AdminAction,
    EditSource,
    ListSourceDocuments,
    ListSources,
    NewSource,
    ReadDocument,
    ReadRawDocument,
    SourceEdit,
    SyncSources,
    require_reason,
)
from pipeline.domain.crawl import CrawlRun
from pipeline.domain.errors import (
    DocumentNotFoundError,
    RawDocumentUnreadableError,
    RawStoreError,
    RawStoreUnavailableError,
    SourceExistsError,
    SourceInvalidError,
    SourceNotFoundError,
)
from pipeline.domain.raw_documents import RawDocumentRecord
from pipeline.domain.repository import DocumentKey
from pipeline.domain.schedule import FreshnessState, SourceStatus
from pipeline.domain.sources import Source
from pipeline.infrastructure.adapters import SOURCES, RegistryAdapterTypes
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.raw_store import MemoryRawStore, storage_key_for

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
ADMIN = AdminAction(
    actor=AuditActor.user(UserId(UUID(int=7))),
    reason="Synthetic reason for a test",
    correlation_id="0123456789abcdef0123456789abcdef",
)
TYPES = RegistryAdapterTypes()
DEFINITIONS = [spec.definition() for spec in SOURCES.values()]


def clock() -> datetime:
    return NOW


def synced() -> MemoryStore:
    store = MemoryStore()
    SyncSources(store, DEFINITIONS, clock=clock).run()
    return store


def stored(store: MemoryStore, content: bytes, **overrides: object) -> RawDocumentRecord:
    digest = hashlib.sha256(content).hexdigest()
    values: dict[str, object] = {
        "document_id": document_id_for(digest),
        "source_key": "cbic_notifications",
        "source_url": f"https://example.invalid/{digest[:8]}.pdf",
        "fetched_at": NOW,
        "content_type": "application/pdf",
        "size": len(content),
        "sha256": digest,
        "storage_key": storage_key_for(digest),
    }
    values.update(overrides)
    record = RawDocumentRecord(**values)  # type: ignore[arg-type]
    with store() as unit:
        assert unit.documents.add(record)
    return record


def new_source(**overrides: object) -> NewSource:
    values: dict[str, object] = {
        "key": "cbic_integrated",
        "name": "CBIC Integrated Tax notifications",
        "adapter_type": "cbic",
        "parameters": {"listing": "notifications", "category": "Central Tax"},
        "cadence": timedelta(hours=1),
    }
    values.update(overrides)
    return NewSource(**values)  # type: ignore[arg-type]


def test_the_built_in_sources_are_added_once_and_never_changed() -> None:
    store = MemoryStore()
    sync = SyncSources(store, DEFINITIONS, clock=clock)
    report = sync.run()
    assert sorted(report.added) == sorted(SOURCES)
    with store() as unit:
        cbic = unit.sources.get("cbic_notifications")
        assert cbic is not None
        unit.sources.save(cbic.edited(NOW, cadence=timedelta(hours=1), paused=True))
    assert sync.run().added == ()
    kept = store.sources["cbic_notifications"]
    assert (kept.cadence, kept.paused) == (timedelta(hours=1), True), "an admin's edit stays"


def test_a_built_in_row_stored_without_a_name_is_named() -> None:
    store = MemoryStore()
    with store() as unit:
        nameless = Source(
            key="gstn_advisories",
            adapter_type="gstn",
            parameters={},
            cadence=timedelta(hours=3),
            created_at=NOW,
            updated_at=NOW,
        )
        unit.sources.add(nameless)
    report = SyncSources(store, DEFINITIONS, clock=clock).run()
    assert report.named == ("gstn_advisories",)
    assert store.sources["gstn_advisories"].name == "GSTN advisories"


def test_each_source_with_its_kind_status_freshness_and_counts() -> None:
    store = synced()
    stored(store, b"%PDF one")
    stored(store, b"%PDF two")
    with store() as unit:
        unit.crawl_runs.add(CrawlRun.start("gstn_advisories", NOW - timedelta(minutes=5)))
        unit.sources.add(
            Source(
                key="retired",
                adapter_type="gone",
                parameters={},
                cadence=timedelta(hours=1),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    views = {view.source.key: view for view in ListSources(store, TYPES, clock=clock).run()}
    cbic = views["cbic_notifications"]
    assert cbic.kind is not None
    assert (cbic.kind.regulator, cbic.kind.doc_type) == ("CBIC", DocumentType.NOTIFICATION)
    assert (cbic.document_count, cbic.status) == (2, SourceStatus.HEALTHY)
    assert cbic.freshness.state is FreshnessState.NEVER
    assert views["gstn_advisories"].status is SourceStatus.FETCHING
    assert views["retired"].kind is None, "a type the code lacks is shown, not refused"
    one = ListSources(store, TYPES, clock=clock).one("cbic_notifications")
    assert one.document_count == 2
    with pytest.raises(SourceNotFoundError):
        ListSources(store, TYPES, clock=clock).one("nowhere")


def test_an_admin_adds_a_source_whose_type_checks_its_parameters() -> None:
    store = synced()
    added = AddSource(store, TYPES, clock=clock).run(new_source(), ADMIN)
    assert dict(added.parameters) == {"listing": "notifications", "category": "Central Tax"}
    (entry,) = store.audit
    assert (entry.action, entry.subject_type, entry.subject_id) == (
        ADD_ACTION,
        "source",
        "cbic_integrated",
    )
    assert (entry.tenant_id, entry.before, entry.reason) == (None, None, ADMIN.reason)
    assert entry.after is not None
    assert entry.after["cadence_seconds"] == 3600
    assert entry.correlation_id == ADMIN.correlation_id
    with pytest.raises(SourceExistsError):
        AddSource(store, TYPES, clock=clock).run(new_source(), ADMIN)
    assert len(store.audit) == 1, "a refused write is not audited"


@pytest.mark.parametrize(
    ("overrides", "error", "says"),
    [
        ({"adapter_type": "nowhere"}, SourceInvalidError, "unknown adapter type 'nowhere'"),
        ({"parameters": {"listing": "notifications"}}, SourceInvalidError, "category"),
        (
            {"parameters": {"listing": "notifications", "category": "Integrated Tax"}},
            SourceInvalidError,
            "has no recorded listing",
        ),
        ({"adapter_type": "gstn", "parameters": {"page": 2}}, SourceInvalidError, "page"),
        ({"cadence": timedelta(days=40)}, InvariantViolationError, "at most"),
        ({"key": "Bad Key"}, InvariantViolationError, "key"),
    ],
)
def test_a_source_the_registry_cannot_read_is_refused(
    overrides: dict[str, object], error: type[Exception], says: str
) -> None:
    store = synced()
    with pytest.raises(error, match=says):
        AddSource(store, TYPES, clock=clock).run(new_source(**overrides), ADMIN)
    assert store.audit == []


def test_a_write_needs_a_reason() -> None:
    assert require_reason("  ten chars!  ") == "ten chars!"
    with pytest.raises(InvariantViolationError, match="reason"):
        AddSource(MemoryStore(), TYPES).run(
            new_source(), AdminAction(actor=ADMIN.actor, reason="short")
        )


def test_an_admin_edits_a_source_and_the_entry_holds_before_and_after() -> None:
    store = synced()
    edit = EditSource(store, TYPES, clock=lambda: NOW + timedelta(hours=1))
    after = edit.run(
        "cbic_circulars",
        SourceEdit(cadence=timedelta(hours=12), paused=True, name="CGST circulars"),
        ADMIN,
    )
    assert (after.cadence, after.paused, after.name) == (
        timedelta(hours=12),
        True,
        "CGST circulars",
    )
    assert after.updated_at == NOW + timedelta(hours=1)
    (entry,) = store.audit
    assert entry.action == EDIT_ACTION
    assert entry.before is not None
    assert entry.after is not None
    assert (entry.before["paused"], entry.after["paused"]) == (False, True)
    assert (entry.before["cadence_seconds"], entry.after["cadence_seconds"]) == (21600, 43200)


def test_an_edit_that_changes_nothing_writes_nothing() -> None:
    store = synced()
    before = store.sources["gstn_advisories"]
    same = EditSource(store, TYPES, clock=clock).run(
        "gstn_advisories", SourceEdit(cadence=before.cadence, parameters={}), ADMIN
    )
    assert same == before
    assert store.audit == []


def test_edited_parameters_are_checked_by_the_sources_type() -> None:
    store = synced()
    edit = EditSource(store, TYPES, clock=clock)
    with pytest.raises(SourceInvalidError, match="no recorded listing"):
        edit.run(
            "cbic_notifications",
            SourceEdit(parameters={"listing": "notifications", "category": "Cess"}),
            ADMIN,
        )
    with pytest.raises(SourceNotFoundError):
        edit.run("nowhere", SourceEdit(paused=True), ADMIN)
    assert store.audit == []


def test_a_sources_documents_come_a_page_at_a_time_newest_first() -> None:
    store = synced()
    older = stored(store, b"%PDF older", published_on=date(2026, 8, 1))
    newer = stored(store, b"%PDF newer", published_on=date(2026, 9, 19))
    undated = stored(store, b"%PDF undated", published_on=None)
    same_day = stored(
        store, b"%PDF same day", published_on=date(2026, 9, 19), fetched_at=NOW + timedelta(1)
    )
    documents = ListSourceDocuments(store)
    everything = documents.run("cbic_notifications", after=None, limit=10)
    assert [d.document_id for d in everything] == [
        same_day.document_id,
        newer.document_id,
        older.document_id,
        undated.document_id,
    ]
    pages: list[DocumentId] = []
    after: DocumentKey | None = None
    while True:
        page = documents.run("cbic_notifications", after=after, limit=1)
        if not page:
            break
        pages.append(page[0].document_id)
        after = DocumentKey.of(page[0])
    assert pages == [d.document_id for d in everything]
    assert documents.run("gstn_advisories", after=None, limit=5) == []
    with pytest.raises(SourceNotFoundError):
        documents.run("nowhere", after=None, limit=5)


def test_a_document_and_its_bytes_are_read_back_checked() -> None:
    store, raw = synced(), MemoryRawStore()
    content = b"%PDF-1.7 the notification"
    record = stored(store, content)
    raw.files[record.storage_key] = content
    assert ReadDocument(store).run(record.document_id) == record
    file = ReadRawDocument(store, raw).run(record.document_id)
    assert (file.record, file.content) == (record, content)
    with pytest.raises(DocumentNotFoundError):
        ReadDocument(store).run(DocumentId(UUID(int=3)))


def test_bytes_that_are_lost_or_altered_are_never_served() -> None:
    store, raw = synced(), MemoryRawStore()
    record = stored(store, b"%PDF-1.7 lost")
    with pytest.raises(RawDocumentUnreadableError):
        ReadRawDocument(store, raw).run(record.document_id)
    raw.files[record.storage_key] = b"%PDF-1.7 altered"
    with pytest.raises(RawDocumentUnreadableError):
        ReadRawDocument(store, raw).run(record.document_id)


def test_a_record_whose_digest_differs_from_its_key_is_never_served() -> None:
    store, raw = synced(), MemoryRawStore()
    content = b"%PDF-1.7 elsewhere"
    other = hashlib.sha256(b"%PDF-1.7 the key's own").hexdigest()
    record = stored(store, content, storage_key=storage_key_for(other))
    raw.files[record.storage_key] = b"%PDF-1.7 the key's own"
    with pytest.raises(RawDocumentUnreadableError):
        ReadRawDocument(store, raw).run(record.document_id)


class AwayStore(MemoryRawStore):
    def get(self, storage_key: str) -> bytes:
        raise RawStoreError("the bucket did not answer")


def test_a_raw_store_that_does_not_answer_is_unavailable() -> None:
    store = synced()
    record = stored(store, b"%PDF-1.7 away")
    with pytest.raises(RawStoreUnavailableError):
        ReadRawDocument(store, AwayStore()).run(record.document_id)
