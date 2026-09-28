"""What the rulebook use cases need from storage, as protocols. Regulatory data is global: there
is no tenant and no row-level security on these tables."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from domain_kernel.ids import DocumentId
from rulebook.domain.documents import StoredClause, StoredDocument


class DocumentRepository(Protocol):
    def get(self, document_id: DocumentId) -> StoredDocument | None: ...

    def add(self, document: StoredDocument) -> bool:
        """Insert unless a row with the id exists; whether this call inserted it."""
        ...

    def clauses(self, document_id: DocumentId) -> tuple[StoredClause, ...]:
        """The document's clauses in order; empty when there are none."""
        ...

    def add_clauses(self, clauses: Sequence[StoredClause]) -> None:
        """Insert the clauses; ones whose id exists already are left as they are."""
        ...


class KnowledgeUnitOfWork(Protocol):
    @property
    def documents(self) -> DocumentRepository: ...


class KnowledgeUnitOfWorkFactory(Protocol):
    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        """One transaction: committed when the block exits cleanly, rolled back otherwise."""
        ...
