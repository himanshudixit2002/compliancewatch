"""The parser chain on recorded documents: a table-heavy notification (10/2025-Central Tax, a
table of jurisdictions whose rows wrap over several lines) keeps its rows with pdf-tables@1,
prose notifications stay with pdf@1 and their clauses, recorded listing pages keep their table
rows with html-tables@1, and a document parses with the parser that parsed it before."""

import base64
import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from domain_kernel.documents import (
    Clause,
    DocumentRef,
    DocumentType,
    ParsedDocument,
    RawDocument,
    document_id_for,
)
from domain_kernel.ids import SourceId
from domain_kernel.protocols import DocumentParser
from pipeline.domain.errors import UnparsedDocumentError, UnsupportedDocumentError
from pipeline.domain.ports import ParseHints
from pipeline.domain.structure import CELL_SEPARATOR, Paragraph, Table
from pipeline.domain.transcripts import read_transcript
from pipeline.infrastructure.adapters import RegistryCatalog, source_id_for
from pipeline.infrastructure.http import PoliteClient
from pipeline.infrastructure.parsers import (
    ChainLink,
    DeclinedDocumentError,
    HtmlParser,
    HtmlTableParser,
    ParserChain,
    PdfParser,
    has_table,
    has_tables,
)
from pipeline.infrastructure.parsers.html_tables import html_blocks
from pipeline.infrastructure.parsers.pdf_tables import clean, find_rows, page_blocks

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REF = DocumentRef(SourceId(source_id_for("cbic_notifications").value), "https://example.test/doc")
TABLE_NOTIFICATION = "gst-ct-10-2025.pdf.json"
PROSE = (
    "gst-ct-01-2026.pdf.json",
    "gst-ct-01h-2026.pdf.json",
    "gst-ct-17-2025.pdf.json",
    "centaltax-15-2025.pdf.json",
    "central-tax-13-2024-11072024.pdf.json",
)


def recorded_pdf(name: str) -> RawDocument:
    wrapper = json.loads((FIXTURES / "cbic" / name).read_text())
    return RawDocument.from_bytes(REF, base64.b64decode(wrapper["data"]), "application/pdf")


def recorded_html(relative: str) -> RawDocument:
    return RawDocument.from_bytes(REF, (FIXTURES / relative).read_bytes(), "text/html")


def rows(parsed: ParsedDocument) -> list[list[str]]:
    return [c.text.split(CELL_SEPARATOR) for c in parsed.clauses if CELL_SEPARATOR in c.text]


def test_the_table_notification_keeps_each_row_with_its_cells() -> None:
    parsed = ParserChain().parse_as(recorded_pdf(TABLE_NOTIFICATION), ParseHints())
    assert parsed.parser_version == "pdf-tables@1"
    found = rows(parsed)
    assert [row[:2] for row in found] == [
        ['"7.', "Alwar"],
        ["“23.", "Chennai Outer"],
        ["“49.", "Jaipur"],
        ['"53.', "Jodhpur"],
        ["“63.", "Madurai"],
        ["“100.", "Tiruchirapalli"],
        ['"102.', "Udaipur"],
    ]
    assert all(len(row) == 3 for row in found)
    chennai = found[1][2]
    assert chennai.startswith("Districts of Viluppuram, Kallakurichi, Thiruvannamalai")
    assert "Ranipet, Tiruvallur, Kanchipuram" in chennai, "the wrapped lines in order"
    assert chennai.endswith("in the State of Tamil Nadu”;")
    madurai = found[4][2]
    assert madurai.endswith("the Union territory of Puducherry.”;"), "the cell's second paragraph"
    texts = [c.text for c in parsed.clauses]
    assert (
        "(ii) for serial number 23, and the entries relating thereto, the following shall be "
        "substituted, namely:-"
    ) in texts
    assert "New Delhi, the 13th March, 2025" in texts, "a superscript ordinal joined again"
    assert [c.page for c in parsed.clauses if c.text.startswith("“100.")] == [2]


def test_the_rows_and_their_ids_are_the_same_on_every_parse() -> None:
    chain = ParserChain()
    first = chain.parse_as(recorded_pdf(TABLE_NOTIFICATION), ParseHints())
    again = chain.parse_as(recorded_pdf(TABLE_NOTIFICATION), ParseHints())
    assert first.clauses == again.clauses
    assert [c.clause_ref for c in first.clauses] == [f"en.p{n}" for n in range(1, 25)]


def test_a_document_pdf_1_parsed_before_keeps_its_clauses() -> None:
    raw = recorded_pdf(TABLE_NOTIFICATION)
    kept = ParserChain().parse_as(raw, ParseHints(parser_version="pdf@1"))
    assert kept.parser_version == "pdf@1"
    assert kept.clauses == PdfParser().parse(raw).clauses
    tables = ParserChain().parse_as(raw, ParseHints(parser_version="pdf-tables@1"))
    assert tables.parser_version == "pdf-tables@1"


@pytest.mark.parametrize("name", PROSE)
def test_prose_notifications_stay_with_the_text_layer_parser(name: str) -> None:
    raw = recorded_pdf(name)
    parsed = ParserChain().parse_as(raw, ParseHints())
    assert parsed.parser_version == "pdf@1"
    assert parsed.clauses == PdfParser().parse(raw).clauses


def test_only_the_table_notification_has_tables() -> None:
    def reader(name: str) -> PdfReader:
        return PdfReader(io.BytesIO(recorded_pdf(name).content))

    assert has_tables(reader(TABLE_NOTIFICATION))
    assert not any(has_tables(reader(name)) for name in PROSE)
    faq = PdfReader(io.BytesIO((FIXTURES / "gstcouncil" / "faq-56th-council.pdf").read_bytes()))
    assert not has_tables(faq), "ten pages of justified prose are no table"


def test_recorded_listing_pages_keep_their_table_rows() -> None:
    raw = recorded_html("gstcouncil/archive-press-release-page0.html")
    assert has_table(raw.content.decode())
    parsed = ParserChain().parse_as(raw, ParseHints())
    assert parsed.parser_version == "html-tables@1"
    texts = [c.text for c in parsed.clauses]
    header = texts.index("Sr. No. | Date | Description")
    assert texts[header + 1].startswith(
        "1 | 03-09-2025 | Frequently Asked Questions (FAQs) on the decisions of the 56th GST"
    )
    mahagst = ParserChain().parse_as(recorded_html("mahagst/notifications.html"), ParseHints())
    assert "1 | *** Reset Password User Manual ***" in [c.text for c in mahagst.clauses]


def test_a_page_without_a_table_stays_with_the_html_parser() -> None:
    raw = RawDocument.from_bytes(
        REF, b"<html><body><h1>Advisory</h1><p>Example text.</p></body></html>", "text/html"
    )
    parsed = ParserChain().parse_as(raw, ParseHints())
    assert parsed.parser_version == "html@1"
    assert parsed.clauses == HtmlParser().parse(raw).clauses


def test_the_html_table_parser_reads_headers_cells_and_captions() -> None:
    html = (
        "<html><head><title>Example page</title><style>p {}</style></head><body>"
        "<p>1. Example text\n2. Second example item</p>"
        "<table><caption>Example rates</caption>"
        "<tr><th>S. No.</th><th>Item</th><th>Rate</th></tr>"
        "<tr><td>1</td><td>Example<br>item</td><td>5%</td></tr>"
        "<tr><td>2</td><td><table><tr><td>Nested</td><td>cell</td></tr></table></td><td></td></tr>"
        "</table><script>var x = 1;</script><p>After the table.</p></body></html>"
    )
    blocks = html_blocks(html)
    assert blocks[3] == Paragraph("Example rates")
    assert blocks[4] == Table(
        header=("S. No.", "Item", "Rate"),
        rows=(("1", "Example item", "5%"), ("2", "Nested cell", "")),
    )
    raw = RawDocument.from_bytes(REF, html.encode(), "text/html")
    parsed = HtmlTableParser().parse(raw)
    assert [c.text for c in parsed.clauses] == [
        "Example page",
        "1. Example text",
        "2. Second example item",
        "Example rates",
        "S. No. | Item | Rate",
        "1 | Example item | 5%",
        "2 | Nested cell",
        "After the table.",
    ]
    assert parsed.parser_version == "html-tables@1"
    assert not has_table("<table><tr><td>Only one cell</td></tr></table>")


def blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_a_scan_is_unparsed_with_each_parsers_reason() -> None:
    raw = RawDocument.from_bytes(REF, blank_pdf(), "application/pdf")
    with pytest.raises(UnparsedDocumentError) as caught:
        ParserChain().parse_as(raw, ParseHints())
    assert "pdf@1: UnparsedDocumentError: the PDF has no text layer" in str(caught.value)
    assert "pdf-tables@1: UnparsedDocumentError" in str(caught.value)


def test_bytes_a_parser_cannot_open_are_unparsed_too() -> None:
    raw = RawDocument.from_bytes(REF, b"%PDF-1.7 not really a pdf", "application/pdf")
    with pytest.raises(UnparsedDocumentError, match="pdf@1: "):
        ParserChain().parse_as(raw, ParseHints())


def test_a_media_type_no_parser_takes_is_unsupported() -> None:
    raw = RawDocument.from_bytes(REF, b"plain text", "text/plain")
    assert not ParserChain().supports(raw)
    with pytest.raises(UnsupportedDocumentError, match="no parser for text/plain"):
        ParserChain().parse_as(raw, ParseHints())


def test_a_transcript_is_parsed_instead_of_the_bytes() -> None:
    raw = RawDocument.from_bytes(REF, blank_pdf(), "application/pdf")
    transcript = read_transcript(
        {"blocks": [{"type": "paragraph", "number": "1.", "text": "Example transcribed text."}]}
    )
    parsed = ParserChain().parse_as(
        raw, ParseHints(doc_type=DocumentType.STATUTE, transcript=transcript)
    )
    assert (parsed.parser_version, parsed.doc_type) == ("manual@1", DocumentType.STATUTE)
    assert parsed.document_id == document_id_for(raw.sha256)
    assert [c.text for c in parsed.clauses] == ["1. Example transcribed text."]


def test_the_type_comes_from_the_hints_else_the_source() -> None:
    chain = ParserChain(RegistryCatalog(PoliteClient()))
    pdf = recorded_pdf("gst-ct-01-2026.pdf.json")
    circular = DocumentRef(source_id_for("cbic_circulars"), "https://example.test/c.pdf")
    raw = RawDocument.from_bytes(circular, pdf.content, "application/pdf")
    assert chain.parse_as(raw, ParseHints()).doc_type is DocumentType.CIRCULAR
    statute = chain.parse_as(raw, ParseHints(doc_type=DocumentType.STATUTE))
    assert statute.doc_type is DocumentType.STATUTE
    assert ParserChain().parse(raw).doc_type is DocumentType.NOTIFICATION


class Fixed:
    """A parser of every media type that gives way when told to, or fails."""

    def __init__(self, version: str, *, give_way: bool = False, fails: bool = False) -> None:
        self.version, self.give_way, self.fails = version, give_way, fails

    def supports(self, doc: RawDocument) -> bool:
        return True

    def parse(self, doc: RawDocument) -> ParsedDocument:
        if self.give_way:
            raise DeclinedDocumentError("another parser reads it better")
        if self.fails:
            raise UnparsedDocumentError("cannot read it")
        return ParsedDocument(
            document_id=document_id_for(doc.sha256),
            doc_type=DocumentType.NOTIFICATION,
            title="Example",
            clauses=(Clause("en.p1", f"read by {self.version}"),),
            parser_version=self.version,
        )


def link(version: str, **kwargs: bool) -> ChainLink:
    build: Callable[[DocumentType, bool], DocumentParser] = lambda _, give_way: Fixed(  # noqa: E731
        version,
        give_way=give_way and kwargs.get("gives_way", False),
        fails=kwargs.get("fails", False),
    )
    return ChainLink(version, build)


def test_a_parser_that_gave_way_parses_when_no_later_one_can() -> None:
    raw = RawDocument.from_bytes(REF, b"bytes", "application/octet-stream")
    chain = ParserChain(links=[link("first@1", gives_way=True), link("second@1", fails=True)])
    assert chain.parse_as(raw, ParseHints()).parser_version == "first@1"
    better = ParserChain(links=[link("first@1", gives_way=True), link("second@1")])
    assert better.parse_as(raw, ParseHints()).parser_version == "second@1"
    sticky = better.parse_as(raw, ParseHints(parser_version="first@1"))
    assert sticky.parser_version == "first@1", "the recorded parser never gives way"
    unknown = better.parse_as(raw, ParseHints(parser_version="gone@3"))
    assert unknown.parser_version == "second@1", "a version the chain lacks is passed over"


def test_wrapped_aligned_and_single_rows_on_the_layout_grid() -> None:
    page = "\n".join(
        [
            "Example heading of the page",
            "",
            "1.      Example one      Example text of the first entry that wraps",
            "                         onto a second line under its own column",
            "",
            "2.      Example two      Example text of the second entry",
            "",
            "S. No.   Item            Rate",
            "1        Example item    5%",
            "2        Another item    12%",
            "",
            "(a)   Example list item whose text",
            "          wraps under itself, which is no table",
        ]
    )
    (segments,) = find_rows([page])
    blocks = page_blocks(segments, 1)
    assert blocks == [
        Paragraph("Example heading of the page", page=1),
        Table(
            rows=(
                (
                    "1.",
                    "Example one",
                    "Example text of the first entry that wraps onto a second line under its own "
                    "column",
                ),
            ),
            page=1,
        ),
        Table(rows=(("2.", "Example two", "Example text of the second entry"),), page=1),
        Table(
            rows=(
                ("S. No.", "Item", "Rate"),
                ("1", "Example item", "5%"),
                ("2", "Another item", "12%"),
            ),
            page=1,
        ),
        Paragraph("(a) Example list item whose text wraps under itself, which is no table", page=1),
    ]


def test_the_grid_cleanup() -> None:
    assert clean("the 13           th   March,  2025") == "the 13th March, 2025"
    assert clean('"53  .   Jodhpur') == '"53. Jodhpur'
    assert clean("namely: -") == "namely: -"
