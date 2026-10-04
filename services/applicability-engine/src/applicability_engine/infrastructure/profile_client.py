"""The profile service's snapshot route (``GET /v1/profile/nodes/{node_id}/snapshot``) and its
business read (``GET /v1/businesses/{business_id}``, the registrations under a legal entity) as
the engine's ``ProfileReader``."""

from collections.abc import Sequence
from typing import Final
from uuid import UUID

import httpx2

from applicability_engine.infrastructure.http import JsonHttp, http_client, reading
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.profiles import ProfileSnapshot

SNAPSHOT_PATH: Final = "/v1/profile/nodes/{node_id}/snapshot"
BUSINESS_PATH: Final = "/v1/businesses/{business_id}"
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
        self, tenant_id: TenantId, business_id: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        data = self._http.get(
            SNAPSHOT_PATH.format(node_id=business_id),
            params={} if fy is None else {"fy": fy.label},
            headers={"x-tenant-id": str(tenant_id)},
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

    def registrations(
        self, tenant_id: TenantId, entity_id: BusinessId
    ) -> Sequence[BusinessId] | None:
        data = self._http.get(
            BUSINESS_PATH.format(business_id=entity_id),
            headers={"x-tenant-id": str(tenant_id)},
        )
        if data is None:
            return None
        with reading(SERVICE):
            return tuple(
                BusinessId(UUID(str(registration["id"]))) for registration in data["registrations"]
            )

    def close(self) -> None:
        self._http.close()
