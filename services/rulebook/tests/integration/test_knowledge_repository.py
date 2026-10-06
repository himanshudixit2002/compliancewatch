"""The document use cases on the Postgres unit of work: registration is idempotent, a different
parse is refused and leaves the stored clauses alone, reads return clauses in order."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import SourceId
from rulebook.application.documents import ReadDocument, RegisterDocument
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import DocumentConflictError, UnknownDocumentError
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
CONTENT = b"%PDF-1.7 recorded notification bytes"
DIGEST = hashlib.sha256(CONTENT).hexdigest()
CLAUSES = (
    Clause("en.p1", "Notification No. 01/2026 \u2013 Central Tax", page=1),
    Clause("en.p2", "sub -section (6) of section 39", page=1),
    Clause("hi.p1", "अधिसूचना", page=2),
)


@pytest.fixture(scope="module")
def factory() -> Iterator[PostgresKnowledgeUnitOfWorkFactory]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        factory = PostgresKnowledgeUnitOfWorkFactory.from_url(url)
        yield factory
        factory.engine.dispose()


def _document(**overrides: object) -> StoredDocument:
    values: dict[str, object] = {
        "document_id": document_id_for(DIGEST),
        "source_id": SourceId(UUID(int=3)),
        "sha256": DIGEST,
        "regulator": "CBIC",
        "doc_type": DocumentType.NOTIFICATION,
        "url": "https://example.invalid/n.pdf",
        "language": "en",
        "media_type": "application/pdf",
        "parser_version": "pdf@1",
        "fetched_at": datetime(2026, 9, 28, 6, tzinfo=UTC),
        "published_at": date(2026, 1, 16),
        "title": "Notification No. 01/2026",
    }
    values.update(overrides)
    return StoredDocument(**values)  # type: ignore[arg-type]


def test_register_read_and_register_again(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    assert factory.ping() is True
    first = RegisterDocument(factory).run(_document(), CLAUSES)
    assert first.created is True
    doc_id = document_id_for(DIGEST)
    assert first.clause_ids["hi.p1"] == clause_id_for(doc_id, "hi.p1")

    stored, clauses = ReadDocument(factory).run(doc_id)
    assert stored == _document()
    assert [c.as_clause() for c in clauses] == list(CLAUSES)
    assert [c.ordinal for c in clauses] == [1, 2, 3]

    again = RegisterDocument(factory).run(_document(title="Other"), CLAUSES)
    assert again.created is False
    assert again.clause_ids == first.clause_ids
    assert again.metadata_differs == ("title",)


def test_a_different_parse_is_refused_and_changes_nothing(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    RegisterDocument(factory).run(_document(), CLAUSES)
    with pytest.raises(DocumentConflictError):
        RegisterDocument(factory).run(_document(), (*CLAUSES, Clause("en.p3", "extra")))
    kept = RegisterDocument(factory).run(
        _document(parser_version="pdf@2"), (*CLAUSES, Clause("en.p3", "extra"))
    )
    assert (kept.created, kept.parser_version) == (False, "pdf@1")
    _, clauses = ReadDocument(factory).run(document_id_for(DIGEST))
    assert len(clauses) == len(CLAUSES)


def test_a_statute_is_stored(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    digest = hashlib.sha256(b"Example Act, 2000").hexdigest()
    statute = _document(
        sha256=digest,
        document_id=document_id_for(digest),
        doc_type=DocumentType.STATUTE,
        parser_version="manual@1",
    )
    assert RegisterDocument(factory).run(statute, CLAUSES).created is True
    stored, _ = ReadDocument(factory).run(document_id_for(digest))
    assert stored.doc_type is DocumentType.STATUTE


def test_an_unknown_document_is_reported(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    with pytest.raises(UnknownDocumentError):
        ReadDocument(factory).run(document_id_for("0" * 64))
