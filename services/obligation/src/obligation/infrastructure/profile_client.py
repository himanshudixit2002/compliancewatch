"""The profile service's node read as the obligation service's ``ProfileNodes``.

``GET {CW_PROFILE_URL}/v1/profile/nodes/{node_id}`` with the tenant in ``x-tenant-id`` answers
the node when the tenant has it: a business (its legal entity), a registration or a location.
Profile serves it to a service acting for the tenant, so in ``dual`` and ``token`` mode every call
carries this service's own access token (``auth``, from ``py_common.auth.service_auth_from``),
whose client needs the tenant:act scope.

A 200 is a node of the tenant, and a 404 with profile's own problem,
``profile-node-not-found``, is none: row-level security hides another tenant's nodes, so their
ids read as unknown ones. Any other answer (a 404 of another kind too, such as a URL that reaches
something else than profile), a transport error, or a service token identity could not issue
raises ``ProfileUnavailableError``: whether the business is the tenant's cannot be told now.
"""

from typing import Any, Final

import httpx2

from domain_kernel.ids import BusinessId, TenantId
from obligation.domain.errors import ProfileUnavailableError
from py_common.auth import ServiceTokenUnavailableError

NODE_PATH: Final = "/v1/profile/nodes/{node_id}"
TENANT_HEADER: Final = "x-tenant-id"
NOT_FOUND: Final = "profile-node-not-found"
DETAIL_CHARS: Final = 300


class HttpProfileNodes:
    """``base_url`` is ``CW_PROFILE_URL`` and ``auth`` the service's token auth (None sends no
    token). Pass ``client`` to talk to an in-process app or a mock transport instead of the
    network; ``auth`` applies to it too."""

    def __init__(
        self,
        base_url: str = "http://localhost:8002",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = auth

    def exists(self, tenant_id: TenantId, business_id: BusinessId) -> bool:
        path = NODE_PATH.format(node_id=business_id)
        headers = {TENANT_HEADER: str(tenant_id)}
        try:
            if self._auth is None:
                response = self._client.get(path, headers=headers)
            else:
                response = self._client.get(path, headers=headers, auth=self._auth)
        except httpx2.TransportError as exc:
            raise ProfileUnavailableError(f"profile unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise ProfileUnavailableError(f"no service token for profile: {exc}") from exc
        if response.status_code == 200:
            return True
        if response.status_code == 404 and _problem_slug(response) == NOT_FOUND:
            return False
        raise ProfileUnavailableError(
            f"profile answered {response.status_code} for node {business_id}: "
            f"{response.text[:DETAIL_CHARS]}"
        )

    def close(self) -> None:
        self._client.close()


def _problem_slug(response: httpx2.Response) -> str:
    """The last part of a problem's type, ``profile-node-not-found``; '' for another body."""
    try:
        body: Any = response.json()
    except ValueError:
        return ""
    kind = body.get("type") if isinstance(body, dict) else None
    return kind.rsplit(":", 1)[-1] if isinstance(kind, str) else ""
