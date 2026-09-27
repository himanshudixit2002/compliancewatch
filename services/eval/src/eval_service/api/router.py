"""Routes of the eval service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/eval", tags=["eval"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "eval", "status": "pong"}
