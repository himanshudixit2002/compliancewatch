"""Mask Indian personal identifiers before text leaves the system.

Patterns are ASCII-only so Devanagari text is never touched. Order matters: a GSTIN contains
a PAN, so GSTINs go first; Aadhaar numbers go before phone numbers, and a ``+91`` prefix keeps
a phone from reading as twelve Aadhaar digits. A ten-digit mobile number is masked as written;
the split form (``98765 43210``) is masked only behind a ``+91`` or ``0`` prefix, because two
adjacent five-digit amounts in regulator text would otherwise read as a phone number.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from domain_kernel._validation import require_instance

GSTIN = re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b", re.ASCII)
PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.ASCII)
AADHAAR = re.compile(r"(?<![0-9+])[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}\b", re.ASCII)
PHONE = re.compile(
    r"(?<![0-9])(?:(?:\+91[ -]?|0)[6-9][0-9]{4}[ -][0-9]{5}"
    r"|(?:\+91[ -]?|0)?[6-9][0-9]{9})(?![0-9])",
    re.ASCII,
)
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", re.ASCII)

PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("gstin", GSTIN, "[GSTIN]"),
    ("pan", PAN, "[PAN]"),
    ("aadhaar", AADHAAR, "[AADHAAR]"),
    ("phone", PHONE, "[PHONE]"),
    ("email", EMAIL, "[EMAIL]"),
)
PII_KINDS: tuple[str, ...] = tuple(kind for kind, _, _ in PATTERNS)


@dataclass(frozen=True, slots=True)
class ScrubResult:
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


def scrub(text: str) -> ScrubResult:
    """Replace every identifier with a bracketed placeholder naming its kind."""
    require_instance(text, str, "text")
    counts: dict[str, int] = {}
    for kind, pattern, placeholder in PATTERNS:
        text, counts[kind] = pattern.subn(placeholder, text)
    return ScrubResult(text, counts)
