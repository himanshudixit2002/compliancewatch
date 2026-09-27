"""Routes of the obligation service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/obligation", tags=["obligation"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "obligation", "status": "pong"}
