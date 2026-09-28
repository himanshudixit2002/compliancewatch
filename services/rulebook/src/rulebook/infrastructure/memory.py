"""In-memory unit of work: the store for tests, demos and a rulebook without a database.

Changes made inside a unit of work become visible to others only when the block exits cleanly,
as with the Postgres store. Units of work run one at a time (a lock held for the whole block),
so two overlapping requests cannot both start from the same tables and lose a write.
"""

import threading
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field

from domain_kernel.ids import ClauseId, DocumentId
from rulebook.domain.documents import StoredClause, StoredDocument
from rulebook.domain.repository import KnowledgeUnitOfWork


@dataclass
class _Tables:
    documents: dict[DocumentId, StoredDocument] = field(default_factory=dict)
    clauses: dict[ClauseId, StoredClause] = field(default_factory=dict)

    def copy(self) -> "_Tables":
        return _Tables(dict(self.documents), dict(self.clauses))


class MemoryDocumentRepository:
    def __init__(self, tables: _Tables) -> None:
        self._tables = tables

    def get(self, document_id: DocumentId) -> StoredDocument | None:
        return self._tables.documents.get(document_id)

    def add(self, document: StoredDocument) -> bool:
        if document.document_id in self._tables.documents:
            return False
        self._tables.documents[document.document_id] = document
        return True

    def clauses(self, document_id: DocumentId) -> tuple[StoredClause, ...]:
        found = [c for c in self._tables.clauses.values() if c.document_id == document_id]
        return tuple(sorted(found, key=lambda clause: clause.ordinal))

    def add_clauses(self, clauses: Sequence[StoredClause]) -> None:
        for clause in clauses:
            self._tables.clauses.setdefault(clause.clause_id, clause)


class MemoryUnitOfWork:
    def __init__(self, tables: _Tables) -> None:
        self._documents = MemoryDocumentRepository(tables)

    @property
    def documents(self) -> MemoryDocumentRepository:
        return self._documents


class MemoryKnowledgeStore:
    """``store()`` opens a unit of work on a copy of the tables; a clean exit publishes it."""

    def __init__(self) -> None:
        self._tables = _Tables()
        self._lock = threading.Lock()

    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[KnowledgeUnitOfWork]:
        with self._lock:
            working = self._tables.copy()
            yield MemoryUnitOfWork(working)
            self._tables = working

    def ping(self) -> bool:
        return True
