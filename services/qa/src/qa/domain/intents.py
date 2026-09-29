"""The two questions the structured layer answers from a business's obligations, without a
model: "when is my <form> due" and "what is due this month" (or next month).

The patterns are anchored and read the question casefolded, so anything longer or different
passes to the next layer. The form is read with the kernel's form normalisation, so "gstr 3b",
"GSTR3B" and "GSTR-3B" are the same form; a word without a digit is not a form code.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from domain_kernel.citations import DASHES
from domain_kernel.knowledge import EntityType, normalise_name

_DUE_FOR_FORM: Final = re.compile(
    r"when is (?:my|our|the) (?:next )?(?:form )?(?P<form>[a-z0-9][a-z0-9 -]{0,23}?)"
    r"(?: return)? due"
)
_DUE_IN_MONTH: Final = re.compile(
    r"what(?: is|'s| do i have| do we have)? due(?: for (?:me|us))? (?P<when>this|next) month"
)
_FORM_CODE: Final = re.compile(r"[A-Z]+(?:-[A-Z0-9]+)+")
_FOLD = str.maketrans({**dict.fromkeys(DASHES, "-"), "\u2019": "'"})
"""Unicode dashes read as ``-`` and a typographic apostrophe as ``'``."""


@dataclass(frozen=True, slots=True)
class DueForForm:
    """The next due date of one form, by its canonical code (``GSTR-3B``)."""

    form: str


@dataclass(frozen=True, slots=True)
class DueInWindow:
    """Everything due between two days in India, both included."""

    start: date
    end: date
    label: str


type Intent = DueForForm | DueInWindow


def match_intent(question: str, as_of: date) -> Intent | None:
    """The structured intent of ``question`` asked on ``as_of``, or ``None``."""
    text = " ".join(question.translate(_FOLD).casefold().split()).rstrip(" ?.!")
    form_match = _DUE_FOR_FORM.fullmatch(text)
    if form_match is not None:
        form = normalise_name(EntityType.FORM, form_match.group("form"))
        if _FORM_CODE.fullmatch(form) and any(char.isdigit() for char in form):
            return DueForForm(form)
        return None
    month_match = _DUE_IN_MONTH.fullmatch(text)
    if month_match is None:
        return None
    start = as_of.replace(day=1)
    if month_match.group("when") == "next":
        start = _next_month(start)
    end = _next_month(start) - timedelta(days=1)
    return DueInWindow(start, end, f"{month_match['when']} month")


def _next_month(first: date) -> date:
    return date(first.year + first.month // 12, first.month % 12 + 1, 1)
