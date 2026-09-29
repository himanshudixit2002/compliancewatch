"""The clause search index: the pipeline stores clause embeddings, readers search clauses."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from domain_kernel.ids import ClauseId, DocumentId
from py_common.problems import problem_responses
from rulebook.api.deps import Wired, WriteAccess
from rulebook.api.read_schemas import ClauseDetailOut
from rulebook.api.search_schemas import EmbeddingsIn, EmbeddingsStoredOut, SearchHitOut, SearchIn

router = APIRouter(tags=["search"])


@router.put(
    "/clauses/embeddings",
    summary="Store clause embeddings from one model; a clause's first embedding stays",
    dependencies=[WriteAccess],
    responses=problem_responses(401, 422, 503),
)
def store_embeddings(body: EmbeddingsIn, wired: Wired) -> EmbeddingsStoredOut:
    report = wired.store_embeddings.run(
        body.model, body.dims, [item.to_embedding() for item in body.items]
    )
    return EmbeddingsStoredOut.from_report(report)


# Declared before /clauses/{clause_id}, which would otherwise try "unembedded" as an id.
@router.get(
    "/clauses/unembedded",
    summary="Clauses with no embedding from a model yet, in clause id order",
)
def list_unembedded(
    wired: Wired,
    model: Annotated[str, Query(min_length=1, max_length=120)],
    document_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    after: Annotated[UUID | None, Query(description="Continue after this clause id")] = None,
) -> list[ClauseDetailOut]:
    found = wired.list_unembedded.run(
        model,
        None if document_id is None else DocumentId(document_id),
        limit,
        None if after is None else ClauseId(after),
    )
    return [ClauseDetailOut.from_detail(detail) for detail in found]


@router.post(
    "/search",
    summary="Hybrid clause search: full text and vectors fused by reciprocal rank",
    responses=problem_responses(422),
)
def search(body: SearchIn, wired: Wired) -> list[SearchHitOut]:
    return [SearchHitOut.from_hit(hit) for hit in wired.search_clauses.run(body.to_query())]
