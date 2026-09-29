"""The profile service's snapshot route as the qa service's ``ProfileReader``."""

from typing import Final
from uuid import UUID

import httpx2

from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.profiles import ProfileSnapshot
from qa.infrastructure.http import JsonHttp, http_client, reading

SNAPSHOT_PATH: Final = "/v1/profile/nodes/{node_id}/snapshot"
SERVICE: Final = "profile"


class HttpProfiles:
    """``base_url`` is ``CW_PROFILE_URL``; the tenant goes in ``x-tenant-id`` on every call, which
    a service token may name with the tenant:act scope. ``auth`` is the service's token auth
    (None sends no token). JSON lists come back as sets, which is how set-valued attributes are
    compared."""

    def __init__(
        self,
        base_url: str = "http://localhost:8002",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._http = JsonHttp(http_client(base_url, timeout_seconds, client), SERVICE, auth=auth)

    def snapshot(
        self, tenant: TenantId, business: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        data = self._http.get(
            SNAPSHOT_PATH.format(node_id=business),
            params={} if fy is None else {"fy": fy.label},
            headers={"x-tenant-id": str(tenant)},
        )
        if data is None:
            return None
        with reading(SERVICE):
            level = data.get("level")
            as_of_fy = data.get("as_of_fy")
            return ProfileSnapshot(
                business_id=BusinessId(UUID(str(data["business_id"]))),
                tenant_id=TenantId(UUID(str(data["tenant_id"]))),
                version=int(data["version"]),
                attributes={
                    str(key): frozenset(value) if isinstance(value, list) else value
                    for key, value in dict(data["attributes"]).items()
                },
                as_of_fy=None if as_of_fy is None else FinancialYear.parse(str(as_of_fy)),
                level=None if level is None else AttributeLevel(level),
                lineage=tuple(BusinessId(UUID(str(item))) for item in data.get("lineage", [])),
            )

    def close(self) -> None:
        self._http.close()
