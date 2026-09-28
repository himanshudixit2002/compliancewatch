"""HTML into clauses: the visible text of paragraphs, list items, headings and table cells."""

from html.parser import HTMLParser

from domain_kernel.documents import (
    Clause,
    DocumentType,
    ParsedDocument,
    RawDocument,
    document_id_for,
)
from pipeline.infrastructure.parsers.text import LANGUAGE_BILINGUAL, renumber, split_clauses

PARSER_VERSION = "html@1"
"""Bump when a change can alter the clause text or refs this parser gives for the same bytes."""

_BLOCKS = {"title", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "div", "br", "tr"}
_SKIP = {"script", "style"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
        if tag in _BLOCKS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        if tag in _BLOCKS:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return "".join(extractor.parts)


class HtmlParser:
    def __init__(self, *, doc_type: DocumentType = DocumentType.PRESS_RELEASE) -> None:
        self._doc_type = doc_type

    def supports(self, doc: RawDocument) -> bool:
        return doc.media_type.split(";")[0].strip() in {"text/html", "application/xhtml+xml"}

    def parse(self, doc: RawDocument) -> ParsedDocument:
        text = html_to_text(doc.content.decode("utf-8", errors="replace"))
        clauses = renumber(split_clauses(text))
        if not clauses:
            clauses = renumber(split_clauses(doc.ref.url))
        languages = {clause.language for clause in clauses}
        return ParsedDocument(
            document_id=document_id_for(doc.sha256),
            doc_type=self._doc_type,
            title=clauses[0].text[:200],
            clauses=tuple(
                Clause(clause_ref=clause.ref, text=clause.text, page=None) for clause in clauses
            ),
            language=languages.pop() if len(languages) == 1 else LANGUAGE_BILINGUAL,
            parser_version=PARSER_VERSION,
        )
