"""Indian personal identifiers in text, and how they are masked.

``mask_pii(text)`` replaces every GSTIN, PAN, Aadhaar number, phone number and email address with
a bracketed token naming its kind (``[GSTIN]``, ``[PAN]``, ``[AADHAAR]``, ``[PHONE]``,
``[EMAIL]``) and counts the replacements per kind: the llm-gateway masks prompts with it.
``mask_pii_in(value)`` masks every text inside a JSON-like value with wider patterns and keeps
ids whole: py-common's logging masks every log line with it, and the audit writer every audit row.

Prompts (``PII_PATTERNS``). Patterns are ASCII-only so Devanagari text is never touched. Order
matters: a GSTIN contains a PAN, so GSTINs go first; Aadhaar numbers go before phone numbers, and
a ``+91`` prefix keeps a phone from reading as twelve Aadhaar digits. A ten-digit mobile number is
masked as written; the split form (``98765 43210``) is masked only behind a ``+91`` or ``0``
prefix, because two adjacent five-digit amounts in regulator text would otherwise read as a phone
number. A PAN or GSTIN is upper case and stands on its own. The gateway's tests pin these.

Log lines and audit rows (``RECORD_PII_PATTERNS``) carry identifiers in URLs, keys and file
names too, so ``mask_pii_in`` takes the same five kinds in wider shapes. Each was checked against
the repository's regulatory texts (the recorded notifications and listings, the golden sets and
the seed calendar's quotes) and masks nothing there that the prompt patterns leave:

- an email address URL-encoded: ``owner%40example.com``;
- an identifier glued to an underscore or to digits: ``pan_ABCDE1234F``,
  ``gstin_29ABCDE1234F1Z5``, ``ABCDE1234F09876543210``, ``owner@example.com_old``. Only a letter
  next to a PAN, or after an address, stops it; a GSTIN's shape needs no edge at all; an Aadhaar
  number may be followed by an underscore;
- a PAN or GSTIN in lower case, all of it (``abcde1234f``), not in mixed case;
- a phone number as ``+91 (987) 654 3210``, three, three and four digits behind a prefix, and
  with ``0091`` for ``+91`` (``00919876543210``). A split form still needs its prefix.

Ids stay whole in a record: a UUID in its canonical form, and a run of 16 or more lower-case hex
digits with a letter from a to f in it (a SHA-256 digest, a ``uuid4().hex``, an OpenTelemetry
span id), each standing on its own, with no ASCII letter or digit next to it. None of the five
kinds looks like either, and a digit run inside one would otherwise read as a phone or an Aadhaar
number: about one SHA-256 digest in 31, one ``uuid4().hex`` in 61, one span id in 152 and one
UUID in 70. The email goes last, over the whole text, so an address whose local part is such an
id is still masked. The value of a key ending in ``_id`` or ``_ids`` is left alone.

Masking is idempotent: text masked once is never changed by a second pass. Each call runs the
patterns again until a pass finds nothing, which is how ``ABCDE1234F09876543210`` comes out as
``[PAN][PHONE]`` in one call. The edges are chosen so that this takes a few passes, never one
per identifier: no identifier waits on a token of its own kind, so a ``+91`` number starts a
number of its own even after a digit, and a GSTIN's shape needs no edge. Over every pair of
identifier shapes, glued in every way and repeated, a call takes three passes at most. It takes
linear time: every pattern but the email has a bounded length, and an email's local part may only
start where no local-part character stands before it, once per run of them; 64 KB of
``a.a.a.…@``, which took two seconds before, takes about a millisecond.

This is pattern matching, and it errs towards masking: a ten-digit number that starts with 6 to
9 reads as a phone number, and a twelve-digit number that starts with 2 to 9 (spaces or hyphens
after every fourth digit allowed) as an Aadhaar number, whatever it really is, such as an amount
or a reference. It misses what has no pattern: a name, an address, free text.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, overload

from domain_kernel._validation import require_instance

_Patterns = tuple[tuple[str, re.Pattern[str], str], ...]

_GSTIN = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b", re.ASCII)
_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.ASCII)
_AADHAAR = re.compile(r"(?<![0-9+])[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}\b", re.ASCII)
_PHONE = re.compile(
    # A digit before the number makes it part of a longer one, except before a "+91", which
    # starts a number of its own: so "+91…" glued after another number is masked with it.
    r"(?:\+91[ -]?|(?<![0-9])0)(?:[6-9][0-9]{4}[ -][0-9]{5}|[6-9][0-9]{9})(?![0-9])"
    r"|(?<![0-9])[6-9][0-9]{9}(?![0-9])",
    re.ASCII,
)
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.ASCII
)

_RECORD_GSTIN = re.compile(
    r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]|[0-9]{2}[a-z]{5}[0-9]{4}[a-z][0-9a-z]z[0-9a-z]",
    re.ASCII,
)
_RECORD_PAN = re.compile(
    r"(?<![A-Za-z])(?:[A-Z]{5}[0-9]{4}[A-Z]|[a-z]{5}[0-9]{4}[a-z])(?![A-Za-z])", re.ASCII
)
_RECORD_AADHAAR = re.compile(
    r"(?<![0-9+])[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}(?![0-9A-Za-z])", re.ASCII
)
_RECORD_PHONE = re.compile(
    r"(?:\+91[ -]?|(?<![0-9])(?:0091[ -]?|0))"
    r"(?:[6-9][0-9]{4}[ -][0-9]{5}|\(?[6-9][0-9]{2}\)?[ -]?[0-9]{3}[ -]?[0-9]{4})(?![0-9])"
    r"|(?<![0-9])[6-9][0-9]{9}(?![0-9])",
    re.ASCII,
)
_RECORD_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+(?:@|%40)[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z])",
    re.ASCII,
)

PII_PATTERNS: Final[_Patterns] = (
    ("gstin", _GSTIN, "[GSTIN]"),
    ("pan", _PAN, "[PAN]"),
    ("aadhaar", _AADHAAR, "[AADHAAR]"),
    ("phone", _PHONE, "[PHONE]"),
    ("email", _EMAIL, "[EMAIL]"),
)
"""Each kind with the pattern ``mask_pii`` masks a prompt with and the token that replaces a
match, in the order they apply."""
RECORD_PII_PATTERNS: Final[_Patterns] = (
    ("gstin", _RECORD_GSTIN, "[GSTIN]"),
    ("pan", _RECORD_PAN, "[PAN]"),
    ("aadhaar", _RECORD_AADHAAR, "[AADHAAR]"),
    ("phone", _RECORD_PHONE, "[PHONE]"),
    ("email", _RECORD_EMAIL, "[EMAIL]"),
)
"""The wider patterns ``mask_pii_in`` masks log lines and audit rows with, in the order they
apply: the first four between the ids it keeps, the email over the whole text."""
PII_KINDS: Final[tuple[str, ...]] = tuple(kind for kind, _, _ in PII_PATTERNS)
ID_KEY_SUFFIXES: Final[tuple[str, ...]] = ("_id", "_ids")
"""A key with one of these endings holds our own ids (``tenant_id``, ``obligation_ids``), whose
value ``mask_pii_in`` leaves alone."""
MAX_DEPTH: Final = 32
"""How deep ``mask_pii_in`` walks: a mapping, list or tuple nested deeper is replaced by
``TOO_DEEP``."""
TOO_DEEP: Final = "[TOO DEEP]"
CYCLE: Final = "[CYCLE]"
"""What replaces a mapping, list or tuple that holds itself, where it comes round again."""

_KEPT: Final = re.compile(
    r"(?<![0-9A-Za-z])"
    r"([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"|(?=[0-9]*[a-f])[0-9a-f]{16,})"
    r"(?![0-9A-Za-z])",
    re.ASCII,
)
"""What ``mask_pii_in`` keeps whole: a canonical UUID, or a lower-case hex run of 16 or more with
a letter in it, standing on its own; the one group makes ``split`` return them."""
_RECORD_BETWEEN_IDS: Final = RECORD_PII_PATTERNS[:-1]
_RECORD_EMAILS: Final = RECORD_PII_PATTERNS[-1:]
_DIGIT: Final = re.compile(r"[0-9]", re.ASCII)
"""Every pattern but the email needs an ASCII digit, and the email needs an ``@`` (or ``%40``):
a pattern that cannot match is not run."""


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
    """Replace every identifier in ``text`` with the bracketed token naming its kind, with the
    prompt patterns (``PII_PATTERNS``), until nothing more is found."""
    require_instance(text, str, "text")
    return _fixed_point(text, _prompt_pass)


@overload
def mask_pii_in(
    value: str, *, id_keys: bool = ..., render: Callable[[object], str] | None = ...
) -> str: ...
@overload
def mask_pii_in(
    value: object, *, id_keys: bool = ..., render: Callable[[object], str] | None = ...
) -> object: ...
def mask_pii_in(
    value: object, *, id_keys: bool = True, render: Callable[[object], str] | None = None
) -> object:
    """A copy of the JSON-like ``value`` with every text in it masked with the record patterns
    (``RECORD_PII_PATTERNS``), around the UUIDs and hex ids it keeps whole.

    Mappings, lists and tuples are walked: a mapping comes back as a dict, a list as a list and a
    tuple as a tuple, so nothing the caller holds is changed. A mapping's keys are never masked,
    and with ``id_keys`` the value of a key that ends in ``_id`` or ``_ids`` is returned as it is.
    Text is masked; a number, a boolean and None are returned as they are. Any other leaf is
    returned as it is too, or, given ``render``, turned into text with it and masked.

    It never recurses without end: a mapping, list or tuple nested deeper than ``MAX_DEPTH`` is
    replaced by ``TOO_DEEP``, and one inside itself by ``CYCLE``.
    """
    return _walk(value, id_keys, render, 0, set())


def _walk(
    value: object,
    id_keys: bool,
    render: Callable[[object], str] | None,
    depth: int,
    ancestors: set[int],
) -> object:
    if isinstance(value, str):
        return _fixed_point(value, _record_pass).text
    if value is None or isinstance(value, bool | int | float):
        return value
    if not isinstance(value, Mapping | list | tuple):
        return value if render is None else _fixed_point(render(value), _record_pass).text
    if id(value) in ancestors:
        return CYCLE
    if depth >= MAX_DEPTH:
        return TOO_DEEP
    ancestors.add(id(value))
    try:
        if isinstance(value, Mapping):
            return {
                key: item
                if id_keys and _is_id_key(key)
                else _walk(item, id_keys, render, depth + 1, ancestors)
                for key, item in value.items()
            }
        items = [_walk(item, id_keys, render, depth + 1, ancestors) for item in value]
        return items if isinstance(value, list) else tuple(items)
    finally:
        ancestors.discard(id(value))


def _fixed_point(text: str, one_pass: Callable[[str, dict[str, int]], str]) -> MaskResult:
    """``text`` masked by ``one_pass`` again until a pass replaces nothing (a few passes at
    most: see the module's notes on idempotence)."""
    counts = dict.fromkeys(PII_KINDS, 0)
    while True:
        before = sum(counts.values())
        text = one_pass(text, counts)
        if sum(counts.values()) == before:
            return MaskResult(text, counts)


def _prompt_pass(text: str, counts: dict[str, int]) -> str:
    return _substitute(text, PII_PATTERNS, counts)


def _record_pass(text: str, counts: dict[str, int]) -> str:
    """The kinds but the email between the ids kept whole, then the email over the whole text."""
    pieces = _KEPT.split(text)
    text = "".join(
        piece if index % 2 else _substitute(piece, _RECORD_BETWEEN_IDS, counts)
        for index, piece in enumerate(pieces)
    )
    return _substitute(text, _RECORD_EMAILS, counts)


def _substitute(text: str, patterns: _Patterns, counts: dict[str, int]) -> str:
    has_digit = _DIGIT.search(text) is not None
    has_at = "@" in text or "%40" in text
    for kind, pattern, token in patterns:
        if has_at if kind == "email" else has_digit:
            text, found = pattern.subn(token, text)
            counts[kind] += found
    return text


def _is_id_key(key: object) -> bool:
    return isinstance(key, str) and key.endswith(ID_KEY_SUFFIXES)
