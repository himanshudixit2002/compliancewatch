"""Routes of the rulebook service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/rulebook", tags=["rulebook"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "rulebook", "status": "pong"}
