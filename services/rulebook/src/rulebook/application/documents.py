"""Register a parsed regulator document and read it back.

Registration is idempotent: the same document with the same clauses returns what is stored, so
a retried pipeline activity is harmless. A different parse of stored bytes is refused: documents
and clauses are append-only, and mention spans and citations point into the stored text. What
happens to stored documents after a parser change is an open decision (ADR-018), never an
overwrite.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from domain_kernel.documents import Clause
from domain_kernel.ids import ClauseId, DocumentId
from rulebook.domain.documents import (
    StoredClause,
    StoredDocument,
    metadata_differences,
    same_clauses,
    stored_clauses,
)
from rulebook.domain.errors import DocumentConflictError, UnknownDocumentError
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class Registration:
    document_id: DocumentId
    created: bool
    clause_ids: Mapping[str, ClauseId]
    metadata_differs: tuple[str, ...] = ()


class RegisterDocument:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, document: StoredDocument, clauses: Sequence[Clause]) -> Registration:
        submitted = stored_clauses(document.document_id, clauses)
        with self._unit_of_work() as uow:
            stored = uow.documents.get(document.document_id)
            if stored is None and uow.documents.add(document):
                uow.documents.add_clauses(submitted)
                return _registration(document.document_id, submitted, created=True)
            # Stored before, or a concurrent registration won the insert just now.
            stored = stored or uow.documents.get(document.document_id)
            current = uow.documents.clauses(document.document_id)
            if not same_clauses(current, submitted):
                raise DocumentConflictError(
                    f"document {document.document_id} is stored with other clauses: "
                    f"{len(current)} stored, {len(submitted)} submitted by "
                    f"{document.parser_version}"
                )
            differs = () if stored is None else metadata_differences(stored, document)
            return _registration(document.document_id, current, created=False, differs=differs)


class ReadDocument:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, document_id: DocumentId) -> tuple[StoredDocument, tuple[StoredClause, ...]]:
        with self._unit_of_work() as uow:
            document = uow.documents.get(document_id)
            if document is None:
                raise UnknownDocumentError(str(document_id))
            return document, uow.documents.clauses(document_id)


def _registration(
    document_id: DocumentId,
    clauses: Sequence[StoredClause],
    *,
    created: bool,
    differs: tuple[str, ...] = (),
) -> Registration:
    return Registration(
        document_id=document_id,
        created=created,
        clause_ids={clause.clause_ref: clause.clause_id for clause in clauses},
        metadata_differs=differs,
    )
