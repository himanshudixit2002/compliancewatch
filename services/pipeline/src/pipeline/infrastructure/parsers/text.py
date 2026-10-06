"""Text into clauses, and which language a text is in.

Regulator documents are English, Hindi or both (a Hindi gazette text followed by the English
one; ``pipeline.domain.language``). Clauses are the paragraphs of the text; a numbered paragraph
(``1.``, ``(2)``, ``(a)``) starts a new clause even without a blank line before it. The
reference is ``<lang>.p<n>`` so an English and a Hindi rendering of the same document never
collide.
"""

import re
from dataclasses import dataclass

from pipeline.domain.language import (
    LANGUAGE_BILINGUAL,
    LANGUAGE_ENGLISH,
    LANGUAGE_HINDI,
    detect_language,
)

__all__ = [
    "LANGUAGE_BILINGUAL",
    "LANGUAGE_ENGLISH",
    "LANGUAGE_HINDI",
    "TextClause",
    "detect_language",
    "renumber",
    "split_clauses",
]

_NUMBERED = re.compile(r"^\s*(?:\(?[0-9]{1,3}[.)]|\([a-z]\)|\([ivx]+\))\s+")
_BLANK = re.compile(r"\n\s*\n")


@dataclass(frozen=True, slots=True)
class TextClause:
    ref: str
    text: str
    language: str
    page: int | None = None


def split_clauses(text: str, *, page: int | None = None, prefix: str = "") -> list[TextClause]:
    """Paragraphs and numbered items of ``text`` as clauses, references numbered from 1."""
    clauses: list[TextClause] = []
    for block in _BLANK.split(text):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        current: list[str] = []
        for line in lines:
            if current and _NUMBERED.match(line):
                clauses.append(_clause(current, page, prefix, len(clauses) + 1))
                current = []
            current.append(line.strip())
        clauses.append(_clause(current, page, prefix, len(clauses) + 1))
    return clauses


def _clause(lines: list[str], page: int | None, prefix: str, number: int) -> TextClause:
    body = " ".join(lines)
    language = detect_language(body)
    ref = f"{prefix}{language}.p{number}"
    return TextClause(ref=ref, text=body, language=language, page=page)


def renumber(clauses: list[TextClause]) -> list[TextClause]:
    """References ``<lang>.p<n>`` counted per language across pages, in document order."""
    counters: dict[str, int] = {}
    result: list[TextClause] = []
    for clause in clauses:
        counters[clause.language] = counters.get(clause.language, 0) + 1
        result.append(
            TextClause(
                ref=f"{clause.language}.p{counters[clause.language]}",
                text=clause.text,
                language=clause.language,
                page=clause.page,
            )
        )
    return result
