"""Register a parsed regulator document and read it back.

Registration is idempotent: the same document with the same clauses returns what is stored, so
a retried pipeline activity is harmless. Documents and clauses are append-only, since mention
spans and citations point into the stored text, so the first parse of a document is kept
(ADR-018, addendum of 2026-10-06):

- a parse of stored bytes by another parser version (a newer parser, or an analyst's transcript)
  is answered with what is stored: the stored clause ids, the stored parser version, and
  ``parser_version`` among ``metadata_differs``. Nothing is written and nothing is refused;
- a different parse by the same parser version is refused (``DocumentConflictError``, a 409):
  that parser changed what it gives for the same bytes without a new version, which is a bug.
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
    """What a registration came to. ``parser_version`` names the parser whose clauses are stored:
    the submitted one, or the one that parsed the document first when another submits it."""

    document_id: DocumentId
    created: bool
    clause_ids: Mapping[str, ClauseId]
    metadata_differs: tuple[str, ...] = ()
    parser_version: str = ""


class RegisterDocument:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, document: StoredDocument, clauses: Sequence[Clause]) -> Registration:
        submitted = stored_clauses(document.document_id, clauses)
        with self._unit_of_work() as uow:
            stored = uow.documents.get(document.document_id)
            if stored is None and uow.documents.add(document):
                uow.documents.add_clauses(submitted)
                return _registration(
                    document.document_id,
                    submitted,
                    created=True,
                    parser_version=document.parser_version,
                )
            # Stored before, or a concurrent registration won the insert just now.
            stored = stored or uow.documents.get(document.document_id)
            current = uow.documents.clauses(document.document_id)
            kept = document.parser_version if stored is None else stored.parser_version
            if kept == document.parser_version and not same_clauses(current, submitted):
                raise DocumentConflictError(
                    f"document {document.document_id} is stored with other clauses by the same "
                    f"parser {kept}: {len(current)} stored, {len(submitted)} submitted; a parser "
                    "that changes what it gives for the same bytes needs a new version"
                )
            differs = () if stored is None else metadata_differences(stored, document)
            return _registration(
                document.document_id, current, created=False, differs=differs, parser_version=kept
            )


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
    parser_version: str,
    differs: tuple[str, ...] = (),
) -> Registration:
    return Registration(
        document_id=document_id,
        created=created,
        clause_ids={clause.clause_ref: clause.clause_id for clause in clauses},
        metadata_differs=differs,
        parser_version=parser_version,
    )
