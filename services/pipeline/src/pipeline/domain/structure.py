"""A document's structure as the table-aware parsers read it and an analyst transcribes it:
headings, paragraphs (with their number when they have one) and tables, in document order; and
the clauses they become.

Every block becomes clauses the same way, whichever parser read it (``clauses_of``):

- a heading is one clause, its text;
- a paragraph is one clause, its number and then its text (``(1) Every registered person ...``);
- a table is one clause per row, its header row first when it has one. A row's cells stay
  together and in order, joined by `` | `` (``CELL_SEPARATOR``): ``1 | Rule 61 | GSTR-3B``; an
  empty cell keeps its place (``1 |  | 5%``) unless it ends the row.

Text is kept as read, each run of white space made one space. A clause's reference is
``<language>.p<n>``, counted per language in document order the way the text-layer parsers count
theirs, so the rulebook stores it as it is and the same blocks always give the same refs, and so
the same clause ids. The rulebook takes at most ``MAX_CLAUSES`` clauses of a document, each of
at most ``MAX_CLAUSE_CHARS`` characters, and refs up to ``p9999`` per language
(``MAX_PER_LANGUAGE``); ``limit_problems`` names what passes those limits.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from domain_kernel._validation import require_instance
from domain_kernel.documents import Clause
from domain_kernel.errors import InvariantViolationError
from pipeline.domain.language import detect_language

CELL_SEPARATOR: Final = " | "
MAX_CLAUSES: Final = 2_000
MAX_CLAUSE_CHARS: Final = 50_000
MAX_PER_LANGUAGE: Final = 9_999


def normalise(text: str) -> str:
    """The text with each run of white space made one space, and none at either end."""
    return " ".join(text.split())


def _require_page(page: object) -> None:
    if page is not None and (not isinstance(page, int) or isinstance(page, bool) or page < 1):
        raise InvariantViolationError(f"page must be a number from 1, got {page!r}")


@dataclass(frozen=True, slots=True)
class Heading:
    text: str
    page: int | None = None

    def __post_init__(self) -> None:
        require_instance(self.text, str, "text")
        _require_page(self.page)


@dataclass(frozen=True, slots=True)
class Paragraph:
    """``number`` is the paragraph's own numbering as printed (``1.``, ``(2)``, ``(a)``)."""

    text: str
    number: str = ""
    page: int | None = None

    def __post_init__(self) -> None:
        require_instance(self.text, str, "text")
        require_instance(self.number, str, "number")
        _require_page(self.page)


@dataclass(frozen=True, slots=True)
class Table:
    """Rows of cells in order; ``header`` is the header row, when the table has one."""

    rows: tuple[tuple[str, ...], ...]
    header: tuple[str, ...] = ()
    page: int | None = None

    def __post_init__(self) -> None:
        for index, row in enumerate(require_instance(self.rows, tuple, "rows")):
            for cell in require_instance(row, tuple, f"rows[{index}]"):
                require_instance(cell, str, f"rows[{index}] cell")
        for cell in require_instance(self.header, tuple, "header"):
            require_instance(cell, str, "header cell")
        _require_page(self.page)


type Block = Heading | Paragraph | Table


def row_text(cells: Sequence[str]) -> str:
    """A row as one clause's text: its cells in order, joined by ``CELL_SEPARATOR``. An empty
    cell keeps its place between others; empty cells at the end are dropped, and a row of
    empty cells is empty."""
    normalised = [normalise(cell) for cell in cells]
    while normalised and not normalised[-1]:
        normalised.pop()
    return CELL_SEPARATOR.join(normalised)


def block_texts(block: Block) -> Iterator[str]:
    """The text of each clause the block becomes, in order; an empty one becomes none."""
    if isinstance(block, Heading):
        yield normalise(block.text)
    elif isinstance(block, Paragraph):
        yield normalise(f"{block.number} {block.text}")
    else:
        if block.header:
            yield row_text(block.header)
        for row in block.rows:
            yield row_text(row)


def clauses_of(blocks: Sequence[Block]) -> tuple[Clause, ...]:
    """The blocks as clauses ``<language>.p<n>``, counted per language in document order."""
    counters: dict[str, int] = {}
    clauses: list[Clause] = []
    for block in blocks:
        for text in block_texts(block):
            if not text:
                continue
            language = detect_language(text)
            counters[language] = counters.get(language, 0) + 1
            clauses.append(Clause(f"{language}.p{counters[language]}", text, page=block.page))
    return tuple(clauses)


def limit_problems(clauses: Sequence[Clause]) -> list[str]:
    """What in the clauses passes the rulebook's limits: the count, a clause's length, the refs
    of one language."""
    found: list[str] = []
    if len(clauses) > MAX_CLAUSES:
        found.append(f"{len(clauses)} clauses; the rulebook takes at most {MAX_CLAUSES}")
    for clause in clauses:
        if len(clause.text) > MAX_CLAUSE_CHARS:
            found.append(
                f"{clause.clause_ref} has {len(clause.text)} characters; at most {MAX_CLAUSE_CHARS}"
            )
    languages: dict[str, int] = {}
    for clause in clauses:
        language = clause.clause_ref.partition(".")[0]
        languages[language] = languages.get(language, 0) + 1
    for language, count in sorted(languages.items()):
        if count > MAX_PER_LANGUAGE:
            found.append(f"{count} {language} clauses; at most {MAX_PER_LANGUAGE} per language")
    return found
