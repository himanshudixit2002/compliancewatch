"""Conformance: every adapter replayed against the recorded responses of its site."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from domain_kernel.documents import DocumentRef, DocumentType
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import SourceId
from pipeline.domain.errors import UnknownSourceError
from pipeline.infrastructure.adapters import (
    ADAPTER_TYPES,
    SOURCES,
    RegistryCatalog,
    SourceSpec,
    build_adapter,
    source_id_for,
)
from pipeline.infrastructure.adapters.cbic import RECORDED_CATEGORIES, CbicAdapter, hindi_alternate
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


def test_the_cbic_listing_and_category_are_parameters_of_one_adapter_type(
    client: PoliteClient,
) -> None:
    notifications, circulars = SOURCES["cbic_notifications"], SOURCES["cbic_circulars"]
    assert notifications.adapter_type == circulars.adapter_type == "cbic"
    assert dict(notifications.parameters) == {"listing": "notifications", "category": "Central Tax"}
    assert dict(circulars.parameters) == {"listing": "circulars", "category": "Circulars CGST"}
    assert type(notifications.build(client)) is type(circulars.build(client)) is CbicAdapter
    assert (notifications.doc_type, circulars.doc_type) == (
        DocumentType.NOTIFICATION,
        DocumentType.CIRCULAR,
    )
    assert {spec.regulator for spec in (notifications, circulars)} == {"CBIC"}
    assert set(RECORDED_CATEGORIES) == {"notifications", "circulars"}


@pytest.mark.parametrize(
    ("adapter_type", "parameters", "message"),
    [
        ("cbic", {"listing": "notifications", "category": "Integrated Tax"}, "no recorded listing"),
        ("cbic", {"listing": "orders", "category": "Central Tax"}, "listing"),
        ("cbic", {"listing": "circulars"}, "category"),
        ("gstn", {"page": 2}, "Extra inputs are not permitted"),
    ],
)
def test_parameters_an_adapter_type_does_not_take_are_refused(
    adapter_type: str, parameters: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        SourceSpec("new_source", adapter_type, parameters, timedelta(hours=1))
    with pytest.raises(ValueError, match="unknown adapter type"):
        SourceSpec("new_source", "fssai", {}, timedelta(hours=1))


def test_each_source_is_defined_by_its_type_and_parameters() -> None:
    assert sorted(ADAPTER_TYPES) == ["cbic", "gstcouncil", "gstn", "mahagst", "upload"]
    definitions = {key: spec.definition() for key, spec in SOURCES.items()}
    assert {key: (d.adapter_type, d.regulator, d.doc_type) for key, d in definitions.items()} == {
        "cbic_notifications": ("cbic", "CBIC", DocumentType.NOTIFICATION),
        "cbic_circulars": ("cbic", "CBIC", DocumentType.CIRCULAR),
        "gstcouncil_press": ("gstcouncil", "GST Council", DocumentType.PRESS_RELEASE),
        "gstn_advisories": ("gstn", "GSTN", DocumentType.PRESS_RELEASE),
        "mahagst_notifications": ("mahagst", "Maharashtra GST", DocumentType.NOTIFICATION),
        "cgst_act": ("upload", "CBIC", DocumentType.STATUTE),
        "cgst_rules": ("upload", "CBIC", DocumentType.STATUTE),
        "igst_act": ("upload", "CBIC", DocumentType.STATUTE),
    }
    assert [key for key, spec in SOURCES.items() if not spec.kind.listable] == [
        "cgst_act",
        "cgst_rules",
        "igst_act",
    ]
    assert definitions["cbic_notifications"].cadence <= timedelta(hours=6), "F1: within 6 h"
    assert {spec.site for spec in SOURCES.values()} >= {"taxinformation.cbic.gov.in"}


def test_the_catalog_serves_the_built_in_sources_by_id(client: PoliteClient) -> None:
    catalog = RegistryCatalog(client)
    resolved = catalog.resolve(source_id_for("gstn_advisories"))
    assert resolved.source_id == SOURCES["gstn_advisories"].source_id
    assert resolved.definition == SOURCES["gstn_advisories"].definition()
    assert catalog.resolve(source_id_for("gstn_advisories")).adapter is resolved.adapter
    listed = list(resolved.adapter.list_documents(datetime(2026, 8, 1, tzinfo=UTC)))
    assert [d.ref.source_id for d in listed] == [resolved.source_id] * 3
    with pytest.raises(UnknownSourceError, match="no source has the id"):
        catalog.resolve(SourceId(UUID(int=1)))


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


def test_an_upload_only_source_lists_and_fetches_nothing(client: PoliteClient) -> None:
    adapter = SOURCES["cgst_act"].build(client)
    assert list(adapter.list_documents(datetime(2000, 1, 1, tzinfo=UTC))) == []
    ref = DocumentRef(source_id_for("cgst_act"), "https://example.invalid/act.pdf")
    with pytest.raises(InvariantViolationError, match="upload-only"):
        adapter.fetch(ref)
    kind = ADAPTER_TYPES["upload"]
    read = kind.validated({"document_type": "notification", "regulator": "Example GST"})
    assert (kind.regulator_for(read), kind.doc_type(read)) == (
        "Example GST",
        DocumentType.NOTIFICATION,
    )
    with pytest.raises(ValidationError):
        kind.validated({"regulator": " "})
