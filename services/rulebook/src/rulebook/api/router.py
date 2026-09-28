"""Routes of the rulebook service. Business logic lives in application use cases."""

from fastapi import APIRouter

from rulebook.api import documents, graph, publication, review, rule_versions, search

router = APIRouter(prefix="/v1/rulebook", tags=["rulebook"])
router.include_router(documents.router)
router.include_router(review.router)
router.include_router(rule_versions.router)
router.include_router(publication.router)
# Before graph: /clauses/unembedded must match ahead of /clauses/{clause_id}.
router.include_router(search.router)
router.include_router(graph.router)


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "rulebook", "status": "pong"}
