"""The profile client against a mock transport: the node route answers whether the tenant has a
node, profile's own 404 is none, and anything else the client cannot use is
ProfileUnavailableError."""

from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from obligation.domain.errors import ProfileUnavailableError
from obligation.infrastructure.profile_client import HttpProfileNodes
from obligation.testing import BUSINESS, TENANT
from py_common.auth import ServiceTokenUnavailableError

BASE = "http://profile.test"


def nodes(
    handler: Callable[[httpx2.Request], httpx2.Response], auth: httpx2.Auth | None = None
) -> HttpProfileNodes:
    client = httpx2.Client(base_url=BASE, transport=httpx2.MockTransport(handler))
    return HttpProfileNodes(BASE, client=client, auth=auth)


def node() -> dict[str, Any]:
    """What GET /v1/profile/nodes/{node_id} answers, in part."""
    return {"id": str(BUSINESS), "level": "registration", "key": "29ZZZAA0000Z1Z5"}


def problem(slug: str) -> Callable[[httpx2.Request], httpx2.Response]:
    """A handler answering a 404 problem ``slug``."""
    body = {"type": f"urn:compliancewatch:problem:{slug}", "status": 404}
    return lambda _: httpx2.Response(404, json=body)


def test_a_node_of_the_tenant_exists_and_profiles_404_is_none() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=node())

    assert nodes(handler).exists(TENANT, BUSINESS) is True
    (request,) = seen
    assert request.url.path == f"/v1/profile/nodes/{BUSINESS}"
    assert request.headers["x-tenant-id"] == str(TENANT)
    assert nodes(problem("profile-node-not-found")).exists(TENANT, BUSINESS) is False


def test_anything_else_is_unavailable() -> None:
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
        unreachable,
        no_token,
    ):
        with pytest.raises(ProfileUnavailableError):
            nodes(handler).exists(TENANT, BUSINESS)


def test_the_service_token_goes_with_every_call() -> None:
    seen: list[str | None] = []

    class Bearer(httpx2.Auth):
        def auth_flow(self, request: httpx2.Request) -> Any:
            request.headers["authorization"] = "Bearer test-token"
            yield request

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("authorization"))
        return httpx2.Response(200, json=node())

    nodes(handler, auth=Bearer()).exists(TENANT, BUSINESS)
    probe = nodes(handler)
    probe.exists(TENANT, BUSINESS)
    probe.close()
    assert seen == ["Bearer test-token", None]
