"""Parsers: fetched bytes into clauses with stable references, and the chain that picks one."""

from pipeline.infrastructure.parsers.chain import CHAIN, ChainLink, ParserChain
from pipeline.infrastructure.parsers.errors import DeclinedDocumentError, UnparsedDocumentError
from pipeline.infrastructure.parsers.html import HtmlParser
from pipeline.infrastructure.parsers.html_tables import HtmlTableParser, has_table
from pipeline.infrastructure.parsers.pdf import PdfParser
from pipeline.infrastructure.parsers.pdf_tables import PdfTableParser, has_tables
from pipeline.infrastructure.parsers.sources import parsers_for
from pipeline.infrastructure.parsers.text import (
    LANGUAGE_BILINGUAL,
    LANGUAGE_ENGLISH,
    LANGUAGE_HINDI,
    detect_language,
    split_clauses,
)

__all__ = [
    "CHAIN",
    "LANGUAGE_BILINGUAL",
    "LANGUAGE_ENGLISH",
    "LANGUAGE_HINDI",
    "ChainLink",
    "DeclinedDocumentError",
    "HtmlParser",
    "HtmlTableParser",
    "ParserChain",
    "PdfParser",
    "PdfTableParser",
    "UnparsedDocumentError",
    "detect_language",
    "has_table",
    "has_tables",
    "parsers_for",
    "split_clauses",
]
