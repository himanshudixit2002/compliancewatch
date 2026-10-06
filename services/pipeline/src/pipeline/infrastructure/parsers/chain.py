"""The parser chain: how every document is parsed, chosen by its media type.

A document is parsed by the first parser of ``CHAIN`` that takes its media type and reads it:

1. ``pdf@1`` (``PdfParser``): the PDF's text layer. It gives way to the next on a PDF with tables
   (``pdf_tables.has_tables``);
2. ``pdf-tables@1`` (``PdfTableParser``): the same text with its table rows kept together;
3. ``html@1`` (``HtmlParser``): the page's text. It gives way to the next on a page with a data
   table (``html_tables.has_table``);
4. ``html-tables@1`` (``HtmlTableParser``): the page with its table rows kept together.

A parser that gave way is asked again, to parse as it always did, when no later one reads the
document. A parser that fails on the bytes (a scan with no text layer, a file it cannot open)
leaves them to the next; when none reads them the chain raises ``UnparsedDocumentError`` with each
parser's reason, and when none takes the media type, ``UnsupportedDocumentError``.

The hints (``ParseHints``) come from the document's record: ``parser_version`` names the parser
that parsed it before, which the chain puts first and which then never gives way, so a stored
document keeps its clauses and their ids while the code has that parser (a version the chain no
longer has is passed over); ``doc_type`` is what to parse it as, else its source's type; and a
``transcript`` is parsed instead of the bytes, as ``manual@1``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from domain_kernel.documents import DocumentType, ParsedDocument, RawDocument, document_id_for
from domain_kernel.protocols import DocumentParser
from pipeline.domain.errors import UnparsedDocumentError, UnsupportedDocumentError
from pipeline.domain.ports import ParseHints, SourceCatalog
from pipeline.domain.transcripts import transcribed
from pipeline.infrastructure.parsers import html, html_tables, pdf, pdf_tables
from pipeline.infrastructure.parsers.errors import DeclinedDocumentError
from pipeline.infrastructure.parsers.html import HtmlParser
from pipeline.infrastructure.parsers.html_tables import HtmlTableParser
from pipeline.infrastructure.parsers.pdf import PdfParser
from pipeline.infrastructure.parsers.pdf_tables import PdfTableParser

MAX_REASON_CHARS: Final = 300


@dataclass(frozen=True, slots=True)
class ChainLink:
    """One parser of the chain: its version, and how to build it for a document type, giving
    way or not."""

    version: str
    build: Callable[[DocumentType, bool], DocumentParser]


CHAIN: Final[tuple[ChainLink, ...]] = (
    ChainLink(
        pdf.PARSER_VERSION, lambda t, give_way: PdfParser(doc_type=t, give_way_to_tables=give_way)
    ),
    ChainLink(pdf_tables.PARSER_VERSION, lambda t, _: PdfTableParser(doc_type=t)),
    ChainLink(
        html.PARSER_VERSION, lambda t, give_way: HtmlParser(doc_type=t, give_way_to_tables=give_way)
    ),
    ChainLink(html_tables.PARSER_VERSION, lambda t, _: HtmlTableParser(doc_type=t)),
)


def _reason(version: str, error: Exception) -> str:
    return f"{version}: {type(error).__name__}: {error}"[:MAX_REASON_CHARS]


class ParserChain:
    """The pipeline's ``DocumentParsers`` over ``links``. A document whose hints name no type is
    parsed as its source's (``sources``), or as ``default_type`` without a catalog. It is the
    kernel's ``DocumentParser`` too: ``parse`` is ``parse_as`` with no hints."""

    def __init__(
        self,
        sources: SourceCatalog | None = None,
        *,
        links: Sequence[ChainLink] = CHAIN,
        default_type: DocumentType = DocumentType.NOTIFICATION,
    ) -> None:
        self._sources = sources
        self._links = tuple(links)
        self._default_type = default_type

    @property
    def versions(self) -> tuple[str, ...]:
        return tuple(link.version for link in self._links)

    def supports(self, doc: RawDocument) -> bool:
        return any(link.build(self._default_type, False).supports(doc) for link in self._links)

    def parse(self, doc: RawDocument) -> ParsedDocument:
        return self.parse_as(doc, ParseHints())

    def parse_as(self, raw: RawDocument, hints: ParseHints) -> ParsedDocument:
        doc_type = hints.doc_type or self._type_of(raw)
        if hints.transcript is not None:
            return transcribed(
                hints.transcript, document_id=document_id_for(raw.sha256), doc_type=doc_type
            )
        first = [link for link in self._links if link.version == hints.parser_version]
        ordered = [*first, *(link for link in self._links if link not in first)]
        reasons: list[str] = []
        declined: list[ChainLink] = []
        taken = False
        for link in ordered:
            parser = link.build(doc_type, link not in first)
            if not parser.supports(raw):
                continue
            taken = True
            try:
                return parser.parse(raw)
            except DeclinedDocumentError as exc:
                declined.append(link)
                reasons.append(_reason(link.version, exc))
            except Exception as exc:
                reasons.append(_reason(link.version, exc))
        for link in declined:
            try:
                return link.build(doc_type, False).parse(raw)
            except Exception as exc:
                reasons.append(_reason(link.version, exc))
        if not taken:
            raise UnsupportedDocumentError(f"no parser for {raw.media_type}")
        raise UnparsedDocumentError("; ".join(reasons))

    def _type_of(self, raw: RawDocument) -> DocumentType:
        if self._sources is None:
            return self._default_type
        return self._sources.resolve(raw.ref.source_id).definition.doc_type
