"""The qa service's own access token on its calls to the rulebook, profile, obligation and the
gateway.

With ``CW_SERVICE_CLIENT_SECRET`` set every request carries ``Authorization: Bearer`` with the
token the identity service issued, next to the tenant header the call already sent. Without the
secret no token is sent, as before.
"""

import json
from datetime import date
from typing import Any
from uuid import UUID

import httpx2
import pytest
from pydantic import SecretStr

from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.llm import CompletionRequest
from domain_kernel.vectors import EMBEDDING_DIMS
from py_common.auth import BearerAuth, service_auth_from
from py_common.auth.service_tokens import SERVICE_TOKENS_PATH
from qa.domain.errors import DependencyUnavailableError, GatewayError
from qa.infrastructure.gateway import GatewayProvider, HttpEmbedder
from qa.infrastructure.obligation_client import HttpObligations
from qa.infrastructure.profile_client import HttpProfiles
from qa.infrastructure.rulebook_client import HttpRulebook
from qa.main import http_ports
from qa.testing import qa_settings

IDENTITY_URL = "http://identity.test"
CLIENT_ID = "qa"
CLIENT_SECRET = SecretStr("qa-" + "s" * 32)
"""The dev client secret these tests exchange; the fake identity checks it."""
TENANT = TenantId(UUID(int=1))
BUSINESS = BusinessId(UUID(int=2))
COMPLETION = {
    "text": "{}",
    "model_served": "fake/echo",
    "input_tokens": 3,
    "output_tokens": 1,
    "trace_id": "t1",
}
EMBEDDING = {
    "model_served": "fake/embed",
    "dims": EMBEDDING_DIMS,
    "vectors": [[0.0] * EMBEDDING_DIMS],
}
SNAPSHOT = {
    "business_id": str(BUSINESS.value),
    "tenant_id": str(TENANT.value),
    "version": 1,
    "attributes": {},
}


class Identity:
    """The identity service's token route: checks the client and numbers the tokens it issues."""

    def __init__(self, *, down: bool = False) -> None:
        self.issued = 0
        self.down = down

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == IDENTITY_URL + SERVICE_TOKENS_PATH
        if self.down:
            return httpx2.Response(503, json={"type": "urn:problem:unavailable"})
        body = json.loads(request.content)
        if body != {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET.get_secret_value()}:
            return httpx2.Response(401, json={"type": "identity-service-client-invalid"})
        self.issued += 1
        return httpx2.Response(
            200,
            json={
                "access_token": f"qa-token-{self.issued}",
                "token_type": "Bearer",
                "expires_in": 600,
                "scopes": ["llm:call", "tenant:act"],
            },
        )


def settings(*, secret: SecretStr | None = CLIENT_SECRET) -> Any:
    return qa_settings(
        identity_url=IDENTITY_URL, service_client_id=CLIENT_ID, service_client_secret=secret
    )


def auth_for(identity: Identity) -> BearerAuth:
    auth = service_auth_from(
        settings(), client=httpx2.Client(transport=httpx2.MockTransport(identity))
    )
    assert auth is not None
    return auth


class Upstream:
    """Every service qa reads, by path; each request's headers are kept as they were sent."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, str]]] = []

    def client(self) -> httpx2.Client:
        return httpx2.Client(base_url="http://svc.test", transport=httpx2.MockTransport(self))

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append((request.url.path, dict(request.headers)))
        path = request.url.path
        if path.endswith("/completions"):
            return httpx2.Response(200, json=COMPLETION)
        if path.endswith("/embeddings"):
            return httpx2.Response(200, json=EMBEDDING)
        if path.endswith("/snapshot"):
            return httpx2.Response(200, json=SNAPSHOT)
        return httpx2.Response(200, json=[])


def read_everything(upstream: Upstream, auth: BearerAuth | None) -> None:
    client = upstream.client()
    HttpRulebook(client=client, auth=auth).rules_in_force(date(2026, 4, 10))
    HttpProfiles(client=client, auth=auth).snapshot(TENANT, BUSINESS, None)
    HttpObligations(client=client, auth=auth).obligations(TENANT, BUSINESS)
    HttpEmbedder(client=client, auth=auth).embed("question", tenant=TENANT, metadata={})
    GatewayProvider(client=client, auth=auth).complete(
        CompletionRequest("qa", "qa.answer@1", "s", "u", tenant_id=TENANT)
    )


def test_every_upstream_call_carries_the_service_token_and_the_tenant() -> None:
    identity, upstream = Identity(), Upstream()
    read_everything(upstream, auth_for(identity))
    assert [path.rsplit("/", 1)[-1] for path, _ in upstream.sent] == [
        "rule-versions",
        "snapshot",
        "obligations",
        "embeddings",
        "completions",
    ]
    assert {headers["authorization"] for _, headers in upstream.sent} == {"Bearer qa-token-1"}
    tenants = [headers.get("x-tenant-id") for _, headers in upstream.sent]
    assert tenants == [None, str(TENANT), str(TENANT), str(TENANT), str(TENANT)]
    assert identity.issued == 1


def test_without_a_client_secret_no_token_is_sent() -> None:
    assert service_auth_from(settings(secret=None)) is None
    upstream = Upstream()
    read_everything(upstream, None)
    assert all("authorization" not in headers for _, headers in upstream.sent)


def test_a_refused_token_is_replaced_once() -> None:
    identity = Identity()
    sent: list[str] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        sent.append(request.headers["authorization"])
        if request.headers["authorization"] == "Bearer qa-token-1":
            return httpx2.Response(401, json={"type": "auth-token-invalid"})
        return httpx2.Response(200, json=[])

    client = httpx2.Client(base_url="http://svc.test", transport=httpx2.MockTransport(answer))
    rulebook = HttpRulebook(client=client, auth=auth_for(identity))
    assert rulebook.rules_in_force(date(2026, 4, 10)) == ()
    assert sent == ["Bearer qa-token-1", "Bearer qa-token-2"]


def test_no_service_token_fails_the_call_as_an_unavailable_dependency() -> None:
    auth = auth_for(Identity(down=True))
    upstream = Upstream()
    client = upstream.client()
    with pytest.raises(DependencyUnavailableError, match="no service token for rulebook"):
        HttpRulebook(client=client, auth=auth).rules_in_force(date(2026, 4, 10))
    with pytest.raises(DependencyUnavailableError, match="no service token for profile"):
        HttpProfiles(client=client, auth=auth).snapshot(TENANT, BUSINESS, None)
    with pytest.raises(DependencyUnavailableError, match="no service token for llm-gateway"):
        HttpEmbedder(client=client, auth=auth).embed("question", tenant=None, metadata={})
    with pytest.raises(GatewayError, match="no service token"):
        GatewayProvider(client=client, auth=auth).complete(
            CompletionRequest("qa", "qa.answer@1", "s", "u")
        )
    assert upstream.sent == []


def test_the_http_ports_share_one_service_token() -> None:
    ports = http_ports(settings())
    provider, embedder = ports.provider, ports.embedder
    rulebook, profiles, obligations = ports.rulebook, ports.profiles, ports.obligations
    assert isinstance(provider, GatewayProvider)
    assert isinstance(embedder, HttpEmbedder)
    assert isinstance(rulebook, HttpRulebook)
    assert isinstance(profiles, HttpProfiles)
    assert isinstance(obligations, HttpObligations)
    auth = provider._auth
    assert isinstance(auth, BearerAuth)
    assert auth.source.client_id == CLIENT_ID
    readers = (rulebook._http, profiles._http, obligations._http, embedder._http)
    assert all(http._auth is auth for http in readers)
    assert ports.search is rulebook
    bare = http_ports(settings(secret=None))
    assert isinstance(bare.provider, GatewayProvider)
    assert isinstance(bare.rulebook, HttpRulebook)
    assert (bare.provider._auth, bare.rulebook._http._auth) == (None, None)
