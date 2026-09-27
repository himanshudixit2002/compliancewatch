"""Routes of the pipeline service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "pipeline", "status": "pong"}
