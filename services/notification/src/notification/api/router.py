"""Routes of the notification service. Business logic lives in application use cases."""

from fastapi import APIRouter

router = APIRouter(prefix="/v1/notification", tags=["notification"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "notification", "status": "pong"}
