"""PDF text into clauses. Text-layer only: a scanned PDF yields nothing and is reported as
unparsed so a person can handle it (OCR is a later adapter)."""

import io

from pypdf import PdfReader

from domain_kernel.documents import (
    Clause,
    DocumentType,
    ParsedDocument,
    RawDocument,
    document_id_for,
)
from pipeline.infrastructure.parsers.text import (
    LANGUAGE_BILINGUAL,
    TextClause,
    detect_language,
    renumber,
    split_clauses,
)

PARSER_VERSION = "pdf@1"
"""Bump when a change can alter the clause text or refs this parser gives for the same bytes."""


class UnparsedDocumentError(ValueError):
    """No text layer: the PDF needs OCR or a person."""


class PdfParser:
    def __init__(self, *, doc_type: DocumentType = DocumentType.NOTIFICATION) -> None:
        self._doc_type = doc_type

    def supports(self, doc: RawDocument) -> bool:
        return doc.media_type.split(";")[0].strip() == "application/pdf" or doc.content.startswith(
            b"%PDF-"
        )

    def parse(self, doc: RawDocument) -> ParsedDocument:
        reader = PdfReader(io.BytesIO(doc.content))
        clauses: list[TextClause] = []
        full_text: list[str] = []
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            full_text.append(text)
            clauses.extend(split_clauses(text, page=number))
        if not any(clause.text.strip() for clause in clauses):
            raise UnparsedDocumentError("the PDF has no text layer")
        clauses = renumber(clauses)
        languages = {clause.language for clause in clauses}
        language = languages.pop() if len(languages) == 1 else LANGUAGE_BILINGUAL
        title = next((c.text for c in clauses if len(c.text) > 12), clauses[0].text)[:200]
        return ParsedDocument(
            document_id=document_id_for(doc.sha256),
            doc_type=self._doc_type,
            title=title,
            clauses=tuple(
                Clause(clause_ref=clause.ref, text=clause.text, page=clause.page)
                for clause in clauses
            ),
            language=language
            if language != LANGUAGE_BILINGUAL
            else detect_language("\n".join(full_text)),
            parser_version=PARSER_VERSION,
        )
