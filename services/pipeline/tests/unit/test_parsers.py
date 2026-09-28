import base64
import io
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from domain_kernel.documents import DocumentRef, DocumentType, RawDocument, document_id_for
from domain_kernel.ids import SourceId
from pipeline.infrastructure.parsers import (
    LANGUAGE_ENGLISH,
    LANGUAGE_HINDI,
    HtmlParser,
    PdfParser,
    detect_language,
    split_clauses,
)
from pipeline.infrastructure.parsers.html import html_to_text
from pipeline.infrastructure.parsers.pdf import UnparsedDocumentError
from pipeline.infrastructure.parsers.text import renumber

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = DocumentRef(SourceId.new(), "https://example.test/doc")


def pdf_fixture(name: str) -> RawDocument:
    wrapper = json.loads((FIXTURES / "cbic" / name).read_text())
    return RawDocument.from_bytes(REF, base64.b64decode(wrapper["data"]), "application/pdf")


def test_detect_language() -> None:
    assert detect_language("In exercise of the powers conferred by section 39") == LANGUAGE_ENGLISH
    assert detect_language("केन्द्रीय माल और सेवा कर अधिनियम") == LANGUAGE_HINDI
    assert detect_language("अधिसूचना Notification No. 01/2026 केन्द्रीय कर Central Tax") == "mul"
    assert detect_language("12345") == LANGUAGE_ENGLISH


def test_split_clauses_breaks_on_blank_lines_and_numbered_items() -> None:
    text = "Title line\n\n1. First item\ncontinues here\n2. Second item\n\n(a) sub item"
    clauses = split_clauses(text, page=1)
    assert [c.ref for c in clauses] == ["en.p1", "en.p2", "en.p3", "en.p4"]
    assert clauses[1].text == "1. First item continues here"
    assert clauses[2].text == "2. Second item"
    assert all(c.page == 1 for c in clauses)


def test_renumber_counts_per_language_across_pages() -> None:
    clauses = split_clauses("अधिसूचना\n\nNotification", page=1) + split_clauses("Second", page=2)
    assert [c.ref for c in renumber(clauses)] == ["hi.p1", "en.p1", "en.p2"]


def test_pdf_parser_reads_the_english_cbic_notification() -> None:
    raw = pdf_fixture("gst-ct-01-2026.pdf.json")
    parser = PdfParser()
    assert parser.supports(raw)
    parsed = parser.parse(raw)
    assert parsed.doc_type is DocumentType.NOTIFICATION
    assert parsed.language == LANGUAGE_ENGLISH
    assert len(parsed.clauses) >= 3
    assert parsed.clauses[0].clause_ref == "en.p1"
    assert parsed.clauses[0].page == 1
    assert "2026" in " ".join(clause.text for clause in parsed.clauses)
    assert len({clause.clause_ref for clause in parsed.clauses}) == len(parsed.clauses)
    assert parsed.parser_version == "pdf@1"
    assert parsed.document_id == document_id_for(raw.sha256)


def test_pdf_parser_reads_the_hindi_rendering_as_hindi() -> None:
    parsed = PdfParser().parse(pdf_fixture("gst-ct-01h-2026.pdf.json"))
    assert parsed.language == LANGUAGE_HINDI
    assert parsed.clauses[0].clause_ref.startswith("hi.")


def test_a_pdf_without_a_text_layer_is_reported_unparsed() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    raw = RawDocument.from_bytes(REF, buffer.getvalue(), "application/pdf")
    with pytest.raises(UnparsedDocumentError):
        PdfParser().parse(raw)


def test_html_parser_keeps_block_text_and_drops_scripts() -> None:
    html = (
        "<html><head><title>T</title><script>var x = 1;</script></head><body>"
        "<h1>Advisory on filing</h1><p>First &amp; foremost.</p><ul><li>one</li><li>two</li></ul>"
        "</body></html>"
    )
    raw = RawDocument.from_bytes(REF, html.encode(), "text/html; charset=utf-8")
    parser = HtmlParser()
    assert parser.supports(raw)
    parsed = parser.parse(raw)
    assert parsed.doc_type is DocumentType.PRESS_RELEASE
    assert parsed.parser_version == "html@1"
    assert [c.text for c in parsed.clauses] == [
        "T",
        "Advisory on filing",
        "First & foremost.",
        "one",
        "two",
    ]
    assert parsed.title == "T"
    assert "var x" not in html_to_text(html)
