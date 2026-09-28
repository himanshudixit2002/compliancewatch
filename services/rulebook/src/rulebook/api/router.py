"""Routes of the rulebook service. Business logic lives in application use cases."""

from fastapi import APIRouter

from rulebook.api import documents

router = APIRouter(prefix="/v1/rulebook", tags=["rulebook"])
router.include_router(documents.router)


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "rulebook", "status": "pong"}
