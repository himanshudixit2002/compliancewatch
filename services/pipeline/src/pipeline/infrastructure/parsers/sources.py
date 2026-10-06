"""The parser chain for documents of one type, for the tools that take a list of parsers (the
backfill, the labelling tool); the worker's chain parses each document as its source's type
(``ParserChain(catalog)``)."""

from domain_kernel.documents import DocumentType
from domain_kernel.protocols import DocumentParser
from pipeline.infrastructure.parsers.chain import ParserChain


def parsers_for(doc_type: DocumentType) -> list[DocumentParser]:
    """The chain giving ``doc_type``, as the one parser of a list."""
    return [ParserChain(default_type=doc_type)]
