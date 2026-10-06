"""The clause search index on Postgres: migration 0006, the generated full-text column, the
vector column and its HNSW index, and both search legs with their filters. Needs Docker."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import ClauseId, DocumentId, SourceId
from domain_kernel.knowledge import EntityType
from domain_kernel.vectors import EMBEDDING_DIMS, ClauseFilter
from rulebook.application.documents import RegisterDocument
from rulebook.application.graph import ListEntityClauses
from rulebook.application.search import ListUnembeddedClauses, SearchClauses, StoreEmbeddings
from rulebook.domain.documents import StoredDocument
from rulebook.domain.search import ClauseEmbedding, SearchQuery
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.models import ClauseEmbeddingRow, ClauseRow

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
INSERT_GUARD = "tr_rule_version_insert_guard"
"""Admits only unpublished drafts. The fixture below inserts versions in any status, so it turns
the guard off for its own transaction; ``ALTER TABLE`` is transactional, so the guard is back on
for everyone else when that transaction commits."""
NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
MODEL = "fake/hash-ngram-512"
EXTENSION = "The due dates for furnishing the returns in FORM GSTR-3B are extended"
MONTHLY = "Every registered person shall furnish a return in FORM GSTR-3B for each month"
RATES = "The rate of tax on the supply of goods is revised"
HINDI = (
    "\u0905\u0927\u093f\u0938\u0942\u091a\u0928\u093e "
    "\u0915\u0947\u0902\u0926\u094d\u0930\u0940\u092f \u0915\u0930"
)
"""Three Hindi words: "notification", "central", "tax"."""


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
def factory(
    database_url: str, alembic_config: Config
) -> Iterator[PostgresKnowledgeUnitOfWorkFactory]:
    factory = PostgresKnowledgeUnitOfWorkFactory.from_url(database_url)
    yield factory
    factory.engine.dispose()


def register(
    factory: PostgresKnowledgeUnitOfWorkFactory,
    name: str,
    published_at: date | None,
    *texts: str,
    regulator: str = "CBIC",
    doc_type: DocumentType = DocumentType.NOTIFICATION,
) -> DocumentId:
    digest = hashlib.sha256(name.encode()).hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(factory).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator=regulator,
            doc_type=doc_type,
            url=f"https://example.invalid/{name}.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=NOW,
            published_at=published_at,
        ),
        [Clause(f"en.p{index}", clause) for index, clause in enumerate(texts, 1)],
    )
    return document_id


def vector(*weights: tuple[int, float]) -> tuple[float, ...]:
    values = [0.0] * EMBEDDING_DIMS
    for index, weight in weights:
        values[index] = weight
    return tuple(values)


def search_vector(factory: PostgresKnowledgeUnitOfWorkFactory, clause_id: ClauseId) -> str:
    with factory.engine.connect() as connection:
        found: str = connection.execute(
            text("SELECT search_vector::text FROM clause WHERE id = :id"), {"id": clause_id.value}
        ).scalar_one()
    return found


def test_the_migration_fills_existing_clauses_and_goes_down_and_up(
    alembic_config: Config, factory: PostgresKnowledgeUnitOfWorkFactory
) -> None:
    command.downgrade(alembic_config, "0005")
    columns = {c["name"] for c in inspect(factory.engine).get_columns("clause", schema=SCHEMA)}
    assert "search_vector" not in columns
    assert "clause_embedding" not in inspect(factory.engine).get_table_names(schema=SCHEMA)
    document = register(factory, "before 0006", date(2026, 3, 28), EXTENSION)

    command.upgrade(alembic_config, "head")
    assert "'extend'" in search_vector(factory, clause_id_for(document, "en.p1"))
    with factory.engine.connect() as connection:
        version: str = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        extension: str = connection.execute(
            text(
                "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n"
                " ON n.oid = e.extnamespace WHERE e.extname = 'vector'"
            )
        ).scalar_one()
    assert (version, extension) == ("0010", "public")

    command.downgrade(alembic_config, "0005")
    command.upgrade(alembic_config, "head")
    assert "'extend'" in search_vector(factory, clause_id_for(document, "en.p1"))


def test_english_words_are_stemmed_and_devanagari_is_kept(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    document = register(factory, "stemming", date(2026, 3, 28), EXTENSION, HINDI)
    english = search_vector(factory, clause_id_for(document, "en.p1"))
    for lexeme in ("'due'", "'date'", "'extend'", "'furnish'", "'return'", "'gstr-3b'"):
        assert lexeme in english
    assert "'the'" not in english
    hindi = search_vector(factory, clause_id_for(document, "en.p2"))
    for word in HINDI.split():
        assert f"'{word}'" in hindi

    search = SearchClauses(factory)
    stemmed = search.run(SearchQuery("extending the due date"))
    assert clause_id_for(document, "en.p1") in [hit.detail.clause.clause_id for hit in stemmed]
    (devanagari,) = search.run(SearchQuery(HINDI.split()[1]))
    assert devanagari.detail.clause.clause_id == clause_id_for(document, "en.p2")
    assert search.run(SearchQuery("the of and")) == []


def test_vectors_round_trip_and_are_never_updated(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    document = register(factory, "round trip", date(2026, 3, 28), RATES)
    clause_id = clause_id_for(document, "en.p1")
    stored = vector((0, 0.5), (7, -0.25), (511, 0.125))
    report = StoreEmbeddings(factory).run(
        MODEL, EMBEDDING_DIMS, [ClauseEmbedding(clause_id, stored)]
    )
    assert (report.stored, report.unchanged) == (1, 0)
    again = StoreEmbeddings(factory).run(
        MODEL, EMBEDDING_DIMS, [ClauseEmbedding(clause_id, vector((1, 1.0)))]
    )
    assert (again.stored, again.unchanged) == (0, 1)
    with Session(factory.engine) as session:
        row = session.get(ClauseEmbeddingRow, (clause_id.value, MODEL))
        assert row is not None
        assert row.embedding == stored
        assert row.created_at.tzinfo is not None
        loaded = session.get(ClauseRow, clause_id.value)
        assert loaded is not None
        assert "search_vector" not in loaded.__dict__

    with pytest.raises(DBAPIError, match="append-only"), factory.engine.begin() as connection:
        connection.execute(
            text("UPDATE clause_embedding SET model = 'other/model' WHERE clause_id = :id"),
            {"id": clause_id.value},
        )
    with factory.engine.begin() as connection:
        deleted = connection.execute(
            text("DELETE FROM clause_embedding WHERE clause_id = :id"), {"id": clause_id.value}
        )
    assert deleted.rowcount == 1
    with pytest.raises(DBAPIError, match="512 dimensions"), factory.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO clause_embedding (clause_id, model, embedding)"
                " VALUES (:id, 'short/model', '[1,2,3]')"
            ),
            {"id": clause_id.value},
        )


def test_nearest_follows_cosine_distance_over_the_hnsw_index(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    document = register(factory, "hnsw", date(2026, 3, 28), "alpha", "beta", "gamma", "delta")
    clauses = [clause_id_for(document, f"en.p{n}") for n in range(1, 5)]
    vectors = [
        vector((0, 1.0)),
        vector((0, 0.8), (1, 0.6)),
        vector((0, 0.3), (1, 0.95)),
        vector((1, 1.0)),
    ]
    StoreEmbeddings(factory).run(
        "hnsw/model",
        EMBEDDING_DIMS,
        [ClauseEmbedding(c, v) for c, v in zip(clauses, vectors, strict=True)],
    )
    with factory() as uow:
        assert (
            list(uow.index.nearest(vector((0, 1.0)), "hnsw/model", ClauseFilter(), 10)) == clauses
        )
        assert list(uow.index.nearest(vector((1, 1.0)), "hnsw/model", ClauseFilter(), 2)) == [
            clauses[3],
            clauses[2],
        ]
        assert uow.index.nearest(vector((0, 1.0)), "no/model", ClauseFilter(), 10) == []

    with factory.engine.begin() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            connection.execute(
                text(
                    "EXPLAIN SELECT clause_id FROM clause_embedding"
                    " ORDER BY embedding <=> CAST(:v AS vector(512)) LIMIT 5"
                ),
                {"v": "[" + ",".join(str(x) for x in vector((0, 1.0))) + "]"},
            ).scalars()
        )
        # pgvector defines its settings once its library is loaded, which the plan above does;
        # nearest() relies on the iterative scan that pgvector 0.8 added.
        allowed: list[str] = connection.execute(
            text("SELECT enumvals FROM pg_settings WHERE name = 'hnsw.iterative_scan'")
        ).scalar_one()
    assert "ix_clause_embedding_hnsw" in plan
    assert "relaxed_order" in allowed


def test_both_legs_honour_the_filters(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    text_ = "Filing dates for the quarterly statement are extended"
    dated = register(factory, "filters dated", date(2026, 3, 28), text_)
    undated = register(factory, "filters undated", None, text_ + " again")
    state = register(
        factory, "filters state", date(2026, 1, 5), text_ + " here", regulator="KA-CTD"
    )
    circular = register(
        factory,
        "filters circular",
        date(2026, 2, 1),
        text_ + " by circular",
        doc_type=DocumentType.CIRCULAR,
    )
    documents = (dated, undated, state, circular)
    StoreEmbeddings(factory).run(
        "filters/model",
        EMBEDDING_DIMS,
        [ClauseEmbedding(clause_id_for(d, "en.p1"), vector((5, 1.0))) for d in documents],
    )

    def found(filters: ClauseFilter) -> tuple[set[DocumentId], set[DocumentId]]:
        with factory() as uow:
            lexical = uow.index.lexical("quarterly statement filing", filters, 40)
            nearest = uow.index.nearest(vector((5, 1.0)), "filters/model", filters, 40)
            hits = uow.index.hits([*lexical, *nearest], None)
        return (
            {hits[c].detail.document.document_id for c in lexical},
            {hits[c].detail.document.document_id for c in nearest},
        )

    everything = set(documents)
    assert found(ClauseFilter()) == (everything, everything)
    assert found(ClauseFilter(regulator="KA-CTD")) == ({state}, {state})
    circulars = ClauseFilter(doc_types=frozenset({DocumentType.CIRCULAR}))
    assert found(circulars) == ({circular}, {circular})
    assert found(ClauseFilter(as_of=date(2026, 2, 1))) == ({state, circular}, {state, circular})

    hits = SearchClauses(factory).run(
        SearchQuery(
            "quarterly statement filing",
            ClauseFilter(regulator="CBIC", as_of=date(2026, 3, 28)),
            vector=vector((5, 1.0)),
            model="filters/model",
        )
    )
    assert {hit.detail.document.document_id for hit in hits} == {dated, circular}
    assert all(hit.lexical_rank and hit.vector_rank for hit in hits)


def test_hits_carry_the_citing_versions_in_force(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    document = register(factory, "cited", date(2026, 3, 28), MONTHLY)
    clause_id = clause_id_for(document, "en.p1")
    rule_id = uuid4()
    old, new, draft = uuid4(), uuid4(), uuid4()
    with factory.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO rule (id, rule_key, regulator, level)"
                " VALUES (:id, 'search_cited', 'CBIC', 'registration')"
            ),
            {"id": rule_id},
        )
        connection.execute(text(f"ALTER TABLE rule_version DISABLE TRIGGER {INSERT_GUARD}"))
        for version_id, number, status, start, end in (
            (old, 1, "superseded", date(2026, 4, 1), date(2026, 7, 1)),
            (new, 2, "published", date(2026, 7, 1), None),
            (draft, 3, "draft", date(2026, 10, 1), None),
        ):
            connection.execute(
                text(
                    "INSERT INTO rule_version (id, rule_id, version, status, title,"
                    " specification, obligation_template, effective_from, effective_to)"
                    " VALUES (:id, :rule, :number, :status, 't', '{}', '{}', :start, :end)"
                ),
                {
                    "id": version_id,
                    "rule": rule_id,
                    "number": number,
                    "status": status,
                    "start": start,
                    "end": end,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO citation (id, rule_version_id, clause_id, quote, verified,"
                    " match_score, verified_at) VALUES (:id, :version, :clause, 'furnish a return',"
                    " true, 1.0, :now)"
                ),
                {"id": uuid4(), "version": version_id, "clause": clause_id.value, "now": NOW},
            )
        connection.execute(text(f"ALTER TABLE rule_version ENABLE TRIGGER {INSERT_GUARD}"))
    with factory() as uow:
        anytime = uow.index.hits([clause_id], None)[clause_id]
        june = uow.index.hits([clause_id], date(2026, 6, 1))[clause_id]
        july = uow.index.hits([clause_id], date(2026, 7, 1))[clause_id]
        assert uow.index.hits([], None) == {}
    assert {v.value for v in anytime.cited_by} == {old, new}
    assert [v.value for v in june.cited_by] == [old]
    assert [v.value for v in july.cited_by] == [new]
    assert anytime.detail.clause.text == MONTHLY
    assert (anytime.out_of_force, june.out_of_force, july.out_of_force) == (False, False, False)


def test_a_superseded_notifications_clause_is_out_of_force_after_its_replacement(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    document = register(factory, "superseded", date(2026, 3, 28), MONTHLY, EXTENSION, RATES)
    monthly, extension, rates = (clause_id_for(document, f"en.p{n}") for n in (1, 2, 3))
    old, withdrawn, draft = uuid4(), uuid4(), uuid4()
    with factory.engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE rule_version DISABLE TRIGGER {INSERT_GUARD}"))
        for version_id, key, status, end, clause in (
            (old, "oof_monthly", "superseded", date(2026, 7, 1), monthly),
            (withdrawn, "oof_extension", "withdrawn", None, extension),
            (draft, "oof_draft", "draft", None, rates),
        ):
            rule_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO rule (id, rule_key, regulator, level)"
                    " VALUES (:id, :key, 'CBIC', 'registration')"
                ),
                {"id": rule_id, "key": key},
            )
            connection.execute(
                text(
                    "INSERT INTO rule_version (id, rule_id, version, status, title,"
                    " specification, obligation_template, effective_from, effective_to)"
                    " VALUES (:id, :rule, 1, :status, 't', '{}', '{}', DATE '2026-04-01', :end)"
                ),
                {"id": version_id, "rule": rule_id, "status": status, "end": end},
            )
            connection.execute(
                text(
                    "INSERT INTO citation (id, rule_version_id, clause_id, quote, verified,"
                    " match_score, verified_at) VALUES (:id, :version, :clause, 'a return',"
                    " true, 1.0, :now)"
                ),
                {"id": uuid4(), "version": version_id, "clause": clause.value, "now": NOW},
            )
        connection.execute(text(f"ALTER TABLE rule_version ENABLE TRIGGER {INSERT_GUARD}"))
    ids = [monthly, extension, rates]

    def flags(as_of: date | None) -> list[bool]:
        with factory() as uow:
            found = uow.index.hits(ids, as_of)
        return [found[clause_id].out_of_force for clause_id in ids]

    assert flags(date(2026, 6, 1)) == [False, True, False]
    assert flags(date(2026, 8, 1)) == [True, True, False]
    assert flags(None) == [False, False, False]
    with factory() as uow:
        form, _ = uow.entities.create_or_get(EntityType.FORM, "GSTR-3B")
        start = MONTHLY.index("FORM GSTR-3B")
        uow.mentions.add(
            monthly, form, "FORM GSTR-3B", start, start + 12, method="grammar", extractor="g@1"
        )
    assert [c.out_of_force for c in ListEntityClauses(factory).run(form, date(2026, 6, 1))] == [
        False
    ]
    assert [c.out_of_force for c in ListEntityClauses(factory).run(form, date(2026, 8, 1))] == [
        True
    ]


def test_unembedded_clauses_by_model(factory: PostgresKnowledgeUnitOfWorkFactory) -> None:
    document = register(factory, "unembedded", date(2026, 3, 28), "one", "two", "three")
    clauses = sorted(
        (clause_id_for(document, f"en.p{n}") for n in (1, 2, 3)), key=lambda c: c.value
    )
    StoreEmbeddings(factory).run(
        "unembedded/model", EMBEDDING_DIMS, [ClauseEmbedding(clauses[0], vector((0, 1.0)))]
    )
    listed = ListUnembeddedClauses(factory)
    mine = listed.run("unembedded/model", document_id=document)
    assert [d.clause.clause_id for d in mine] == clauses[1:]
    paged = listed.run("unembedded/model", document_id=document, limit=1, after=clauses[1])
    assert [d.clause.clause_id for d in paged] == [clauses[2]]
    assert len(listed.run("unembedded/other", document_id=document)) == 3
    with factory() as uow:
        assert uow.index.unknown_clauses([clauses[0], ClauseId(UUID(int=1))]) == {
            ClauseId(UUID(int=1))
        }
    with Session(factory.engine) as session:
        assert (
            session.scalar(
                select(ClauseEmbeddingRow.model).where(
                    ClauseEmbeddingRow.clause_id == clauses[0].value
                )
            )
            == "unembedded/model"
        )
