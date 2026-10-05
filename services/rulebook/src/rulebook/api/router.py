"""Routes of the rulebook service. Business logic lives in application use cases.

``router`` holds the service's routes under ``/v1/rulebook``; ``public_router`` the paths of the
public API outside that prefix (``GET /v1/changes``).
"""

from fastapi import APIRouter

from rulebook.api import changes, documents, graph, publication, review, rule_versions, search

router = APIRouter(prefix="/v1/rulebook", tags=["rulebook"])
public_router = changes.public_router
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
