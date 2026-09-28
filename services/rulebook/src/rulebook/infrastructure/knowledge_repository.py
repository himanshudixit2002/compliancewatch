"""The Postgres unit of work for regulator documents and the knowledge tables.

Inserts use ``ON CONFLICT DO NOTHING``: documents and clauses are append-only and keyed by ids
every writer derives the same way, so a repeated insert is a no-op rather than an error.
"""

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import Self

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.documents import DocumentType
from domain_kernel.ids import ClauseId, DocumentId, SourceId
from rulebook.domain.documents import StoredClause, StoredDocument
from rulebook.domain.repository import KnowledgeUnitOfWork
from rulebook.infrastructure.models import ClauseRow, DocumentRow


class SqlAlchemyDocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, document_id: DocumentId) -> StoredDocument | None:
        row = self._session.get(DocumentRow, document_id.value)
        return None if row is None else _to_document(row)

    def add(self, document: StoredDocument) -> bool:
        statement = (
            insert(DocumentRow)
            .values(_document_values(document))
            .on_conflict_do_nothing()
            .returning(DocumentRow.id)
        )
        return self._session.execute(statement).first() is not None

    def clauses(self, document_id: DocumentId) -> tuple[StoredClause, ...]:
        statement = (
            select(ClauseRow)
            .where(ClauseRow.document_id == document_id.value)
            .order_by(ClauseRow.ordinal)
        )
        return tuple(_to_clause(row) for row in self._session.scalars(statement))

    def add_clauses(self, clauses: Sequence[StoredClause]) -> None:
        if not clauses:
            return
        values = [
            {
                "id": clause.clause_id.value,
                "document_id": clause.document_id.value,
                "clause_ref": clause.clause_ref,
                "ordinal": clause.ordinal,
                "text": clause.text,
                "text_sha256": clause.text_sha256,
                "page": clause.page,
            }
            for clause in clauses
        ]
        self._session.execute(insert(ClauseRow).values(values).on_conflict_do_nothing())


class SqlAlchemyKnowledgeUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._documents = SqlAlchemyDocumentRepository(session)

    @property
    def documents(self) -> SqlAlchemyDocumentRepository:
        return self._documents


class PostgresKnowledgeUnitOfWorkFactory:
    """``factory()`` opens one transaction; the block's clean exit commits it."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> Self:
        return cls(create_engine(database_url, poolclass=NullPool))

    @property
    def engine(self) -> Engine:
        return self._engine

    def __call__(self) -> AbstractContextManager[KnowledgeUnitOfWork]:
        return self._open()

    @contextmanager
    def _open(self) -> Iterator[KnowledgeUnitOfWork]:
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            yield SqlAlchemyKnowledgeUnitOfWork(session)

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


def _document_values(document: StoredDocument) -> dict[str, object]:
    return {
        "id": document.document_id.value,
        "source_id": document.source_id.value,
        "sha256": document.sha256,
        "regulator": document.regulator,
        "doc_type": document.doc_type.value,
        "external_ref": document.external_ref,
        "url": document.url,
        "title": document.title,
        "language": document.language,
        "media_type": document.media_type,
        "parser_version": document.parser_version,
        "published_at": document.published_at,
        "fetched_at": document.fetched_at,
        "raw_uri": document.raw_uri,
    }


def _to_document(row: DocumentRow) -> StoredDocument:
    return StoredDocument(
        document_id=DocumentId(row.id),
        source_id=SourceId(row.source_id),
        sha256=row.sha256,
        regulator=row.regulator,
        doc_type=DocumentType(row.doc_type),
        url=row.url,
        language=row.language,
        media_type=row.media_type,
        parser_version=row.parser_version,
        fetched_at=row.fetched_at,
        external_ref=row.external_ref,
        title=row.title,
        published_at=row.published_at,
        raw_uri=row.raw_uri,
    )


def _to_clause(row: ClauseRow) -> StoredClause:
    return StoredClause(
        clause_id=ClauseId(row.id),
        document_id=DocumentId(row.document_id),
        clause_ref=row.clause_ref,
        ordinal=row.ordinal,
        text=row.text,
        text_sha256=row.text_sha256,
        page=row.page,
    )
