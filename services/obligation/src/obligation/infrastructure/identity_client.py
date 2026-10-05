"""The identity service's membership route as the obligation service's ``TenantMembers``.

``GET {CW_IDENTITY_URL}/v1/identity/users/{user_id}/membership`` with the tenant in
``x-tenant-id`` answers whether the user belongs to the tenant, with their roles and status and
no contact details. Identity serves it to a service acting for the tenant, so in ``dual`` and
``token`` mode every call carries this service's own access token (``auth``, from
``py_common.auth.service_auth_from``), whose client needs the tenant:act scope.

A 404 with identity's own problem, ``identity-user-not-found`` or ``identity-tenant-not-found``,
is None: the tenant has no such user (or identity has no such tenant). A 200 names the user's
status, and only ``active`` counts as a member. Any other answer (a 404 of another kind too, such
as a URL that reaches something else than identity), a transport error, or a service token
identity could not issue raises ``IdentityUnavailableError``: the assignee cannot be checked now,
so the assignment is refused until it can.
"""

from typing import Any, Final

import httpx2

from domain_kernel.ids import TenantId, UserId
from obligation.domain.errors import IdentityUnavailableError
from obligation.domain.ports import Membership
from py_common.auth import ServiceTokenUnavailableError

MEMBERSHIP_PATH: Final = "/v1/identity/users/{user_id}/membership"
TENANT_HEADER: Final = "x-tenant-id"
ACTIVE: Final = "active"
NOT_MEMBERS: Final = frozenset({"identity-user-not-found", "identity-tenant-not-found"})
"""The problems identity answers when the tenant has no such user."""
DETAIL_CHARS: Final = 300


class HttpTenantMembers:
    """``base_url`` is ``CW_IDENTITY_URL`` and ``auth`` the service's token auth (None sends no
    token). Pass ``client`` to talk to an in-process app or a mock transport instead of the
    network; ``auth`` applies to it too."""

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        *,
        client: httpx2.Client | None = None,
        auth: httpx2.Auth | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._client = client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = auth

    def membership(self, tenant_id: TenantId, user_id: UserId) -> Membership | None:
        path = MEMBERSHIP_PATH.format(user_id=user_id)
        headers = {TENANT_HEADER: str(tenant_id)}
        try:
            if self._auth is None:
                response = self._client.get(path, headers=headers)
            else:
                response = self._client.get(path, headers=headers, auth=self._auth)
        except httpx2.TransportError as exc:
            raise IdentityUnavailableError(f"identity unreachable: {exc}") from exc
        except ServiceTokenUnavailableError as exc:
            raise IdentityUnavailableError(f"no service token for identity: {exc}") from exc
        if response.status_code == 404 and _problem_slug(response) in NOT_MEMBERS:
            return None
        if response.status_code != 200:
            raise IdentityUnavailableError(
                f"identity answered {response.status_code} for the membership of user {user_id}: "
                f"{response.text[:DETAIL_CHARS]}"
            )
        try:
            body: Any = response.json()
            return Membership(
                user_id=UserId.parse(str(body["user_id"])),
                tenant_id=TenantId.parse(str(body["tenant_id"])),
                active=body["status"] == ACTIVE,
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise IdentityUnavailableError(
                f"identity answered a membership the client cannot read: {exc}"
            ) from exc

    def close(self) -> None:
        self._client.close()


def _problem_slug(response: httpx2.Response) -> str:
    """The last part of a problem's type, ``identity-user-not-found``; '' for another body."""
    try:
        body: Any = response.json()
    except ValueError:
        return ""
    kind = body.get("type") if isinstance(body, dict) else None
    return kind.rsplit(":", 1)[-1] if isinstance(kind, str) else ""
