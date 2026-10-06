from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from temporalio.testing import ActivityEnvironment

from domain_kernel.documents import DiscoveredDocument, DocumentRef, RawDocument
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import SourceId
from pipeline.application.activities import (
    DiscoverDocument,
    Discovered,
    DiscoverRequest,
    FetchAndStore,
    FetchDocument,
    Fetched,
    NothingDiscoveredError,
    Parsed,
    ParseDocument,
    ParseRequest,
    UnsupportedDocumentError,
    document_id_for,
)
from pipeline.domain.errors import UnknownSourceError
from pipeline.infrastructure.fakes import (
    SAMPLE_TEXT,
    FakePlainTextParser,
    FakeSourceAdapter,
    sample_catalog,
)

SINCE = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def adapter() -> FakeSourceAdapter:
    return FakeSourceAdapter.with_sample()


async def test_discover_returns_the_first_listed_document(adapter: FakeSourceAdapter) -> None:
    request = DiscoverRequest(source_id=adapter.source_id.value, since=SINCE)
    discovered = await ActivityEnvironment().run(
        DiscoverDocument(sample_catalog(adapter)).definition(), request
    )
    assert discovered == Discovered(
        source_id=adapter.source_id.value,
        url="https://example.invalid/notifications/17-2026",
        external_ref="17/2026",
        title="Notification No. 17/2026 - Central Tax",
        published_at=None,
    )


async def test_discover_rejects_a_future_since(adapter: FakeSourceAdapter) -> None:
    request = DiscoverRequest(
        source_id=adapter.source_id.value, since=datetime.now(UTC) + timedelta(days=3)
    )
    with pytest.raises(ValueError, match="future"):
        await DiscoverDocument(sample_catalog(adapter)).execute(request)


async def test_discover_fails_when_the_source_lists_nothing() -> None:
    empty = FakeSourceAdapter(SourceId.new())
    with pytest.raises(NothingDiscoveredError):
        await DiscoverDocument(sample_catalog(empty)).execute(
            DiscoverRequest(source_id=empty.source_id.value, since=SINCE)
        )


async def test_an_unknown_source_is_refused_and_not_retried() -> None:
    request = DiscoverRequest(source_id=SourceId.new().value, since=SINCE)
    with pytest.raises(UnknownSourceError):
        await DiscoverDocument(sample_catalog()).execute(request)
    for activity in (DiscoverDocument, FetchDocument, FetchAndStore):
        assert "UnknownSourceError" in (activity.retry_policy.non_retryable_error_types or [])


async def test_fetch_carries_bytes_digest_and_media_type(adapter: FakeSourceAdapter) -> None:
    discovered = await DiscoverDocument(sample_catalog(adapter)).execute(
        DiscoverRequest(source_id=adapter.source_id.value, since=SINCE)
    )
    fetched = await ActivityEnvironment().run(
        FetchDocument(sample_catalog(adapter)).definition(), discovered
    )
    assert fetched.content == SAMPLE_TEXT.encode()
    assert fetched.media_type == "text/plain"
    assert (
        fetched.sha256
        == RawDocument.from_bytes(
            DocumentRef(adapter.source_id, discovered.url, "17/2026"), fetched.content, "text/plain"
        ).sha256
    )
    assert fetched.fetched_at.tzinfo is not None
    assert adapter.fetches == 1


async def test_fetch_of_an_unknown_document_is_not_retried() -> None:
    adapter = FakeSourceAdapter.with_sample()
    unknown = Discovered(source_id=adapter.source_id.value, url="https://example.invalid/other")
    with pytest.raises(InvariantViolationError, match="unknown document"):
        await FetchDocument(sample_catalog(adapter)).execute(unknown)
    assert "InvariantViolationError" in (FetchDocument.retry_policy.non_retryable_error_types or [])


async def test_fetch_record_rejects_empty_content(adapter: FakeSourceAdapter) -> None:
    fetched = Fetched(
        source_id=adapter.source_id.value,
        url="https://example.invalid/x",
        media_type="text/plain",
        sha256="0" * 64,
        fetched_at=SINCE,
        content=b"",
    )
    with pytest.raises(InvariantViolationError, match="empty"):
        FetchDocument(sample_catalog(adapter)).record(
            Discovered(source_id=adapter.source_id.value, url="https://example.invalid/x"), fetched
        )


async def test_parse_splits_paragraphs_into_clauses(adapter: FakeSourceAdapter) -> None:
    discovered = await DiscoverDocument(sample_catalog(adapter)).execute(
        DiscoverRequest(source_id=adapter.source_id.value, since=SINCE)
    )
    fetched = await FetchDocument(sample_catalog(adapter)).execute(discovered)
    request = ParseRequest(
        document_id=document_id_for(fetched).value, fetched=fetched, title=discovered.title
    )
    parsed = await ActivityEnvironment().run(
        ParseDocument(FakePlainTextParser()).definition(), request
    )
    assert parsed == Parsed(
        document_id=UUID(fetched.sha256[:32]),
        doc_type="notification",
        title="Notification No. 17/2026 - Central Tax",
        language="en",
        clause_count=3,
        clause_refs=["p1", "p2", "p3"],
    )
    assert parsed.document_id == document_id_for(fetched).value


def test_the_fake_parser_names_its_version() -> None:
    ref = DocumentRef(SourceId(UUID(int=1)), "memory://sample")
    raw = RawDocument.from_bytes(ref, SAMPLE_TEXT.encode(), "text/plain")
    assert FakePlainTextParser().parse(raw).parser_version == "fake@1"


async def test_parse_refuses_an_unsupported_media_type(adapter: FakeSourceAdapter) -> None:
    discovered = await DiscoverDocument(sample_catalog(adapter)).execute(
        DiscoverRequest(source_id=adapter.source_id.value, since=SINCE)
    )
    fetched = await FetchDocument(sample_catalog(adapter)).execute(discovered)
    pdf = fetched.model_copy(update={"media_type": "application/pdf"})
    with pytest.raises(UnsupportedDocumentError, match="application/pdf"):
        await ParseDocument(FakePlainTextParser()).execute(
            ParseRequest(document_id=document_id_for(pdf).value, fetched=pdf)
        )
    assert "UnsupportedDocumentError" in (
        ParseDocument.retry_policy.non_retryable_error_types or []
    )


def test_fake_adapter_lists_and_fetches_what_it_was_given() -> None:
    adapter = FakeSourceAdapter.with_sample()
    (listed,) = list(adapter.list_documents(SINCE))
    assert isinstance(listed, DiscoveredDocument)
    raw = adapter.fetch(listed.ref)
    assert raw.media_type == "text/plain"
    assert FakePlainTextParser().supports(raw)
    assert not FakePlainTextParser().supports(
        RawDocument.from_bytes(listed.ref, b"%PDF-1.7", "application/pdf")
    )
