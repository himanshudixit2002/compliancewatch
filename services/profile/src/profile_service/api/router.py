"""Routes of the profile service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/profile", tags=["profile"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "profile", "status": "pong"}
