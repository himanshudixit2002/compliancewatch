"""Hybrid search (ADR-012 layer 2): the rulebook's full-text and vector search over clauses,
fused by reciprocal rank, then the answerer.

The question is embedded through the gateway and searched with the model that served the
vector, ``k=8``, in the fused order: there is no reranker. When embedding fails or its budget is
used up, the search runs on full text alone and the span says so. No hit means ``not_covered``
(``no_evidence``).
"""

from datetime import date
from typing import Final

from domain_kernel.vectors import Vector
from qa.application.answerer import Answerer
from qa.application.context import AskContext
from qa.domain.answer import Answer, Layer, Reason
from qa.domain.errors import DependencyUnavailableError, ModelBudgetExceededError
from qa.domain.evidence import BundleBuilder
from qa.domain.ports import ClauseSearch, Embedder, Span, Tracer
from qa.domain.records import SearchHit

SEARCH_K: Final = 8
SEARCH_STEP: Final = "search"
"""The step id clauses found by hybrid search carry in the bundle."""
LEXICAL_ONLY: Final = "qa.retrieve.lexical_only"


def search_clauses(
    search: ClauseSearch,
    embedder: Embedder,
    ctx: AskContext,
    text: str,
    *,
    as_of: date,
    k: int,
    layer: Layer,
    span: Span,
) -> tuple[SearchHit, ...]:
    """Search ``text`` with its embedding, or on full text alone when embedding fails."""
    request = ctx.request
    vector: Vector | None = None
    model: str | None = None
    try:
        embedding = embedder.embed(
            text,
            tenant=request.tenant,
            metadata={"question_id": request.question_id, "layer": layer.value},
        )
        vector, model = embedding.vector, embedding.model
    except (DependencyUnavailableError, ModelBudgetExceededError):
        span.set_attribute(LEXICAL_ONLY, True)
    return search.search(text, vector=vector, model=model, as_of=as_of, k=k)


class HybridLayer:
    def __init__(
        self,
        search: ClauseSearch,
        embedder: Embedder,
        answerer: Answerer,
        tracer: Tracer,
        *,
        k: int = SEARCH_K,
    ) -> None:
        self._search = search
        self._embedder = embedder
        self._answerer = answerer
        self._tracer = tracer
        self._k = k

    def run(self, ctx: AskContext) -> Answer:
        request = ctx.request
        with self._tracer.span("qa.retrieve", {"qa.k": self._k}) as span:
            hits = search_clauses(
                self._search,
                self._embedder,
                ctx,
                request.question,
                as_of=request.as_of,
                k=self._k,
                layer=Layer.HYBRID,
                span=span,
            )
            span.set_attribute("qa.retrieve.hits", len(hits))
        if not hits:
            return Answer.not_covered(Reason.NO_EVIDENCE)
        builder = BundleBuilder()
        for hit in hits:
            clause = hit.clause
            builder.add_clause(
                clause_id=clause.clause_id,
                document_id=clause.document_id,
                clause_ref=clause.clause_ref,
                text=clause.text,
                step_id=SEARCH_STEP,
                source=clause.source,
            )
        return self._answerer.answer(ctx, builder.build(), Layer.HYBRID)
