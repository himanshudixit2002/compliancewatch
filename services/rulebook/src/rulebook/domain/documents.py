"""Regulator documents and their clauses as the rulebook stores them.

A document is keyed by its digest and a clause by the id the kernel derives from the document id
and the clause ref, so the pipeline and the rulebook agree on both without asking each other.
Stored text is the parser's output verbatim: mention spans are offsets into it.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import date, datetime

from domain_kernel.documents import (
    Clause,
    DocumentType,
    ParsedDocument,
    clause_id_for,
    document_id_for,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId, SourceId
from rulebook.domain.errors import DocumentIdMismatchError

CLAUSE_REF_PATTERN = r"^(?:[a-z]{2,3}\.)?p[1-9][0-9]{0,3}$"
"""``en.p3``, ``mul.p1`` or a bare ``p2``: the refs the parsers emit, at most 9999 per language."""

_IGNORED_ON_COMPARE = frozenset({"fetched_at", "raw_uri"})


@dataclass(frozen=True, slots=True)
class StoredDocument:
    """What the rulebook keeps about a document besides its clauses."""

    document_id: DocumentId
    source_id: SourceId
    sha256: str
    regulator: str
    doc_type: DocumentType
    url: str
    language: str
    media_type: str
    parser_version: str
    fetched_at: datetime
    external_ref: str = ""
    title: str = ""
    published_at: date | None = None
    raw_uri: str | None = None

    def __post_init__(self) -> None:
        if document_id_for(self.sha256) != self.document_id:
            raise DocumentIdMismatchError(
                f"document id {self.document_id} is not the first half of sha256 {self.sha256}"
            )
        for name in ("regulator", "url", "language", "media_type"):
            if not str(getattr(self, name)).strip():
                raise InvariantViolationError(f"{name} must not be blank")
        if not self.parser_version:
            raise InvariantViolationError("parser_version must name the parser, e.g. 'pdf@1'")
        if self.fetched_at.tzinfo is None:
            raise InvariantViolationError("fetched_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class StoredClause:
    """One clause under its derived id, in document order from 1."""

    clause_id: ClauseId
    document_id: DocumentId
    clause_ref: str
    ordinal: int
    text: str
    text_sha256: str
    page: int | None = None

    def as_clause(self) -> Clause:
        return Clause(clause_ref=self.clause_ref, text=self.text, page=self.page)


def stored_clauses(document_id: DocumentId, clauses: Sequence[Clause]) -> tuple[StoredClause, ...]:
    """The clauses in order under their derived ids. Refs must be unique and there must be at
    least one clause, the same rules ``ParsedDocument`` enforces."""
    if not clauses:
        raise InvariantViolationError("a document needs at least one clause")
    seen: set[str] = set()
    stored: list[StoredClause] = []
    for ordinal, clause in enumerate(clauses, 1):
        if clause.clause_ref in seen:
            raise InvariantViolationError(f"duplicate clause_ref {clause.clause_ref!r}")
        seen.add(clause.clause_ref)
        stored.append(
            StoredClause(
                clause_id=clause_id_for(document_id, clause.clause_ref),
                document_id=document_id,
                clause_ref=clause.clause_ref,
                ordinal=ordinal,
                text=clause.text,
                text_sha256=hashlib.sha256(clause.text.encode("utf-8")).hexdigest(),
                page=clause.page,
            )
        )
    return tuple(stored)


def same_clauses(stored: Sequence[StoredClause], submitted: Sequence[StoredClause]) -> bool:
    """Whether two clause lists are the same parse: same refs in the same order, same text and
    pages. Ids follow from refs, so they need no separate check."""

    def shape(clauses: Sequence[StoredClause]) -> list[tuple[str, int, str, int | None]]:
        return [(c.clause_ref, c.ordinal, c.text_sha256, c.page) for c in clauses]

    return shape(stored) == shape(submitted)


def metadata_differences(stored: StoredDocument, submitted: StoredDocument) -> tuple[str, ...]:
    """Names of the fields whose submitted value differs from the stored one, ignoring when and
    where the bytes were fetched. The stored row wins; the caller reports the difference."""
    return tuple(
        field.name
        for field in fields(StoredDocument)
        if field.name not in _IGNORED_ON_COMPARE
        and getattr(stored, field.name) != getattr(submitted, field.name)
    )


def as_parsed_document(document: StoredDocument, clauses: Sequence[StoredClause]) -> ParsedDocument:
    """The stored document as the kernel's ``ParsedDocument``, for readers that extract from it."""
    return ParsedDocument(
        document_id=document.document_id,
        doc_type=document.doc_type,
        title=document.title,
        clauses=tuple(clause.as_clause() for clause in clauses),
        published_at=document.published_at,
        language=document.language,
        parser_version=document.parser_version,
    )
