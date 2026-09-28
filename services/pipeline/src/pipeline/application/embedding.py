"""The embedding stage: a vector for every stored clause that has none, through the gateway.

It pages through the rulebook's clauses without a vector from the run's model, in clause id
order and 64 at a time, sends each page's texts (``domain.embedding.embedding_text``) to the
gateway in one call, checks the answer and stores the vectors. It reads and writes through its
ports, so unlike the extraction stages it is not a ``PipelineStage``; the ``EmbedClauses``
activity calls it for one document and ``pipeline-embed`` for every document.

Vectors from two models do not compare, so a run pins one model. The first call is a one-line
probe that asks the gateway which model serves retrieval (the route's, or ``model`` when the
caller overrides it for a re-embed); the rulebook is asked about that model's gaps and every
batch must come back from it. An answer of another length than ``EMBEDDING_DIMS``, another count
than the texts sent or another model raises ``EmbeddingContractError`` before anything is
stored.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from domain_kernel.ids import ClauseId, DocumentId
from domain_kernel.vectors import EMBEDDING_DIMS
from pipeline.domain.embedding import ClauseVector, EmbeddingBatch, embedding_text
from pipeline.domain.errors import EmbeddingContractError
from pipeline.domain.ports import ClauseIndexSink, Embedder

BATCH_SIZE: Final = 64
MODEL_PROBE: Final = "retrieval model probe"


@dataclass(frozen=True, slots=True)
class EmbeddingRun:
    """What one run did: the model it pinned, vectors stored now, clauses already embedded."""

    model: str
    embedded: int = 0
    unchanged: int = 0


class EmbeddingStage:
    def __init__(
        self, embedder: Embedder, index: ClauseIndexSink, *, batch_size: int = BATCH_SIZE
    ) -> None:
        if not 1 <= batch_size <= BATCH_SIZE:
            raise ValueError(f"batch_size must be 1 to {BATCH_SIZE}")
        self._embedder = embedder
        self._index = index
        self._batch_size = batch_size

    def embed_missing(
        self,
        document_id: DocumentId | None,
        *,
        limit: int | None = None,
        model: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> EmbeddingRun:
        """Embed the clauses of ``document_id`` (``None``: of every document) that have no
        vector yet, at most ``limit`` of them."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        tags = {**(metadata or {}), "stage": "embedding"}
        probe = self._embedder.embed((MODEL_PROBE,), model=model, metadata=tags)
        served = probe.model
        _check(probe, 1, served)
        embedded = unchanged = 0
        after: ClauseId | None = None
        while limit is None or embedded + unchanged < limit:
            size = self._batch_size
            if limit is not None:
                size = min(size, limit - embedded - unchanged)
            page = self._index.unembedded_clauses(
                served, document_id=document_id, limit=size, after=after
            )
            if not page:
                break
            batch = self._embedder.embed(
                [embedding_text(clause) for clause in page], model=model, metadata=tags
            )
            _check(batch, len(page), served)
            report = self._index.put_embeddings(
                served,
                batch.dims,
                [
                    ClauseVector(clause.clause_id, vector)
                    for clause, vector in zip(page, batch.vectors, strict=True)
                ],
            )
            embedded += report.stored
            unchanged += report.unchanged
            if len(page) < size:
                break
            after = page[-1].clause_id
        return EmbeddingRun(served, embedded, unchanged)


def _check(batch: EmbeddingBatch, count: int, model: str) -> None:
    if batch.model != model:
        raise EmbeddingContractError(
            f"the gateway served {batch.model!r} in a run pinned to {model!r}"
        )
    if batch.dims != EMBEDDING_DIMS or any(len(v) != EMBEDDING_DIMS for v in batch.vectors):
        raise EmbeddingContractError(
            f"{model} answered {batch.dims}-dimensional vectors; the rulebook stores "
            f"{EMBEDDING_DIMS}"
        )
    if len(batch.vectors) != count:
        raise EmbeddingContractError(
            f"{model} answered {len(batch.vectors)} vectors for {count} texts"
        )
