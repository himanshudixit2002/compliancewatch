"""Mask Indian personal identifiers before text leaves the system.

The patterns, their order and the tokens are the kernel's (``domain_kernel.pii``), which the
logging and the audit writer use too: GSTINs, PANs, Aadhaar numbers, phone numbers and email
addresses become ``[GSTIN]``, ``[PAN]``, ``[AADHAAR]``, ``[PHONE]`` and ``[EMAIL]``. The kernel's
docstring has the rules of each pattern. This module keeps the gateway's names for them.
"""

from domain_kernel.pii import PII_KINDS, MaskResult, mask_pii

__all__ = ["PII_KINDS", "ScrubResult", "scrub"]

ScrubResult = MaskResult
"""The masked text and how many of each kind were replaced (every kind is a key)."""


def scrub(text: str) -> ScrubResult:
    """Replace every identifier with a bracketed placeholder naming its kind."""
    return mask_pii(text)
