"""Indian personal identifiers in text, and how they are masked.

``mask_pii(text)`` replaces every GSTIN, PAN, Aadhaar number, phone number and email address with
a bracketed token naming its kind (``[GSTIN]``, ``[PAN]``, ``[AADHAAR]``, ``[PHONE]``,
``[EMAIL]``) and counts the replacements per kind. ``mask_pii_in(value)`` does the same to every
text inside a JSON-like value, except under a key that names one of our ids. The llm-gateway
masks prompts with them before text leaves the system, py-common's logging masks every log line,
and the audit writer masks the reason and the state of every audit row.

Patterns are ASCII-only so Devanagari text is never touched. Order matters: a GSTIN contains
a PAN, so GSTINs go first; Aadhaar numbers go before phone numbers, and a ``+91`` prefix keeps
a phone from reading as twelve Aadhaar digits. A ten-digit mobile number is masked as written;
the split form (``98765 43210``) is masked only behind a ``+91`` or ``0`` prefix, because two
adjacent five-digit amounts in regulator text would otherwise read as a phone number.

This is pattern matching, and it errs towards masking: a ten-digit number that starts with 6 to
9 reads as a phone number, and a twelve-digit number that starts with 2 to 9 (spaces or hyphens
after every fourth digit allowed) as an Aadhaar number, whatever it really is, such as an amount or
a reference. A digit run inside a UUID can read the same way (about one random UUID in seventy has
one), so ``mask_pii_in`` keeps every UUID written in its canonical form whole, and leaves the value
of a key ending in ``_id`` or ``_ids`` alone. ``mask_pii`` applies the patterns alone, as the
gateway always has.
"""

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, overload

from domain_kernel._validation import require_instance

_GSTIN = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b", re.ASCII)
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.ASCII)
_AADHAAR = re.compile(r"(?<![0-9+])[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}\b", re.ASCII)
_PHONE = re.compile(
    r"(?<![0-9])(?:(?:\+91[ -]?|0)[6-9][0-9]{4}[ -][0-9]{5}"
    r"|(?:\+91[ -]?|0)?[6-9][0-9]{9})(?![0-9])",
    re.ASCII,
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.ASCII)

PII_PATTERNS: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = (
    ("gstin", _GSTIN, "[GSTIN]"),
    ("pan", _PAN, "[PAN]"),
    ("aadhaar", _AADHAAR, "[AADHAAR]"),
    ("phone", _PHONE, "[PHONE]"),
    ("email", _EMAIL, "[EMAIL]"),
)
"""Each kind with its pattern and the token that replaces a match, in the order they apply."""
PII_KINDS: Final[tuple[str, ...]] = tuple(kind for kind, _, _ in PII_PATTERNS)
ID_KEY_SUFFIXES: Final[tuple[str, ...]] = ("_id", "_ids")
"""A key with one of these endings holds our own ids (``tenant_id``, ``obligation_ids``), whose
value ``mask_pii_in`` never masks."""

_UUID: Final = re.compile(
    r"(?<![0-9A-Za-z-])"
    r"([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})"
    r"(?![0-9A-Za-z-])",
    re.ASCII,
)
"""A UUID in its canonical form, standing on its own: none of the five kinds has its shape, so
``mask_pii_in`` masks only the text around it."""
_DIGIT: Final = re.compile(r"[0-9]", re.ASCII)
"""Every pattern but the email needs an ASCII digit, and the email needs an ``@``: text with
neither is returned as it is, and the email pattern, whose cost grows with the square of a long
run of word characters and dots, runs only on text with an ``@``."""


@dataclass(frozen=True, slots=True)
class MaskResult:
    """The masked text and how many of each kind were replaced (every kind is a key)."""

    text: str
    counts: Mapping[str, int]

    def __post_init__(self) -> None:
        require_instance(self.text, str, "text")
        counts = {kind: int(self.counts.get(kind, 0)) for kind in PII_KINDS}
        object.__setattr__(self, "counts", MappingProxyType(counts))

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def mask_pii(text: str) -> MaskResult:
    """Replace every identifier in ``text`` with the bracketed token naming its kind."""
    require_instance(text, str, "text")
    has_digit = _DIGIT.search(text) is not None
    has_at = "@" in text
    counts: dict[str, int] = {}
    for kind, pattern, token in PII_PATTERNS:
        if has_at if pattern is _EMAIL else has_digit:
            text, counts[kind] = pattern.subn(token, text)
    return MaskResult(text, counts)


@overload
def mask_pii_in(value: str, *, keep: Collection[str] = ...) -> str: ...
@overload
def mask_pii_in(value: object, *, keep: Collection[str] = ...) -> object: ...
def mask_pii_in(value: object, *, keep: Collection[str] = frozenset()) -> object:
    """A copy of the JSON-like ``value`` with every text in it masked by ``mask_pii``, except
    that a UUID in its canonical form is kept whole.

    Mappings, lists and tuples are walked at any depth: a mapping comes back as a dict, a list as
    a list and a tuple as a tuple, so nothing the caller holds is changed. Text is masked and
    anything else is returned as it is. A mapping's keys are never masked, and the value of a key
    that ends in ``_id`` or ``_ids``, or that ``keep`` names, is returned as it is.
    """
    if isinstance(value, str):
        return _masked_text(value)
    if isinstance(value, Mapping):
        return {
            key: item if _kept(key, keep) else mask_pii_in(item, keep=keep)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_pii_in(item, keep=keep) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_pii_in(item, keep=keep) for item in value)
    return value


def _masked_text(text: str) -> str:
    """``text`` masked around the UUIDs in it, each of which is kept whole."""
    pieces = _UUID.split(text)
    return "".join(
        piece if index % 2 else mask_pii(piece).text for index, piece in enumerate(pieces)
    )


def _kept(key: object, keep: Collection[str]) -> bool:
    return isinstance(key, str) and (key in keep or key.endswith(ID_KEY_SUFFIXES))
