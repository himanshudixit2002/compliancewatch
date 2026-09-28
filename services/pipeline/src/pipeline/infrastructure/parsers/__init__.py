"""Parsers: fetched bytes into clauses with stable references."""

from pipeline.infrastructure.parsers.html import HtmlParser
from pipeline.infrastructure.parsers.pdf import PdfParser
from pipeline.infrastructure.parsers.text import (
    LANGUAGE_BILINGUAL,
    LANGUAGE_ENGLISH,
    LANGUAGE_HINDI,
    detect_language,
    split_clauses,
)

__all__ = [
    "LANGUAGE_BILINGUAL",
    "LANGUAGE_ENGLISH",
    "LANGUAGE_HINDI",
    "HtmlParser",
    "PdfParser",
    "detect_language",
    "split_clauses",
]
