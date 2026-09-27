"""Routes of the qa service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/qa", tags=["qa"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "qa", "status": "pong"}
