"""The identity client against a mock transport: the membership route answers whether a user
belongs to the tenant, identity's own 404 is nobody, and anything else the client cannot use is
IdentityUnavailableError."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx2
import pytest

from domain_kernel.ids import TenantId, UserId
from obligation.domain.errors import IdentityUnavailableError
from obligation.infrastructure.identity_client import HttpTenantMembers
from obligation.testing import TENANT
from py_common.auth import ServiceTokenUnavailableError

USER = UserId(UUID(int=0x5AF))
BASE = "http://identity.test"


def members(
    handler: Callable[[httpx2.Request], httpx2.Response], auth: httpx2.Auth | None = None
) -> HttpTenantMembers:
    client = httpx2.Client(base_url=BASE, transport=httpx2.MockTransport(handler))
    return HttpTenantMembers(BASE, client=client, auth=auth)


def membership(status: str = "active", tenant: TenantId = TENANT) -> dict[str, Any]:
    """What GET /v1/identity/users/{user_id}/membership answers."""
    return {
        "user_id": str(USER),
        "tenant_id": str(tenant),
        "roles": ["staff"],
        "status": status,
    }


def test_the_route_answers_an_active_or_disabled_member() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=membership())

    found = members(handler).membership(TENANT, USER)
    assert found is not None
    assert (found.user_id, found.tenant_id, found.active) == (USER, TENANT, True)
    (request,) = seen
    assert request.url.path == f"/v1/identity/users/{USER}/membership"
    assert request.headers["x-tenant-id"] == str(TENANT)
    disabled = members(lambda _: httpx2.Response(200, json=membership("disabled")))
    gone = disabled.membership(TENANT, USER)
    assert gone is not None
    assert gone.active is False


def problem(slug: str) -> Callable[[httpx2.Request], httpx2.Response]:
    """A handler answering identity's 404 problem ``slug``."""
    body = {"type": f"urn:compliancewatch:problem:{slug}", "status": 404}
    return lambda _: httpx2.Response(404, json=body)


def test_identitys_404_is_nobody_and_the_rest_is_unavailable() -> None:
    for slug in ("identity-user-not-found", "identity-tenant-not-found"):
        assert members(problem(slug)).membership(TENANT, USER) is None

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    def no_token(request: httpx2.Request) -> httpx2.Response:
        raise ServiceTokenUnavailableError("identity down")

    for handler in (
        problem("route-not-found"),
        lambda _: httpx2.Response(404, text="not json"),
        lambda _: httpx2.Response(401, json={}),
        lambda _: httpx2.Response(403, json={}),
        lambda _: httpx2.Response(500, text="boom"),
        lambda _: httpx2.Response(200, text="not json"),
        lambda _: httpx2.Response(200, json={"user_id": "x", "tenant_id": str(TENANT)}),
        unreachable,
        no_token,
    ):
        with pytest.raises(IdentityUnavailableError):
            members(handler).membership(TENANT, USER)


def test_the_service_token_goes_with_every_call() -> None:
    seen: list[str | None] = []

    class Bearer(httpx2.Auth):
        def auth_flow(self, request: httpx2.Request) -> Any:
            request.headers["authorization"] = "Bearer test-token"
            yield request

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization"))
        return httpx2.Response(200, json=membership())

    members(handler, auth=Bearer()).membership(TENANT, USER)
    members(handler).membership(TENANT, USER)
    assert seen == ["Bearer test-token", None]
