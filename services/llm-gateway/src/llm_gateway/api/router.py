"""Routes of the llm-gateway service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/llm-gateway", tags=["llm-gateway"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "llm-gateway", "status": "pong"}
