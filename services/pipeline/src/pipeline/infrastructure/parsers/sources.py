"""Parsers by source: the parsers of a document type, and a parser over every source of a
catalog that parses each document as its source's document type."""

from domain_kernel.documents import DocumentType, ParsedDocument, RawDocument
from domain_kernel.protocols import DocumentParser
from pipeline.domain.ports import SourceCatalog
from pipeline.infrastructure.parsers.html import HtmlParser
from pipeline.infrastructure.parsers.pdf import PdfParser


def parsers_for(doc_type: DocumentType) -> list[DocumentParser]:
    """The PDF parser, then the HTML one, both giving ``doc_type``."""
    return [PdfParser(doc_type=doc_type), HtmlParser(doc_type=doc_type)]


class SourceParsers:
    """A ``DocumentParser`` for documents of any source in ``sources``: the first of
    ``parsers_for`` the source's document type that supports the bytes parses them."""

    def __init__(self, sources: SourceCatalog) -> None:
        self._sources = sources

    def supports(self, doc: RawDocument) -> bool:
        return self._parser(doc) is not None

    def parse(self, doc: RawDocument) -> ParsedDocument:
        parser = self._parser(doc)
        if parser is None:
            raise ValueError(f"no parser for {doc.media_type}")
        return parser.parse(doc)

    def _parser(self, doc: RawDocument) -> DocumentParser | None:
        doc_type = self._sources.resolve(doc.ref.source_id).definition.doc_type
        return next((p for p in parsers_for(doc_type) if p.supports(doc)), None)
