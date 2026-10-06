"""An analyst's transcript of a document no parser could read, parsed as ``manual@1``.

A transcript is the document's structure typed by hand, in the shape the table-aware parsers read
documents into (``domain.structure``): headings, paragraphs with their numbering, and tables with
their rows and cells, in document order. Its clauses come from those blocks exactly as a parser's
do (``clauses_of``), so a transcribed document reads like a parsed one. As JSON::

    {
        "title": "Example notification",
        "blocks": [
            {"type": "heading", "text": "Example heading", "page": 1},
            {"type": "paragraph", "number": "1.", "text": "Example text of the first paragraph."},
            {"type": "table", "header": ["S. No.", "Item"], "rows": [["1", "Example item"]]},
        ],
    }

``title`` is optional, ``page`` is a page number from 1 and optional, ``number`` and ``header``
are optional; nothing else is accepted. ``read_transcript`` checks the shape and that the clauses
fit what the rulebook takes, and names every problem by its place (``blocks[2].rows[0]``).
A transcript is stored in the raw store as its canonical JSON (``encoded``), under the digest of
those bytes, and resolving the document's manual-parse task names it; from then on the document
is parsed from it.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from domain_kernel.documents import Clause, DocumentType, ParsedDocument
from domain_kernel.ids import DocumentId
from pipeline.domain.errors import TranscriptInvalidError
from pipeline.domain.language import LANGUAGE_BILINGUAL
from pipeline.domain.structure import (
    MAX_CLAUSES,
    Block,
    Heading,
    Paragraph,
    Table,
    clauses_of,
    limit_problems,
)

TRANSCRIPT_PARSER: Final = "manual@1"
"""The parser version of a transcribed document's clauses."""
TRANSCRIPT_MEDIA_TYPE: Final = "application/vnd.compliancewatch.transcript+json"
"""The media type a transcript is kept under in the raw store."""
MAX_BLOCKS: Final = MAX_CLAUSES
MAX_CELLS: Final = 50
MAX_NUMBER_CHARS: Final = 20
MAX_TITLE_CHARS: Final = 500
MAX_PROBLEMS: Final = 20
"""How many problems one refusal names; the rest are counted."""

_KEYS: Final[Mapping[str, frozenset[str]]] = {
    "heading": frozenset({"type", "text", "page"}),
    "paragraph": frozenset({"type", "text", "number", "page"}),
    "table": frozenset({"type", "header", "rows", "page"}),
}


@dataclass(frozen=True, slots=True)
class Transcript:
    """The blocks in document order, and the title the analyst gave, if any."""

    blocks: tuple[Block, ...]
    title: str = ""

    def clauses(self) -> tuple[Clause, ...]:
        return clauses_of(self.blocks)

    def as_json(self) -> dict[str, Any]:
        """The transcript in its JSON shape, with only the keys that carry something."""
        blocks: list[dict[str, Any]] = []
        for block in self.blocks:
            item: dict[str, Any]
            if isinstance(block, Heading):
                item = {"type": "heading", "text": block.text}
            elif isinstance(block, Paragraph):
                item = {"type": "paragraph", "text": block.text}
                if block.number:
                    item["number"] = block.number
            else:
                item = {"type": "table", "rows": [list(row) for row in block.rows]}
                if block.header:
                    item["header"] = list(block.header)
            if block.page is not None:
                item["page"] = block.page
            blocks.append(item)
        shape: dict[str, Any] = {"blocks": blocks}
        if self.title:
            shape["title"] = self.title
        return shape

    def encoded(self) -> bytes:
        """The canonical JSON bytes the raw store keeps: sorted keys, no spaces, UTF-8."""
        return json.dumps(
            self.as_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")


def _refuse(problems: Sequence[str]) -> TranscriptInvalidError:
    shown = list(problems[:MAX_PROBLEMS])
    if len(problems) > MAX_PROBLEMS:
        shown.append(f"and {len(problems) - MAX_PROBLEMS} more")
    return TranscriptInvalidError("the transcript is not valid: " + "; ".join(shown))


def _text(value: object, where: str, problems: list[str], *, required: bool = True) -> str:
    if not isinstance(value, str):
        problems.append(f"{where} must be text")
        return ""
    if required and not value.strip():
        problems.append(f"{where} must not be empty")
    return value


def _page(item: Mapping[str, Any], where: str, problems: list[str]) -> int | None:
    page = item.get("page")
    if page is None:
        return None
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        problems.append(f"{where}.page must be a page number from 1")
        return None
    return page


def _cells(value: object, where: str, problems: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        problems.append(f"{where} must be a list of at least one cell")
        return ()
    if len(value) > MAX_CELLS:
        problems.append(f"{where} has {len(value)} cells; at most {MAX_CELLS}")
    cells = tuple(
        _text(cell, f"{where}[{i}]", problems, required=False) for i, cell in enumerate(value)
    )
    if not any(cell.strip() for cell in cells):
        problems.append(f"{where} has no text in any cell")
    return cells


def _block(item: object, where: str, problems: list[str]) -> Block | None:
    if not isinstance(item, Mapping):
        problems.append(f"{where} must be an object")
        return None
    kind = item.get("type")
    if not isinstance(kind, str) or kind not in _KEYS:
        problems.append(f"{where}.type must be heading, paragraph or table")
        return None
    unknown = sorted(set(item) - _KEYS[kind])
    if unknown:
        problems.append(f"{where} has keys a {kind} does not take: {', '.join(unknown)}")
    page = _page(item, where, problems)
    if kind == "heading":
        return Heading(_text(item.get("text"), f"{where}.text", problems), page=page)
    if kind == "paragraph":
        number = _text(item.get("number", ""), f"{where}.number", problems, required=False)
        if len(number) > MAX_NUMBER_CHARS:
            problems.append(f"{where}.number must be at most {MAX_NUMBER_CHARS} characters")
        text = _text(item.get("text"), f"{where}.text", problems)
        return Paragraph(text, number=number.strip(), page=page)
    rows = item.get("rows")
    if not isinstance(rows, list) or not rows:
        problems.append(f"{where}.rows must be a list of at least one row")
        rows = []
    header = item.get("header")
    return Table(
        rows=tuple(_cells(row, f"{where}.rows[{i}]", problems) for i, row in enumerate(rows)),
        header=() if header is None else _cells(header, f"{where}.header", problems),
        page=page,
    )


def read_transcript(data: object) -> Transcript:
    """The transcript in ``data`` (parsed JSON), checked; ``TranscriptInvalidError`` names every
    problem."""
    problems: list[str] = []
    if not isinstance(data, Mapping):
        raise _refuse(["a transcript is an object with blocks"])
    unknown = sorted(set(data) - {"title", "blocks"})
    if unknown:
        problems.append(f"the transcript has keys it does not take: {', '.join(unknown)}")
    title = _text(data.get("title", ""), "title", problems, required=False).strip()
    if len(title) > MAX_TITLE_CHARS:
        problems.append(f"title must be at most {MAX_TITLE_CHARS} characters")
    items = data.get("blocks")
    if not isinstance(items, list) or not items:
        problems.append("blocks must be a list of at least one block")
        items = []
    if len(items) > MAX_BLOCKS:
        problems.append(f"{len(items)} blocks; at most {MAX_BLOCKS}")
        items = items[:MAX_BLOCKS]
    blocks = [_block(item, f"blocks[{i}]", problems) for i, item in enumerate(items)]
    if problems:
        raise _refuse(problems)
    transcript = Transcript(tuple(block for block in blocks if block is not None), title=title)
    clauses = transcript.clauses()
    if not clauses:
        raise _refuse(["the blocks hold no text"])
    limits = limit_problems(clauses)
    if limits:
        raise _refuse(limits)
    return transcript


def decode_transcript(content: bytes) -> Transcript:
    """A transcript from the JSON bytes the raw store keeps (``Transcript.encoded``)."""
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranscriptInvalidError(f"the transcript is not JSON: {exc}") from exc
    return read_transcript(data)


def transcribed(
    transcript: Transcript,
    *,
    document_id: DocumentId,
    doc_type: DocumentType,
    title: str = "",
    published_at: date | None = None,
) -> ParsedDocument:
    """The document as the transcript gives it: its clauses, parsed by ``manual@1``."""
    clauses = transcript.clauses()
    if not clauses:
        raise TranscriptInvalidError("the transcript holds no text")
    languages = {clause.clause_ref.partition(".")[0] for clause in clauses}
    return ParsedDocument(
        document_id=document_id,
        doc_type=doc_type,
        title=(title or transcript.title or clauses[0].text)[:200],
        clauses=clauses,
        published_at=published_at,
        language=languages.pop() if len(languages) == 1 else LANGUAGE_BILINGUAL,
        parser_version=TRANSCRIPT_PARSER,
    )
