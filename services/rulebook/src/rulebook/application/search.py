"""Store clause embeddings, list the clauses still to embed, and search clauses.

The pipeline embeds clauses through the LLM gateway and stores the vectors here; the rulebook
never calls a model. A clause keeps its first embedding from a model: storing again under the
same model changes nothing, and a new model means a new embedding beside the old one.

A search draws a pool of candidates from each leg, larger than ``k`` so that fusion has
something to reorder, then keeps the ``k`` best by reciprocal rank.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from domain_kernel._validation import require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId
from domain_kernel.vectors import EMBEDDING_DIMS
from rulebook.domain.errors import EmbeddingDimensionError, UnknownClauseError
from rulebook.domain.graph import ClauseDetail
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.domain.search import ClauseEmbedding, SearchHit, SearchQuery, fuse

MAX_EMBEDDINGS = 256
MAX_UNEMBEDDED = 500
MIN_POOL = 40
MAX_POOL = 200


def pool_size(k: int) -> int:
    """How many candidates each leg contributes for ``k`` results."""
    return min(MAX_POOL, max(MIN_POOL, 4 * k))


@dataclass(frozen=True, slots=True)
class StoreReport:
    stored: int
    unchanged: int


class StoreEmbeddings:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, model: str, dims: int, embeddings: Sequence[ClauseEmbedding]) -> StoreReport:
        """All or nothing: an unknown clause, a repeated clause or a wrong dimension refuses
        the whole batch."""
        require_text(model, "model")
        if dims != EMBEDDING_DIMS:
            raise EmbeddingDimensionError(
                f"vectors have {EMBEDDING_DIMS} dimensions, the batch says {dims}"
            )
        if not 1 <= len(embeddings) <= MAX_EMBEDDINGS:
            raise InvariantViolationError(f"send 1 to {MAX_EMBEDDINGS} embeddings at a time")
        ids = [embedding.clause_id for embedding in embeddings]
        if len(set(ids)) != len(ids):
            raise InvariantViolationError("each clause appears at most once in a batch")
        with self._unit_of_work() as uow:
            unknown = uow.index.unknown_clauses(ids)
            if unknown:
                raise UnknownClauseError(
                    f"{len(unknown)} clauses are not stored: "
                    + ", ".join(sorted(str(clause_id) for clause_id in unknown)[:5])
                )
            stored, unchanged = uow.index.store(model, embeddings)
        return StoreReport(stored=stored, unchanged=unchanged)


class ListUnembeddedClauses:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        model: str,
        document_id: DocumentId | None = None,
        limit: int = 100,
        after: ClauseId | None = None,
    ) -> Sequence[ClauseDetail]:
        with self._unit_of_work() as uow:
            return uow.index.unembedded(
                model, document_id, min(max(limit, 1), MAX_UNEMBEDDED), after
            )


class SearchClauses:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, query: SearchQuery) -> list[SearchHit]:
        pool = pool_size(query.k)
        with self._unit_of_work() as uow:
            lexical = uow.index.lexical(query.text, query.filters, pool)
            vector: Sequence[ClauseId] = ()
            if query.vector is not None and query.model is not None:
                vector = uow.index.nearest(query.vector, query.model, query.filters, pool)
            fused = fuse(lexical, vector, query.k)
            found = uow.index.hits([rank.clause_id for rank in fused], query.filters.as_of)
        return [
            SearchHit(
                detail=found[rank.clause_id].detail,
                score=rank.score,
                lexical_rank=rank.lexical_rank,
                vector_rank=rank.vector_rank,
                cited_by=found[rank.clause_id].cited_by,
            )
            for rank in fused
        ]
