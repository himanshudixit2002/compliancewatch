"""Routes of the applicability-engine service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/applicability-engine", tags=["applicability-engine"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "applicability-engine", "status": "pong"}
