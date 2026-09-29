"""The obligation service's read route as the qa service's ``ObligationReader``."""

from datetime import date, datetime
from typing import Final
from uuid import UUID

import httpx2

from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from domain_kernel.status import ObligationStatus
from qa.domain.records import ObligationRecord
from qa.infrastructure.http import JsonHttp, http_client, reading

OBLIGATIONS_PATH: Final = "/v1/obligation/obligations"
SERVICE: Final = "obligation"


class HttpObligations:
    """``base_url`` is ``CW_OBLIGATION_URL``; the tenant goes in ``x-tenant-id`` on every call,
    which a service token may name with the tenant:act scope. ``auth`` is the service's token
    auth (None sends no token)."""

    def __init__(
        self,
        base_url: str = "http://localhost:8005",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._http = JsonHttp(http_client(base_url, timeout_seconds, client), SERVICE, auth=auth)

    def obligations(
        self,
        tenant: TenantId,
        business: BusinessId,
        *,
        due_from: date | None = None,
        due_to: date | None = None,
        rule_version_id: RuleVersionId | None = None,
    ) -> tuple[ObligationRecord, ...]:
        params: dict[str, str | int] = {"business_id": str(business)}
        if due_from is not None:
            params["due_from"] = due_from.isoformat()
        if due_to is not None:
            params["due_to"] = due_to.isoformat()
        if rule_version_id is not None:
            params["rule_version_id"] = str(rule_version_id)
        data = self._http.get(OBLIGATIONS_PATH, params=params, headers={"x-tenant-id": str(tenant)})
        with reading(SERVICE):
            return tuple(
                ObligationRecord(
                    obligation_id=ObligationId(UUID(str(item["obligation_id"]))),
                    business_id=BusinessId(UUID(str(item["business_id"]))),
                    rule_version_id=RuleVersionId(UUID(str(item["rule_version_id"]))),
                    title=str(item["title"]),
                    status=ObligationStatus(item["status"]),
                    period_label=None
                    if item.get("period_label") is None
                    else str(item["period_label"]),
                    due_at=None
                    if item.get("due_at") is None
                    else datetime.fromisoformat(str(item["due_at"])),
                )
                for item in data or []
            )

    def close(self) -> None:
        self._http.close()
