"""PDF tables kept as rows: the table-aware PDF parser, ``pdf-tables@1``.

The text-layer parser (``pdf@1``) reads a PDF's text in the order the page draws it, so a table
comes out as its cells one after another and a wrapped cell is split from the rest of its row.
This parser reads each page in pypdf's layout mode, which puts the text on a grid of characters
where it stands on the page, and finds the rows in it. A cell is a run of text; two cells on a
line are at least ``GAP`` spaces apart. A row has at least ``MIN_CELLS`` cells:

- a **wrapped row** is a line of cells followed by lines that hang at least ``HANG`` characters
  right of it and continue its cells. The line's last cell starts within ``TOLERANCE`` of where
  the hanging lines start, and every hanging piece of text goes to the cell it stands under (the
  numbered entries of a jurisdiction table, a description that runs over several lines);
- **aligned rows** are two or more consecutive lines whose cells start at the same columns, give
  or take ``ALIGN`` characters;
- a **single row** is a line whose cells start where the cells of a row found in the document
  start, within ``TOLERANCE``;
- the lines right after a row that all start under its last cell continue that cell (an entry of
  two paragraphs).

Everything else is text, split into paragraphs as the text-layer parser splits it. Rows become
``domain.structure`` table rows: one clause each, its cells joined by `` | ``. The grid adds
spaces the text does not have, so each run of white space is made one space, an ordinal printed
as a superscript is joined to its number again (``13 th`` reads ``13th``), and a full stop, comma,
colon or semicolon standing alone is joined to the word before it.

``has_tables`` answers whether a PDF has a wrapped or aligned row: the text-layer parser gives
way to this one on such a PDF (``ParserChain``).
"""

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from pypdf import PageObject, PdfReader

from domain_kernel.documents import DocumentType, ParsedDocument, RawDocument, document_id_for
from pipeline.domain.errors import UnparsedDocumentError
from pipeline.domain.language import LANGUAGE_BILINGUAL, detect_language
from pipeline.domain.structure import Block, Paragraph, Table, clauses_of, normalise
from pipeline.infrastructure.parsers.text import split_clauses
from py_common.logging import get_logger

PARSER_VERSION: Final = "pdf-tables@1"
"""Bump when a change can alter the clause text or refs this parser gives for the same bytes."""
GAP: Final = 3
"""Spaces that part two cells on a line of the layout grid."""
HANG: Final = 8
"""How far right of a row's first line its wrapped lines start."""
TOLERANCE: Final = 8
"""How far a cell may start from its column: the grid places a long line's words a few
characters off where the lines below it place theirs."""
ALIGN: Final = 2
"""How far apart the cells of aligned rows may start."""
MIN_CELLS: Final = 3

log = get_logger(__name__)

_RUN = re.compile(rf"\S+(?: {{1,{GAP - 1}}}\S+)*")
_MARKS = re.compile(r"[.,;:]+")
_ORDINAL = re.compile(r"(\d)\s+(st|nd|rd|th)\b")
_LONE_MARK = re.compile(r"\s+([.,;:])(?=\s|$)")


@dataclass(frozen=True, slots=True)
class Run:
    start: int
    text: str


@dataclass
class Row:
    """A row found on the grid: where its cells start, and their text."""

    columns: list[int]
    cells: list[list[str]]

    def texts(self) -> tuple[str, ...]:
        return tuple(clean(" ".join(parts)) for parts in self.cells)


@dataclass
class Segment:
    """Consecutive lines of a page with no blank line between them, and the rows found in
    them (empty when they are text)."""

    lines: list[str]
    rows: list[Row] = field(default_factory=list)


def clean(text: str) -> str:
    """Text off the grid: one space for each run of white space, a superscript ordinal joined
    to its number, a lone punctuation mark joined to the word before it."""
    return _LONE_MARK.sub(r"\1", _ORDINAL.sub(r"\1\2", normalise(text)))


def runs_of(line: str) -> list[Run]:
    """The line's cells; a run that is only punctuation belongs to the one before it (the grid
    can set the full stop of ``102.`` apart)."""
    runs: list[Run] = []
    for match in _RUN.finditer(line):
        if runs and _MARKS.fullmatch(match.group()):
            runs[-1] = Run(runs[-1].start, runs[-1].text + match.group())
        else:
            runs.append(Run(match.start(), match.group()))
    return runs


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def segments_of(text: str) -> list[Segment]:
    segments: list[Segment] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip():
            current.append(line.rstrip())
        elif current:
            segments.append(Segment(current))
            current = []
    if current:
        segments.append(Segment(current))
    return segments


def _row(head: list[Run], hanging: Sequence[str], start: int) -> Row | None:
    """The row whose first line has the cells ``head`` and whose wrapped lines, starting at
    ``start``, are ``hanging``; None when fewer than ``MIN_CELLS`` cells come before it."""
    last = next((i for i, run in enumerate(head) if run.start >= start - TOLERANCE), None)
    if last is None or last < MIN_CELLS - 1:
        return None
    row = Row(
        columns=[run.start for run in head[: last + 1]],
        cells=[[run.text] for run in head[:last]] + [[" ".join(r.text for r in head[last:])]],
    )
    for line in hanging:
        for run in runs_of(line):
            column = max(
                (i for i, at in enumerate(row.columns) if at <= run.start + TOLERANCE), default=0
            )
            row.cells[column].append(run.text)
    return row


def wrapped_rows(lines: Sequence[str]) -> list[Row]:
    """The rows of lines whose first line has wrapped lines hanging under it; none when the
    lines are not such rows, every one of them."""
    first = indent(lines[0])
    hanging = [indent(line) for line in lines[1:] if indent(line) >= first + HANG]
    if not hanging:
        return []
    # Where most wrapped lines start: the last column. A wrapped middle cell (a name over two
    # lines) starts left of it.
    start = max(set(hanging), key=lambda at: (hanging.count(at), at))
    groups: list[list[str]] = []
    for line in lines:
        if indent(line) < first + HANG:
            groups.append([line])
        else:
            groups[-1].append(line)
    rows = [_row(runs_of(group[0]), group[1:], start) for group in groups]
    return [row for row in rows if row is not None] if all(rows) else []


def _aligned(a: Sequence[Run], b: Sequence[Run]) -> bool:
    return len(a) == len(b) and all(
        abs(x.start - y.start) <= ALIGN for x, y in zip(a, b, strict=True)
    )


def aligned_rows(lines: Sequence[str]) -> list[Row]:
    """The rows of lines that are all cells under the same columns; none when they are not."""
    found = [runs_of(line) for line in lines]
    if len(found) < 2 or any(len(runs) < MIN_CELLS for runs in found):
        return []
    if not all(_aligned(found[0], runs) for runs in found[1:]):
        return []
    return [Row([run.start for run in runs], [[run.text] for run in runs]) for runs in found]


def _matches(runs: Sequence[Run], columns: Sequence[int]) -> bool:
    return len(runs) == len(columns) and all(
        abs(run.start - at) <= TOLERANCE for run, at in zip(runs, columns, strict=True)
    )


def find_rows(pages: Sequence[str]) -> list[list[Segment]]:
    """Each page's segments with the rows found in them, the single rows found by the columns
    of the others."""
    found = [segments_of(text) for text in pages]
    for segments in found:
        for segment in segments:
            segment.rows = wrapped_rows(segment.lines) or aligned_rows(segment.lines)
    models = [row.columns for segments in found for segment in segments for row in segment.rows]
    for segments in found:
        for segment in segments:
            if segment.rows or len(segment.lines) != 1:
                continue
            runs = runs_of(segment.lines[0])
            if len(runs) >= MIN_CELLS and any(_matches(runs, columns) for columns in models):
                segment.rows = [Row([run.start for run in runs], [[run.text] for run in runs])]
    return found


def _continues(segment: Segment, row: Row) -> bool:
    last = row.columns[-1]
    return all(abs(indent(line) - last) <= TOLERANCE for line in segment.lines)


def _paragraphs(lines: Sequence[str], page: int) -> list[Block]:
    text = "\n".join(clean(line) for line in lines)
    return [Paragraph(clause.text, page=page) for clause in split_clauses(text, page=page)]


def page_blocks(segments: Sequence[Segment], page: int) -> list[Block]:
    """A page's segments as blocks: rows as tables, the rest as paragraphs."""
    blocks: list[Block] = []
    previous: Row | None = None
    for segment in segments:
        if segment.rows:
            blocks.append(Table(rows=tuple(row.texts() for row in segment.rows), page=page))
            previous = segment.rows[-1]
            continue
        if previous is not None and _continues(segment, previous):
            previous.cells[-1].extend(segment.lines)
            last = blocks[-1]
            assert isinstance(last, Table)
            blocks[-1] = Table(rows=(*last.rows[:-1], previous.texts()), page=page)
            continue
        blocks.extend(_paragraphs(segment.lines, page))
        previous = None
    return blocks


def layout_text(page: PageObject) -> str:
    """The page on the layout grid; empty for a page that has no content or that pypdf's layout
    mode cannot lay out (the text-layer parser still reads it)."""
    if "/Contents" not in page:
        return ""
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except Exception as exc:
        log.warning("pdf_tables.layout_failed", error=f"{type(exc).__name__}: {exc}")
        return ""


def layout_pages(reader: PdfReader) -> list[str]:
    return [layout_text(page) for page in reader.pages]


def has_tables(reader: PdfReader) -> bool:
    """Whether a page has a wrapped or aligned row."""
    return any(
        wrapped_rows(segment.lines) or aligned_rows(segment.lines)
        for text in layout_pages(reader)
        for segment in segments_of(text)
    )


class PdfTableParser:
    def __init__(self, *, doc_type: DocumentType = DocumentType.NOTIFICATION) -> None:
        self._doc_type = doc_type

    def supports(self, doc: RawDocument) -> bool:
        return doc.media_type.split(";")[0].strip() == "application/pdf" or doc.content.startswith(
            b"%PDF-"
        )

    def parse(self, doc: RawDocument) -> ParsedDocument:
        reader = PdfReader(io.BytesIO(doc.content))
        pages = layout_pages(reader)
        blocks = [
            block
            for number, segments in enumerate(find_rows(pages), 1)
            for block in page_blocks(segments, number)
        ]
        clauses = clauses_of(blocks)
        if not clauses:
            raise UnparsedDocumentError("the PDF has no text layer")
        languages = {clause.clause_ref.partition(".")[0] for clause in clauses}
        language = languages.pop() if len(languages) == 1 else LANGUAGE_BILINGUAL
        title = next((c.text for c in clauses if len(c.text) > 12), clauses[0].text)[:200]
        return ParsedDocument(
            document_id=document_id_for(doc.sha256),
            doc_type=self._doc_type,
            title=title,
            clauses=clauses,
            language=language
            if language != LANGUAGE_BILINGUAL
            else detect_language("\n".join(pages)),
            parser_version=PARSER_VERSION,
        )
