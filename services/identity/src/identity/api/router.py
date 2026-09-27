"""Routes of the identity service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/identity", tags=["identity"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "identity", "status": "pong"}
