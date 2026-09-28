"""Migration 0004 on Postgres: documents, clauses and citations, their checks and triggers, the
foreign keys it gives the knowledge tables, and the guard on non-empty tables. Needs Docker."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.documents import clause_id_for, document_id_for
from rulebook.infrastructure.models import (
    Base,
    CanonicalEntityRow,
    CitationRow,
    ClauseEntityRow,
    ClauseRow,
    DocumentRow,
    RuleRelationRow,
    RuleRow,
    RuleVersionRow,
)

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
FETCHED = datetime(2026, 9, 28, tzinfo=UTC)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def alembic_config(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        config = Config(str(SERVICE_DIR / "alembic.ini"))
        command.upgrade(config, "head")
        yield config


@pytest.fixture(scope="module")
def engine(alembic_config: Config, database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


def _insert(engine: Engine, *rows: Base) -> None:
    """Insert in the given order (the models declare no relationships to sort by)."""
    with Session(engine, expire_on_commit=False) as session, session.begin():
        for row in rows:
            session.add(row)
            session.flush()


def _execute(engine: Engine, statement: str, **params: object) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement), params)


def _document(content: bytes | None = None, /, **overrides: object) -> DocumentRow:
    digest = hashlib.sha256(content or uuid4().bytes).hexdigest()
    values: dict[str, object] = {
        "id": document_id_for(digest).value,
        "source_id": uuid4(),
        "sha256": digest,
        "regulator": "CBIC",
        "doc_type": "notification",
        "url": "https://example.invalid/doc.pdf",
        "language": "en",
        "media_type": "application/pdf",
        "parser_version": "pdf@1",
        "fetched_at": FETCHED,
    }
    values.update(overrides)
    return DocumentRow(**values)


def _clause(
    document: DocumentRow, ref: str = "en.p1", ordinal: int = 1, /, **overrides: object
) -> ClauseRow:
    values: dict[str, object] = {
        "id": clause_id_for(document_id_for(document.sha256), ref).value,
        "document_id": document.id,
        "clause_ref": ref,
        "ordinal": ordinal,
        "text": f"clause {ref}",
        "text_sha256": hashlib.sha256(ref.encode()).hexdigest(),
        "page": 1,
    }
    values.update(overrides)
    return ClauseRow(**values)


def _rule_version(engine: Engine) -> UUID:
    rule_id, version_id = uuid4(), uuid4()
    _insert(
        engine,
        RuleRow(id=rule_id, rule_key=f"r_{rule_id.hex[:8]}", regulator="CBIC", level="entity"),
    )
    _insert(
        engine,
        RuleVersionRow(
            id=version_id,
            rule_id=rule_id,
            version=1,
            status="draft",
            title="t",
            specification={},
            obligation_template={},
            effective_from=date(2026, 4, 1),
        ),
    )
    return version_id


def test_a_document_and_its_clauses_are_stored(engine: Engine) -> None:
    document = _document()
    _insert(engine, document)
    _insert(engine, _clause(document), _clause(document, "en.p2", 2), _clause(document, "p3", 3))
    with engine.connect() as connection:
        refs: list[str] = list(
            connection.execute(
                text("SELECT clause_ref FROM clause WHERE document_id = :id ORDER BY ordinal"),
                {"id": document.id},
            )
            .scalars()
            .all()
        )
    assert refs == ["en.p1", "en.p2", "p3"]


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"id": UUID(int=1)}, "ck_document_id_from_sha256"),
        ({"parser_version": "pdf"}, "ck_document_parser_version"),
        ({"doc_type": "gazette"}, "ck_document_doc_type"),
    ],
)
def test_document_checks(engine: Engine, overrides: dict[str, object], constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        _insert(engine, _document(**overrides))


def test_a_malformed_digest_is_refused(engine: Engine) -> None:
    short = hashlib.sha256(b"short").hexdigest()[:63]
    with pytest.raises(IntegrityError, match="ck_document_sha256"):
        _insert(engine, _document(sha256=short, id=UUID(short[:32])))


def test_the_same_bytes_are_one_document(engine: Engine) -> None:
    _insert(engine, _document(b"same bytes"))
    with pytest.raises(IntegrityError, match=r"pk_document|uq_document_sha256"):
        _insert(engine, _document(b"same bytes"))


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"clause_ref": "section 1"}, "ck_clause_clause_ref"),
        ({"clause_ref": "en.p0"}, "ck_clause_clause_ref"),
        ({"ordinal": 0}, "ck_clause_ordinal"),
        ({"page": 0}, "ck_clause_page"),
        ({"text": ""}, "ck_clause_text"),
    ],
)
def test_clause_checks(engine: Engine, overrides: dict[str, object], constraint: str) -> None:
    document = _document()
    _insert(engine, document)
    with pytest.raises(IntegrityError, match=constraint):
        _insert(engine, _clause(document, **overrides))


def test_clause_refs_and_ordinals_are_unique_per_document(engine: Engine) -> None:
    document = _document()
    _insert(engine, document, _clause(document))
    with pytest.raises(IntegrityError, match="uq_clause_document_id_clause_ref"):
        _insert(engine, _clause(document, id=uuid4(), ordinal=2))
    with pytest.raises(IntegrityError, match="uq_clause_document_id_ordinal"):
        _insert(engine, _clause(document, "en.p2", 1))


def test_a_clause_needs_its_document(engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="fk_clause_document_id_document"):
        _insert(engine, _clause(_document()))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE document SET title = 'changed' WHERE id = :id",
        "DELETE FROM document WHERE id = :id",
        "UPDATE clause SET text = 'changed' WHERE document_id = :id",
        "DELETE FROM clause WHERE document_id = :id",
    ],
)
def test_documents_and_clauses_are_append_only(engine: Engine, statement: str) -> None:
    document = _document()
    _insert(engine, document, _clause(document))
    with pytest.raises((IntegrityError, InternalError, ProgrammingError), match="append-only"):
        _execute(engine, statement, id=document.id)


def test_mentions_and_relations_must_point_at_stored_rows(engine: Engine) -> None:
    entity = CanonicalEntityRow(id=uuid4(), type="form", canonical_name=f"F{uuid4().hex[:6]}")
    _insert(engine, entity)
    with pytest.raises(IntegrityError, match="fk_clause_entity_clause_id_clause"):
        _insert(
            engine,
            ClauseEntityRow(
                clause_id=uuid4(), entity_id=entity.id, mention_text="F", span_start=0, span_end=1
            ),
        )
    document = _document()
    _insert(engine, document, _clause(document))
    clause_id = clause_id_for(document_id_for(document.sha256), "en.p1").value
    with pytest.raises(IntegrityError, match="fk_rule_relation_from_rule_version_id_rule_version"):
        _insert(
            engine,
            RuleRelationRow(
                id=uuid4(),
                from_rule_version_id=uuid4(),
                relation="refers_to",
                to_kind="form",
                to_ref=entity.canonical_name,
                to_entity_id=entity.id,
                clause_id=clause_id,
            ),
        )


def test_a_mention_records_how_it_was_found(engine: Engine) -> None:
    document = _document()
    _insert(engine, document, _clause(document))
    clause_id = clause_id_for(document_id_for(document.sha256), "en.p1").value
    entity = CanonicalEntityRow(id=uuid4(), type="form", canonical_name=f"F{uuid4().hex[:6]}")
    _insert(engine, entity)
    _insert(
        engine,
        ClauseEntityRow(
            clause_id=clause_id, entity_id=entity.id, mention_text="c", span_start=0, span_end=1
        ),
    )
    with engine.connect() as connection:
        method, extractor = connection.execute(
            text("SELECT method, extractor FROM clause_entity WHERE entity_id = :id"),
            {"id": entity.id},
        ).one()
    assert (method, extractor) == ("grammar", "")
    with pytest.raises(IntegrityError, match="ck_clause_entity_method"):
        _insert(
            engine,
            ClauseEntityRow(
                clause_id=clause_id,
                entity_id=entity.id,
                mention_text="c",
                span_start=2,
                span_end=3,
                method="guess",
            ),
        )


def test_a_rule_version_target_is_named_in_to_rule_version_id(engine: Engine) -> None:
    document = _document()
    _insert(engine, document, _clause(document))
    clause_id = clause_id_for(document_id_for(document.sha256), "en.p1").value
    source, target = _rule_version(engine), _rule_version(engine)
    with pytest.raises(IntegrityError, match="ck_rule_relation_target_version"):
        _insert(
            engine,
            RuleRelationRow(
                id=uuid4(),
                from_rule_version_id=source,
                relation="supersedes",
                to_kind="rule_version",
                to_ref=str(target),
                clause_id=clause_id,
            ),
        )
    with pytest.raises(IntegrityError, match="ck_rule_relation_target_version"):
        _insert(
            engine,
            RuleRelationRow(
                id=uuid4(),
                from_rule_version_id=source,
                relation="supersedes",
                to_kind="rule_version",
                to_ref=str(uuid4()),
                to_rule_version_id=target,
                clause_id=clause_id,
            ),
        )
    _insert(
        engine,
        RuleRelationRow(
            id=uuid4(),
            from_rule_version_id=source,
            relation="supersedes",
            to_kind="rule_version",
            to_ref=str(target),
            to_rule_version_id=target,
            clause_id=clause_id,
        ),
    )


def _citation(engine: Engine) -> CitationRow:
    document = _document()
    _insert(engine, document, _clause(document))
    citation = CitationRow(
        id=uuid4(),
        rule_version_id=_rule_version(engine),
        clause_id=clause_id_for(document_id_for(document.sha256), "en.p1").value,
        quote="clause en.p1",
    )
    _insert(engine, citation)
    return citation


def test_a_citation_is_verified_once_with_a_passing_score(engine: Engine) -> None:
    citation = _citation(engine)
    _execute(
        engine,
        "UPDATE citation SET verified = true, match_score = 0.9, verified_at = now()"
        " WHERE id = :id",
        id=citation.id,
    )
    with pytest.raises((IntegrityError, InternalError, ProgrammingError), match="one-way"):
        _execute(
            engine,
            "UPDATE citation SET verified = false, verified_at = NULL WHERE id = :id",
            id=citation.id,
        )
    with pytest.raises((IntegrityError, InternalError, ProgrammingError), match="immutable"):
        _execute(engine, "UPDATE citation SET quote = 'other' WHERE id = :id", id=citation.id)
    with pytest.raises((IntegrityError, InternalError, ProgrammingError), match="append-only"):
        _execute(engine, "DELETE FROM citation WHERE id = :id", id=citation.id)


@pytest.mark.parametrize(
    "assignment",
    [
        "verified = true, verified_at = now()",
        "verified = true, match_score = 0.5, verified_at = now()",
        "verified = true, match_score = 0.9",
        "match_score = 1.5",
    ],
)
def test_citation_verification_checks(engine: Engine, assignment: str) -> None:
    citation = _citation(engine)
    with pytest.raises(IntegrityError, match="ck_citation"):
        _execute(engine, f"UPDATE citation SET {assignment} WHERE id = :id", id=citation.id)


def test_upgrade_refuses_to_add_foreign_keys_over_existing_rows(
    alembic_config: Config, engine: Engine
) -> None:
    command.downgrade(alembic_config, "0003")
    _execute(engine, "DELETE FROM rule_relation")
    _execute(engine, "DELETE FROM clause_entity")
    entity_id = uuid4()
    _execute(
        engine,
        "INSERT INTO canonical_entity (id, type, canonical_name) VALUES (:id, 'form', 'GSTR-9')",
        id=entity_id,
    )
    _execute(
        engine,
        "INSERT INTO clause_entity (clause_id, entity_id, mention_text, span_start, span_end)"
        " VALUES (:clause, :entity, 'GSTR-9', 0, 6)",
        clause=uuid4(),
        entity=entity_id,
    )
    with pytest.raises(RuntimeError, match="expects both empty; found 1 rows"):
        command.upgrade(alembic_config, "head")
    _execute(engine, "DELETE FROM clause_entity")
    command.upgrade(alembic_config, "head")
    with engine.connect() as connection:
        version: str = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert version == "0006"
