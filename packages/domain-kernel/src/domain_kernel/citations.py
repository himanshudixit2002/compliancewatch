"""A pointer from a rule to the clause it came from, and the checks that a quote is really in
the clause.

``quote_match_ratio`` scores how well a quote matches the best window of a clause after both are
folded (case, dashes, spacing around hyphens, runs of whitespace), so text extraction noise such
as "sub -section" or an en dash does not fail an honest quote. A fuzzy score alone accepts a
quote that differs only in a date or a form number, so ``evidence_tokens_missing`` lists the
numbers, form codes and month names of the quote that the clause does not contain.
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final

from domain_kernel._validation import require_bool, require_instance, require_text
from domain_kernel.ids import ClauseId

QUOTE_MATCH_THRESHOLD: Final = 0.85
"""The lowest ``quote_match_ratio`` at which a quote counts as found in its clause."""

MAX_QUOTE_CHARS: Final = 400
"""Quotes are scored on their first 400 characters; a citation quotes a sentence, not a page."""

MAX_TEXT_CHARS: Final = 50_000
"""Clause text beyond this length is not searched."""

DASHES: Final = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"
"""Unicode dashes that regulator PDFs use where ASCII text has ``-``."""

_DASH_TO_HYPHEN = str.maketrans(dict.fromkeys(DASHES, "-"))
_SPACED_HYPHEN = re.compile(r"\s*-\s*")
_TOKEN = re.compile(r"[^\W_]+(?:[-/.][^\W_]+)*")
_DIGIT = re.compile(r"\d")
_MONTHS = frozenset(
    {
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    }
)
_MIN_ANCHOR = 4


@dataclass(frozen=True, slots=True)
class Citation:
    """Clause reference plus the quoted text. The extractor marks it verified after checking
    the quote against the source; the kernel only records the flag."""

    clause_ref: str
    quote: str
    verified: bool = False
    clause_id: ClauseId | None = None

    def __post_init__(self) -> None:
        require_text(self.clause_ref, "clause_ref")
        require_text(self.quote, "quote", strip=False)
        require_bool(self.verified, "verified")
        if self.clause_id is not None:
            require_instance(self.clause_id, ClauseId, "clause_id")


def _fold(text: str) -> str:
    """Casefold, every dash as ``-`` with no spaces around it, single spaces elsewhere."""
    folded = " ".join(text.casefold().translate(_DASH_TO_HYPHEN).split())
    return _SPACED_HYPHEN.sub("-", folded)


def quote_match_ratio(quote: str, text: str) -> float:
    """How well ``quote`` matches its best window in ``text``, from 0.0 to 1.0.

    Both sides are folded first. A quote contained in the text scores 1.0 and an empty quote
    0.0. Otherwise every run of at least four matching characters anchors a window of the
    quote's length in the text, and the best ``difflib`` ratio over those windows wins.
    """
    folded_quote = _fold(require_instance(quote, str, "quote"))[:MAX_QUOTE_CHARS]
    folded_text = _fold(require_instance(text, str, "text"))[:MAX_TEXT_CHARS]
    if not folded_quote:
        return 0.0
    if folded_quote in folded_text:
        return 1.0
    best = 0.0
    length = len(folded_quote)
    matcher = SequenceMatcher(None, folded_quote, folded_text, autojunk=False)
    for block in matcher.get_matching_blocks():
        if block.size < _MIN_ANCHOR:
            continue
        start = max(0, block.b - block.a)
        window = folded_text[start : start + length]
        best = max(best, SequenceMatcher(None, folded_quote, window, autojunk=False).ratio())
    return best


def quote_matches(quote: str, text: str, threshold: float = QUOTE_MATCH_THRESHOLD) -> bool:
    """``quote_match_ratio(quote, text) >= threshold``."""
    return quote_match_ratio(quote, text) >= threshold


def evidence_tokens_missing(quote: str, text: str) -> tuple[str, ...]:
    """The tokens of ``quote`` that carry a fact and are not in ``text``, in quote order.

    A token carries a fact when it has a digit, which covers dates ("30.09.2026"), provisions
    ("39(1)" gives "39" and "1") and form codes ("gstr-3b"), or when it is an English month
    name. Both sides are folded as for ``quote_match_ratio``; a token counts as present only as
    a whole token.
    """
    folded_text = _fold(require_instance(text, str, "text"))
    present = set(_TOKEN.findall(folded_text))
    missing: list[str] = []
    for token in _TOKEN.findall(_fold(require_instance(quote, str, "quote"))):
        carries_fact = bool(_DIGIT.search(token)) or token in _MONTHS
        if carries_fact and token not in present and token not in missing:
            missing.append(token)
    return tuple(missing)
