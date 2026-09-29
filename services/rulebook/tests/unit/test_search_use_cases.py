"""Storing clause embeddings, listing the clauses to embed, and hybrid search on the memory
store."""

import hashlib
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId, SourceId
from domain_kernel.status import RuleVersionStatus
from domain_kernel.vectors import EMBEDDING_DIMS, ClauseFilter
from rulebook.application.documents import RegisterDocument
from rulebook.application.search import ListUnembeddedClauses, SearchClauses, StoreEmbeddings
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import EmbeddingDimensionError, UnknownClauseError
from rulebook.domain.search import ClauseEmbedding, SearchQuery
from rulebook.infrastructure.memory import MemoryKnowledgeStore

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
MODEL = "fake/hash-ngram-512"
EXTENSION = "The due date for furnishing the return in FORM GSTR-3B is extended"
MONTHLY = "Every registered person shall furnish a return in FORM GSTR-3B for each month"
RATES = "The rate of tax on the supply of goods is revised"
HINDI = "\u0905\u0927\u093f\u0938\u0942\u091a\u0928\u093e \u0938\u0902\u0916\u094d\u092f\u093e"


def register(
    store: MemoryKnowledgeStore,
    name: str,
    published_at: date | None,
    *texts: str,
    regulator: str = "CBIC",
    doc_type: DocumentType = DocumentType.NOTIFICATION,
) -> DocumentId:
    digest = hashlib.sha256(name.encode()).hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
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
        [Clause(f"en.p{index}", text) for index, text in enumerate(texts, 1)],
    )
    return document_id


def unit(*weights: tuple[int, float]) -> tuple[float, ...]:
    vector = [0.0] * EMBEDDING_DIMS
    for index, weight in weights:
        vector[index] = weight
    return tuple(vector)


@pytest.fixture
def store() -> MemoryKnowledgeStore:
    return MemoryKnowledgeStore()


def test_embeddings_are_stored_once_per_model(store: MemoryKnowledgeStore) -> None:
    document = register(store, "n1", date(2026, 3, 28), EXTENSION, MONTHLY)
    p1, p2 = clause_id_for(document, "en.p1"), clause_id_for(document, "en.p2")
    store_embeddings = StoreEmbeddings(store)
    first = store_embeddings.run(MODEL, EMBEDDING_DIMS, [ClauseEmbedding(p1, unit((0, 1.0)))])
    assert (first.stored, first.unchanged) == (1, 0)
    again = store_embeddings.run(
        MODEL,
        EMBEDDING_DIMS,
        [ClauseEmbedding(p1, unit((1, 1.0))), ClauseEmbedding(p2, unit((2, 1.0)))],
    )
    assert (again.stored, again.unchanged) == (1, 1)
    other = store_embeddings.run(
        "other/model", EMBEDDING_DIMS, [ClauseEmbedding(p1, unit((3, 1.0)))]
    )
    assert other.stored == 1
    hits = SearchClauses(store).run(SearchQuery("unrelated", vector=unit((0, 1.0)), model=MODEL))
    assert [hit.detail.clause.clause_id for hit in hits][:1] == [p1]


def test_a_batch_is_refused_whole(store: MemoryKnowledgeStore) -> None:
    document = register(store, "n1", date(2026, 3, 28), EXTENSION)
    p1 = clause_id_for(document, "en.p1")
    store_embeddings = StoreEmbeddings(store)
    with pytest.raises(EmbeddingDimensionError):
        store_embeddings.run(MODEL, 1024, [ClauseEmbedding(p1, unit((0, 1.0)))])
    with pytest.raises(UnknownClauseError):
        store_embeddings.run(
            MODEL,
            EMBEDDING_DIMS,
            [
                ClauseEmbedding(p1, unit((0, 1.0))),
                ClauseEmbedding(ClauseId(UUID(int=9)), unit((0, 1.0))),
            ],
        )
    with pytest.raises(InvariantViolationError, match="at most once"):
        store_embeddings.run(MODEL, EMBEDDING_DIMS, [ClauseEmbedding(p1, unit((0, 1.0)))] * 2)
    with pytest.raises(InvariantViolationError):
        store_embeddings.run(MODEL, EMBEDDING_DIMS, [])
    with pytest.raises(InvariantViolationError):
        store_embeddings.run(" ", EMBEDDING_DIMS, [ClauseEmbedding(p1, unit((0, 1.0)))])
    assert len(ListUnembeddedClauses(store).run(MODEL)) == 1


def test_unembedded_clauses_page_by_clause_id(store: MemoryKnowledgeStore) -> None:
    first = register(store, "n1", date(2026, 3, 28), EXTENSION, MONTHLY)
    second = register(store, "n2", None, RATES)
    StoreEmbeddings(store).run(
        MODEL, EMBEDDING_DIMS, [ClauseEmbedding(clause_id_for(first, "en.p1"), unit((0, 1.0)))]
    )
    listed = ListUnembeddedClauses(store)
    everything = [detail.clause.clause_id for detail in listed.run(MODEL)]
    assert everything == sorted(
        [clause_id_for(first, "en.p2"), clause_id_for(second, "en.p1")], key=str
    )
    assert [d.clause.clause_id for d in listed.run(MODEL, document_id=first)] == [
        clause_id_for(first, "en.p2")
    ]
    assert [d.clause.clause_id for d in listed.run(MODEL, limit=1, after=everything[0])] == [
        everything[1]
    ]
    assert len(listed.run("other/model")) == 3


def test_the_lexical_leg_ranks_by_matching_terms(store: MemoryKnowledgeStore) -> None:
    document = register(store, "n1", date(2026, 3, 28), EXTENSION, MONTHLY, RATES, HINDI)
    hits = SearchClauses(store).run(SearchQuery("due date return GSTR-3B"))
    assert [hit.detail.clause.clause_ref for hit in hits] == ["en.p1", "en.p2"]
    assert [(hit.lexical_rank, hit.vector_rank) for hit in hits] == [(1, None), (2, None)]
    assert hits[0].detail.document.document_id == document
    assert SearchClauses(store).run(SearchQuery("the of and")) == []
    (hindi,) = SearchClauses(store).run(SearchQuery(HINDI.split()[0]))
    assert hindi.detail.clause.clause_ref == "en.p4"


def test_both_legs_are_fused(store: MemoryKnowledgeStore) -> None:
    document = register(store, "n1", date(2026, 3, 28), EXTENSION, MONTHLY, RATES)
    p1, p2, p3 = (clause_id_for(document, f"en.p{n}") for n in (1, 2, 3))
    StoreEmbeddings(store).run(
        MODEL,
        EMBEDDING_DIMS,
        [
            ClauseEmbedding(p1, unit((0, 0.6), (1, 0.8))),
            ClauseEmbedding(p2, unit((0, 1.0))),
            ClauseEmbedding(p3, unit((1, 1.0))),
        ],
    )
    hits = SearchClauses(store).run(
        SearchQuery("due return GSTR-3B", vector=unit((1, 1.0)), model=MODEL, k=3)
    )
    ranks = {hit.detail.clause.clause_id: (hit.lexical_rank, hit.vector_rank) for hit in hits}
    assert ranks == {p1: (1, 2), p2: (2, 3), p3: (None, 1)}
    assert hits[0].detail.clause.clause_id == p1
    assert hits[0].score > hits[1].score
    other_model = SearchClauses(store).run(
        SearchQuery("tax", vector=unit((1, 1.0)), model="other/model")
    )
    assert [(hit.lexical_rank, hit.vector_rank) for hit in other_model] == [(1, None)]


def test_filters_apply_to_both_legs(store: MemoryKnowledgeStore) -> None:
    dated = register(store, "dated", date(2026, 3, 28), EXTENSION)
    undated = register(store, "undated", None, EXTENSION + " again")
    state = register(
        store, "state", date(2026, 1, 5), EXTENSION + " by the state", regulator="KA-CTD"
    )
    circular = register(
        store,
        "circular",
        date(2026, 2, 1),
        EXTENSION + " by circular",
        doc_type=DocumentType.CIRCULAR,
    )
    embeddings = [
        ClauseEmbedding(clause_id_for(document, "en.p1"), unit((0, 1.0)))
        for document in (dated, undated, state, circular)
    ]
    StoreEmbeddings(store).run(MODEL, EMBEDDING_DIMS, embeddings)
    search = SearchClauses(store)

    def documents(filters: ClauseFilter) -> set[DocumentId]:
        query = SearchQuery("due date extended", filters, vector=unit((0, 1.0)), model=MODEL)
        return {hit.detail.document.document_id for hit in search.run(query)}

    assert documents(ClauseFilter()) == {dated, undated, state, circular}
    assert documents(ClauseFilter(regulator="KA-CTD")) == {state}
    assert documents(ClauseFilter(doc_types=frozenset({DocumentType.CIRCULAR}))) == {circular}
    assert documents(ClauseFilter(as_of=date(2026, 2, 1))) == {state, circular}
    assert documents(ClauseFilter(as_of=date(2025, 12, 31))) == set()


def test_hits_carry_the_versions_that_cite_them(store: MemoryKnowledgeStore) -> None:
    document = register(store, "n1", date(2026, 3, 28), EXTENSION)
    p1 = clause_id_for(document, "en.p1")
    _, old = store.add_rule(
        "gstr3b_monthly",
        status=RuleVersionStatus.SUPERSEDED,
        effective_from=date(2026, 4, 1),
        effective_to=date(2026, 7, 1),
    )
    new = store.add_version(
        "gstr3b_monthly", status=RuleVersionStatus.PUBLISHED, effective_from=date(2026, 7, 1)
    )
    _, draft = store.add_rule("gstr3b_draft")
    _, unverified = store.add_rule("gstr3b_other", status=RuleVersionStatus.PUBLISHED)
    for version in (old, new, draft):
        store.add_citation(version, p1, "due date")
    store.add_citation(unverified, p1, "due date", verified=False, match_score=None)
    search = SearchClauses(store)
    (anytime,) = search.run(SearchQuery("due date"))
    assert set(anytime.cited_by) == {old, new}
    june = SearchQuery("due date", ClauseFilter(as_of=date(2026, 6, 1)))
    assert search.run(june)[0].cited_by == (old,)
    july = SearchQuery("due date", ClauseFilter(as_of=date(2026, 7, 1)))
    assert search.run(july)[0].cited_by == (new,)


def test_a_superseded_notifications_clause_is_out_of_force_after_its_replacement(
    store: MemoryKnowledgeStore,
) -> None:
    document = register(store, "old notification", date(2026, 3, 28), EXTENSION, MONTHLY, RATES)
    extension, monthly = clause_id_for(document, "en.p1"), clause_id_for(document, "en.p2")
    _, old = store.add_rule(
        "gstr3b_monthly",
        status=RuleVersionStatus.SUPERSEDED,
        effective_from=date(2026, 4, 1),
        effective_to=date(2026, 7, 1),
    )
    _, withdrawn = store.add_rule("gstr3b_extension", status=RuleVersionStatus.WITHDRAWN)
    _, draft = store.add_rule("gstr3b_draft")
    store.add_citation(old, monthly, "furnish a return in FORM GSTR-3B")
    store.add_citation(withdrawn, extension, "The due date for furnishing the return")
    store.add_citation(draft, clause_id_for(document, "en.p3"), "The rate of tax")
    search = SearchClauses(store)

    def flags(as_of: date | None) -> dict[str, bool]:
        query = SearchQuery("return GSTR-3B rate tax", ClauseFilter(as_of=as_of), k=3)
        return {hit.detail.clause.clause_ref: hit.out_of_force for hit in search.run(query)}

    assert flags(date(2026, 6, 1)) == {"en.p1": True, "en.p2": False, "en.p3": False}
    assert flags(date(2026, 8, 1)) == {"en.p1": True, "en.p2": True, "en.p3": False}
    assert flags(None) == {"en.p1": False, "en.p2": False, "en.p3": False}
