"""HTML tables kept as rows: the table-aware HTML parser, ``html-tables@1``.

The HTML parser (``html@1``) makes every table cell a paragraph of its own, so a row's cells end
up in separate clauses. This parser reads a page into ``domain.structure`` blocks instead: a
heading (``h1`` to ``h6``, the page's ``title``) is a heading; the text between block elements
(``p``, ``li``, ``div``, ``br``) is split into paragraphs as the text-layer parsers split text;
and each outermost ``table`` is a table of its ``tr`` rows and their ``td`` and ``th`` cells, its
first row the header when every cell of it is a ``th``. A table inside a cell is that cell's
text, and a table's text outside its cells (a caption) a paragraph before it. Script and style
are skipped.

``has_table`` answers whether a page has a data table: a table with at least two rows of at
least two cells with text. The HTML parser gives way to this one on such a page
(``ParserChain``).
"""

from html.parser import HTMLParser
from typing import Final

from domain_kernel.documents import DocumentType, ParsedDocument, RawDocument, document_id_for
from pipeline.domain.errors import UnparsedDocumentError
from pipeline.domain.language import LANGUAGE_BILINGUAL
from pipeline.domain.structure import Block, Heading, Paragraph, Table, clauses_of, normalise
from pipeline.infrastructure.parsers.text import split_clauses

PARSER_VERSION: Final = "html-tables@1"
"""Bump when a change can alter the clause text or refs this parser gives for the same bytes."""

_HEADINGS: Final = frozenset({"title", "h1", "h2", "h3", "h4", "h5", "h6"})
_BREAKS: Final = frozenset({"p", "li", "div", "br", "tr", "td", "th", "table", *_HEADINGS})
_SKIP: Final = frozenset({"script", "style"})
_CELLS: Final = frozenset({"td", "th"})


class _Structure(HTMLParser):
    """Blocks in document order, from the events of the standard library's parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._text: list[str] = []
        self._heading = False
        self._skip = 0
        self._depth = 0
        self._rows: list[tuple[list[str], bool]] = []
        self._row: list[str] | None = None
        self._row_headed = True
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self._skip += 1
            return
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._flush()
                self._heading = False
                self._rows = []
            return
        if self._depth >= 1:
            self._table_start(tag)
            return
        if tag in _BREAKS:
            self._flush()
            self._heading = tag in _HEADINGS

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(self._skip - 1, 0)
            return
        if tag == "table" and self._depth:
            if self._depth == 1:
                self._end_row()
                self._end_table()
            self._depth -= 1
            return
        if self._depth >= 1:
            if self._depth == 1 and tag in _CELLS:
                self._end_cell()
            elif self._depth == 1 and tag == "tr":
                self._end_row()
            elif self._cell is not None and tag in _BREAKS:
                self._cell.append(" ")
            return
        if tag in _BREAKS:
            self._flush()
            self._heading = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        else:
            # Outside the tables, or a table's text outside its cells (a caption).
            self._text.append(data)

    def close(self) -> None:
        super().close()
        if self._depth:
            self._end_row()
            self._end_table()
            self._depth = 0
        self._flush()

    def _table_start(self, tag: str) -> None:
        if self._depth > 1:
            if self._cell is not None and tag in _BREAKS:
                self._cell.append(" ")
            return
        if tag == "tr":
            self._end_row()
            self._row, self._row_headed = [], True
        elif tag in _CELLS:
            self._end_cell()
            if self._row is None:
                self._row, self._row_headed = [], True
            self._row_headed = self._row_headed and tag == "th"
            self._cell = []
        elif self._cell is not None and tag in _BREAKS:
            self._cell.append(" ")

    def _end_cell(self) -> None:
        if self._cell is not None and self._row is not None:
            self._row.append(normalise("".join(self._cell)))
        self._cell = None

    def _end_row(self) -> None:
        self._end_cell()
        if self._row is not None and any(self._row):
            self._rows.append((self._row, self._row_headed))
        self._row = None

    def _end_table(self) -> None:
        self._flush()
        rows = self._rows
        self._rows = []
        if not rows:
            return
        header: tuple[str, ...] = ()
        if rows[0][1] and len(rows) > 1:
            header = tuple(rows[0][0])
            rows = rows[1:]
        self.blocks.append(Table(rows=tuple(tuple(cells) for cells, _ in rows), header=header))

    def _flush(self) -> None:
        text = "".join(self._text)
        self._text = []
        if not text.strip():
            return
        if self._heading:
            self.blocks.append(Heading(normalise(text)))
            return
        self.blocks.extend(Paragraph(clause.text) for clause in split_clauses(text))


def html_blocks(html: str) -> list[Block]:
    structure = _Structure()
    structure.feed(html)
    structure.close()
    return structure.blocks


def has_table(html: str) -> bool:
    """Whether the page has a table of at least two rows of at least two cells with text."""
    for block in html_blocks(html):
        if isinstance(block, Table):
            rows = [block.header, *block.rows] if block.header else list(block.rows)
            if sum(1 for row in rows if sum(1 for cell in row if cell) >= 2) >= 2:
                return True
    return False


class HtmlTableParser:
    def __init__(self, *, doc_type: DocumentType = DocumentType.PRESS_RELEASE) -> None:
        self._doc_type = doc_type

    def supports(self, doc: RawDocument) -> bool:
        return doc.media_type.split(";")[0].strip() in {"text/html", "application/xhtml+xml"}

    def parse(self, doc: RawDocument) -> ParsedDocument:
        clauses = clauses_of(html_blocks(doc.content.decode("utf-8", errors="replace")))
        if not clauses:
            raise UnparsedDocumentError("the page has no text")
        languages = {clause.clause_ref.partition(".")[0] for clause in clauses}
        return ParsedDocument(
            document_id=document_id_for(doc.sha256),
            doc_type=self._doc_type,
            title=clauses[0].text[:200],
            clauses=clauses,
            language=languages.pop() if len(languages) == 1 else LANGUAGE_BILINGUAL,
            parser_version=PARSER_VERSION,
        )
