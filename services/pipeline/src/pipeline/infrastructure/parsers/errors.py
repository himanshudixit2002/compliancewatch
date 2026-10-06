"""How a parser of the chain says it will not parse a document: it cannot read it
(``UnparsedDocumentError``, the domain's), or another parser of the chain reads it better
(``DeclinedDocumentError``)."""

from pipeline.domain.errors import UnparsedDocumentError


class DeclinedDocumentError(UnparsedDocumentError):
    """The parser can read the document, but the next one of the chain keeps more of it (a PDF
    or a page with tables); the chain asks this one again when no later one reads it."""


__all__ = ["DeclinedDocumentError", "UnparsedDocumentError"]
