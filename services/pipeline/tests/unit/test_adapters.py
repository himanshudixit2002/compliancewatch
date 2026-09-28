"""Conformance: every adapter replayed against the recorded responses of its site."""

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from domain_kernel.documents import DocumentType
from pipeline.infrastructure.adapters import SOURCES, build_adapter, source_id_for
from pipeline.infrastructure.adapters.cbic import hindi_alternate
from pipeline.infrastructure.http import ClientConfig, PoliteClient
from pipeline.testing import CBIC, FixtureTransport, recorded_sources

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONFIG = ClientConfig(min_delay_seconds=0, respect_robots=False)


@pytest.fixture
def transport() -> FixtureTransport:
    return recorded_sources(FIXTURES)


@pytest.fixture
def client(transport: FixtureTransport) -> PoliteClient:
    return PoliteClient(CONFIG, transport=transport, sleep=lambda _: None)


def test_source_ids_are_stable_and_distinct() -> None:
    assert source_id_for("cbic_notifications") == source_id_for("cbic_notifications")
    assert len({spec.source_id for spec in SOURCES.values()}) == len(SOURCES)
    assert isinstance(SOURCES["cbic_notifications"].source_id.value, UUID)
    with pytest.raises(KeyError, match="unknown source"):
        build_adapter("nope", PoliteClient(CONFIG))


def test_cbic_notifications_list_newest_first_until_since(
    client: PoliteClient, transport: FixtureTransport
) -> None:
    adapter = build_adapter("cbic_notifications", client)
    listed = list(adapter.list_documents(datetime(2025, 9, 1, tzinfo=UTC)))
    assert [d.ref.external_ref for d in listed][:2] == [
        "02/2026-Central Tax",
        "01/2026-Central Tax",
    ]
    assert listed[0].published_at == date(2026, 5, 7)
    assert all(d.published_at and d.published_at >= date(2025, 9, 1) for d in listed)
    assert len(listed) == 10
    assert (
        listed[1].ref.url
        == f"{CBIC}/content/pdf/tax_repository/gst/notifications/gst-ct-01-2026.pdf"
    )
    methods = [(r.method, r.url.path) for r in transport.requests]
    assert methods[0] == ("POST", "/api/authenticate-token")
    assert methods.count(("POST", "/api/authenticate-token")) == 1


def test_cbic_fetch_unwraps_the_json_pdf(client: PoliteClient) -> None:
    adapter = build_adapter("cbic_notifications", client)
    listed = list(adapter.list_documents(datetime(2026, 4, 1, tzinfo=UTC)))
    raw = adapter.fetch(listed[1].ref)
    assert raw.media_type == "application/pdf"
    assert raw.content.startswith(b"%PDF-")
    assert raw.ref == listed[1].ref


def test_cbic_hindi_alternate_path() -> None:
    item = {
        "docFilePath": "tax_repository\\gst\\notifications\\gst-ct-01-2026.pdf",
        "docFileNameHi": "gst-ct-01h-2026.pdf",
    }
    assert (
        hindi_alternate(item)
        == f"{CBIC}/content/pdf/tax_repository/gst/notifications/gst-ct-01h-2026.pdf"
    )
    assert hindi_alternate({"docFilePath": "x.pdf", "docFileNameHi": ""}) is None


def test_cbic_circulars(client: PoliteClient) -> None:
    listed = list(
        build_adapter("cbic_circulars", client).list_documents(datetime(2026, 1, 1, tzinfo=UTC))
    )
    assert [d.ref.external_ref for d in listed] == ["256/02/2026-GST", "255/01/2026-GST"]
    assert SOURCES["cbic_circulars"].doc_type is DocumentType.CIRCULAR


def test_gst_council_archive_pages_until_since(
    client: PoliteClient, transport: FixtureTransport
) -> None:
    adapter = build_adapter("gstcouncil_press", client)
    listed = list(adapter.list_documents(datetime(2023, 8, 1, tzinfo=UTC)))
    assert listed[0].published_at == date(2025, 9, 3)
    assert listed[0].title.startswith("Frequently Asked Questions")
    assert listed[0].ref.url == "https://gstcouncil.gov.in/sites/default/files/2025-09/faq.pdf"
    last = listed[-1].published_at
    assert last is not None
    assert last >= date(2023, 8, 1)
    assert any("pib.gov.in" in d.ref.url for d in listed)
    assert len(listed) == 11
    assert [r.url.params.get("page") for r in transport.requests] == ["0", "1"]
    raw = adapter.fetch(listed[0].ref)
    assert raw.media_type == "application/pdf"
    assert raw.content.startswith(b"%PDF-")


def test_gst_council_lists_everything_when_since_is_old(client: PoliteClient) -> None:
    listed = list(
        build_adapter("gstcouncil_press", client).list_documents(datetime(2000, 1, 1, tzinfo=UTC))
    )
    assert len(listed) == 20


def test_gstn_advisories_come_from_the_feed(client: PoliteClient) -> None:
    adapter = build_adapter("gstn_advisories", client)
    listed = list(adapter.list_documents(datetime(2026, 8, 1, tzinfo=UTC)))
    assert [d.ref.external_ref for d in listed] == ["672", "671", "670"]
    assert listed[0].published_at == date(2026, 9, 19)
    assert listed[0].ref.url == "https://www.gst.gov.in/newsandupdates/read/672"
    raw = adapter.fetch(listed[0].ref)
    assert raw.media_type == "text/html"
    assert b"emSigner" in raw.content
    assert adapter.fetch(listed[0].ref).sha256 == raw.sha256


def test_mahagst_lists_every_pdf_once_without_dates(
    client: PoliteClient, transport: FixtureTransport
) -> None:
    adapter = build_adapter("mahagst_notifications", client)
    listed = list(adapter.list_documents(datetime(2026, 1, 1, tzinfo=UTC)))
    assert len(listed) == len({d.ref.url for d in listed}) == 7
    assert all(d.published_at is None for d in listed)
    assert all(
        d.ref.url.startswith("https://www.mahagst.gov.in/public/uploads/notifications/")
        for d in listed
    )
    assert all(" " not in d.ref.url for d in listed)
    assert "Reset Password User Manual" in {d.title for d in listed}
    pdf = (FIXTURES / "gstcouncil" / "faq-56th-council.pdf").read_bytes()
    transport.body("GET", listed[0].ref.url, pdf, "application/octet-stream")
    raw = adapter.fetch(listed[0].ref)
    assert raw.media_type == "application/pdf"
    assert raw.content == pdf


def test_an_unrecorded_url_fails_loudly(client: PoliteClient) -> None:
    response = client.get("https://gstcouncil.gov.in/nowhere")
    assert response.status_code == 404
    assert "unrecorded" in response.text
