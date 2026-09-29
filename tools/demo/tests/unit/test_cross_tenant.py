"""Tenant isolation at the HTTP edge, route by route, with every service in process on its
memory store.

Every route of a tenant-owned service (identity, profile, obligation, notification) is either
tenant-owned, and then answers 401 to a request without ``x-tenant-id`` whatever its path and
body, or exempt with the reason written next to it. A route in neither list fails the suite
with its name, so whoever adds a route classifies it. The rulebook holds regulatory data every
tenant reads, so its writes need the write token (the pipeline) or the review token (analyst
actions) instead of a tenant. The llm-gateway is shared
infrastructure and is recorded with its reasons and one open finding.

The probes at the end seed data as tenant A through the API and read it as tenant B. The
Postgres proofs (forced row-level security under a plain role) stay in each service's
integration tests.
"""

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient

from identity.main import build_app as build_identity
from identity.testing import identity_settings
from llm_gateway.main import build_app as build_gateway
from llm_gateway.settings import GatewaySettings
from notification.main import build_app as build_notification
from notification.testing import notification_settings
from obligation.main import build_app as build_obligation
from obligation.settings import ObligationSettings
from profile_service.main import build_app as build_profile
from profile_service.settings import ProfileSettings
from qa.main import build_app as build_qa
from qa.testing import memory_ports, qa_settings
from rulebook.main import build_app as build_rulebook
from rulebook.testing import rulebook_settings

DUMMY_ID = "00000000-0000-4000-8000-000000000000"
"""Every path parameter of a probe; a tenant check must answer before the id is looked up."""
TENANT_A = UUID("0a0a0a0a-0000-4000-8000-00000000000a")
TENANT_B = UUID("0b0b0b0b-0000-4000-8000-00000000000b")
AS_A = {"x-tenant-id": str(TENANT_A)}
AS_B = {"x-tenant-id": str(TENANT_B)}
GSTIN = "29ABCDE1234F1Z5"
FY = "2026-27"

BUILDERS: dict[str, Callable[[], FastAPI]] = {
    "identity": lambda: build_identity(identity_settings()),
    "profile": lambda: build_profile(
        ProfileSettings(
            _env_file=None,
            service_name="profile",
            profile_store="memory",
            profile_gstin_lookup="static",
        )
    ),
    "obligation": lambda: build_obligation(
        ObligationSettings(_env_file=None, service_name="obligation", obligation_store="memory")
    ),
    "notification": lambda: build_notification(notification_settings()),
    "qa": lambda: build_qa(qa_settings(), ports=memory_ports()),
}
TENANT_OWNED_SERVICES = tuple(BUILDERS)

PROBES = "liveness and readiness probes for the platform; they return no tenant data"

TENANT_ROUTES: dict[str, frozenset[str]] = {
    "identity": frozenset(
        {
            "POST /v1/identity/consents",
            "GET /v1/identity/consents",
            "POST /v1/identity/billing/subscriptions",
        }
    ),
    "profile": frozenset(
        {
            "POST /v1/profile/entities",
            "POST /v1/profile/registrations",
            "POST /v1/profile/locations",
            "GET /v1/profile/nodes/{node_id}",
            "PUT /v1/profile/nodes/{node_id}/attributes",
            "GET /v1/profile/nodes/{node_id}/snapshot",
            "GET /v1/profile/nodes/{node_id}/next-question",
            "GET /v1/profile/nodes/{node_id}/review-tasks",
            "POST /v1/profile/registrations/{node_id}/prefill",
            "POST /v1/profile/financial-year-confirmations",
            "POST /v1/businesses",
            "GET /v1/businesses",
            "GET /v1/businesses/{business_id}",
            "PATCH /v1/businesses/{business_id}",
            "GET /v1/businesses/{business_id}/onboarding",
            "POST /v1/businesses/{business_id}/registrations",
        }
    ),
    "obligation": frozenset({"GET /v1/obligation/obligations"}),
    "notification": frozenset({"POST /v1/notification/send"}),
    "qa": frozenset({"POST /v1/qa/ask"}),
}
"""Routes that must answer 401 without ``x-tenant-id``."""

SERVICE_TOKEN = (
    "a number's consent before any tenant owns the number; the caller is the WhatsApp bot, "
    "which sends the service token (x-cw-service-token), and a missing token is a 401"
)
PREFERENCE = (
    "an opt-out typed on WhatsApp arrives before the number is linked to a tenant and must be "
    "honoured either way; preferences are keyed by channel and recipient"
)

EXEMPT_ROUTES: dict[str, dict[str, str]] = {
    "identity": {
        "POST /v1/identity/channel-consents": SERVICE_TOKEN,
        "GET /v1/identity/channel-consents/{channel}/{subject}": SERVICE_TOKEN,
        "GET /v1/identity/billing/plans": "the price list, the same for every visitor",
        "POST /v1/identity/billing/webhook": (
            "called by the billing provider, which names no tenant; the body is verified "
            "against the webhook signature before it is read"
        ),
    },
    "profile": {
        "GET /v1/ontology": (
            "global data: the attributes, their questions, labels and rule operators are the same "
            "for every tenant, and nothing a tenant stored is in the answer"
        ),
    },
    "obligation": {},
    "notification": {
        "PUT /v1/notification/preferences/{channel}/{recipient}": PREFERENCE,
        "GET /v1/notification/preferences/{channel}/{recipient}": PREFERENCE,
        "GET /v1/notification/templates": "the message templates are the same for every tenant",
    },
    "qa": {},
}
"""Routes of tenant-owned services that take no tenant, each with the reason; every service
also serves the probes and its router's ping."""

GUARDED_EXEMPT_ROUTES = {
    "POST /v1/identity/channel-consents": 401,
    "GET /v1/identity/channel-consents/{channel}/{subject}": 401,
    "POST /v1/identity/billing/webhook": 401,
}
"""Exempt routes whose own guard refuses an anonymous request."""

RULEBOOK_READ_ONLY_WRITES: dict[str, str] = {
    "POST /v1/rulebook/search": "clause search takes its query in the body but writes nothing",
}
"""Rulebook routes with a write method that only read, so they need no write token."""

GATEWAY_ROUTES: dict[str, str] = {
    "GET /health": PROBES,
    "GET /ready": PROBES,
    "GET /v1/llm-gateway/ping": "router liveness; no data",
    "POST /v1/llm-gateway/completions": (
        "shared infrastructure called by other services; the tenant header is optional because "
        "regulatory work (pipeline extraction) has no tenant, and it only attributes cost"
    ),
    "GET /v1/llm-gateway/usage": (
        "an operator read of spend against a budget; see the finding below: tenant_id in the "
        "query reads any tenant's spend"
    ),
    "GET /v1/llm-gateway/models": "the routing table, the same for every caller",
    "GET /v1/llm-gateway/prompts": "the prompt registry, the same for every caller",
    "POST /v1/llm-gateway/embeddings": (
        "shared infrastructure like completions: clause embedding for the search index has no "
        "tenant, and the tenant header, when sent, only attributes cost"
    ),
}
"""The llm-gateway is shared infrastructure: no route is tenant-owned. Each is listed so a new
one is looked at."""


def served(app: FastAPI) -> set[str]:
    """``METHOD /path`` for every route the app serves, without FastAPI's docs pages."""
    docs = {app.openapi_url, app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url}
    routes: set[str] = set()
    for route in iter_route_contexts(app.routes):
        if not route.path or route.path in docs:
            continue
        methods = set(route.methods or ()) - {"HEAD", "OPTIONS"}
        routes.update(f"{method} {route.path}" for method in methods)
    return routes


def classified(service: str) -> set[str]:
    shared = {"GET /health", "GET /ready", f"GET /v1/{service}/ping"}
    return shared | TENANT_ROUTES[service] | set(EXEMPT_ROUTES[service])


def check_classified(service: str, app: FastAPI) -> None:
    """Fail with the name of every route of ``service`` that is neither tenant-owned nor
    exempt, and of every listed route the service no longer serves."""
    routes = served(app)
    unclassified = sorted(routes - classified(service))
    gone = sorted(classified(service) - routes)
    assert not unclassified, (
        f"{service}: unclassified route(s) {unclassified}; add each to TENANT_ROUTES, or to "
        "EXEMPT_ROUTES with the reason it takes no tenant"
    )
    assert not gone, f"{service}: listed route(s) {gone} are not served any more"


def request(client: TestClient, route: str, **kwargs: Any) -> Any:
    """Call ``METHOD /path`` with every path parameter set to ``DUMMY_ID`` and no body."""
    method, path = route.split(" ", 1)
    for name in (part[1:-1] for part in path.split("/") if part.startswith("{")):
        path = path.replace(f"{{{name}}}", DUMMY_ID)
    return client.request(method, path, **kwargs)


@pytest.fixture(scope="module")
def clients() -> Iterator[dict[str, TestClient]]:
    opened = {service: TestClient(build()) for service, build in BUILDERS.items()}
    for client in opened.values():
        client.__enter__()
    yield opened
    for client in opened.values():
        client.__exit__(None, None, None)


@pytest.mark.parametrize("service", TENANT_OWNED_SERVICES)
def test_every_route_of_a_tenant_owned_service_is_classified(
    service: str, clients: dict[str, TestClient]
) -> None:
    app = clients[service].app
    assert isinstance(app, FastAPI)
    check_classified(service, app)


@pytest.mark.parametrize(
    ("service", "route"),
    [(service, route) for service in TENANT_OWNED_SERVICES for route in TENANT_ROUTES[service]],
)
def test_a_tenant_route_refuses_a_request_without_a_tenant(
    service: str, route: str, clients: dict[str, TestClient]
) -> None:
    response = request(clients[service], route)
    assert response.status_code == 401, (route, response.text)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "tenant-required" in response.json()["type"]


@pytest.mark.parametrize(("route", "status"), sorted(GUARDED_EXEMPT_ROUTES.items()))
def test_an_exempt_route_with_its_own_guard_refuses_an_anonymous_request(
    route: str, status: int, clients: dict[str, TestClient]
) -> None:
    service = route.split("/")[2]
    assert route in EXEMPT_ROUTES[service]
    assert request(clients[service], route).status_code == status


def test_an_unclassified_route_fails_with_its_name() -> None:
    app = BUILDERS["profile"]()

    @app.get("/v1/profile/nodes/{node_id}/documents")
    def documents(node_id: UUID) -> list[str]:  # pragma: no cover - never called
        return []

    with pytest.raises(AssertionError, match=r"GET /v1/profile/nodes/\{node_id\}/documents"):
        check_classified("profile", app)


def test_every_rulebook_write_needs_the_write_or_the_review_token() -> None:
    app = build_rulebook(rulebook_settings())
    writes = sorted(
        route
        for route in served(app)
        if not route.startswith("GET ") and route not in RULEBOOK_READ_ONLY_WRITES
    )
    assert "PUT /v1/rulebook/documents/{document_id}" in writes
    with TestClient(app) as client:
        for route in writes:
            response = request(client, route)
            assert response.status_code == 401, (route, response.text)
            assert response.json()["type"].endswith(
                (":rulebook-write-token-invalid", ":rulebook-review-token-invalid")
            ), route


def gateway_app() -> FastAPI:
    return build_gateway(
        GatewaySettings(
            _env_file=None,
            service_name="llm-gateway",
            llm_provider="fake",
            llm_ledger="memory",
            llm_routes={},
            langfuse_host=None,
            langfuse_public_key=None,
            langfuse_secret_key=None,
        )
    )


def test_the_gateway_routes_are_recorded_as_shared_infrastructure() -> None:
    assert served(gateway_app()) == set(GATEWAY_ROUTES)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "open finding: GET /v1/llm-gateway/usage?tenant_id= reads any tenant's spend; it is an "
        "operator read until the gateway checks roles or is reachable only on a private network"
    ),
)
def test_tenant_b_cannot_read_the_spend_of_tenant_a_at_the_gateway() -> None:
    with TestClient(gateway_app()) as gateway:
        completion = gateway.post(
            "/v1/llm-gateway/completions",
            json={"feature": "smoke", "prompt": "smoke.echo@1", "user": "hello " * 40},
            headers=AS_A,
        )
        # pytest.fail, not assert: a broken setup must fail the test, not pass as the finding.
        if completion.status_code != 200 or Decimal(completion.json()["cost_inr"]) <= 0:
            pytest.fail(f"the completion of tenant A cost nothing: {completion.text}")
        read = gateway.get(
            "/v1/llm-gateway/usage", params={"tenant_id": str(TENANT_A)}, headers=AS_B
        )
    assert read.status_code in {401, 403, 404} or Decimal(read.json()["spent_inr"]) == 0


def test_tenant_b_cannot_read_the_consents_of_tenant_a(clients: dict[str, TestClient]) -> None:
    identity = clients["identity"]
    subject = "owner@tenant-a.example"
    recorded = identity.post(
        "/v1/identity/consents",
        json={
            "subject": subject,
            "purpose": "whatsapp_reminders",
            "source": "web_onboarding",
            "notice_version": "cross-tenant test",
            "evidence": "checkbox",
        },
        headers=AS_A,
    )
    assert recorded.status_code == 201
    as_a = identity.get("/v1/identity/consents", params={"subject": subject}, headers=AS_A)
    as_b = identity.get("/v1/identity/consents", params={"subject": subject}, headers=AS_B)
    assert [record["id"] for record in as_a.json()["history"]] == [recorded.json()["id"]]
    assert as_b.status_code == 200
    assert as_b.json()["history"] == []
    assert not any(state.get("granted") for state in as_b.json()["states"])


@pytest.fixture(scope="module")
def registration(clients: dict[str, TestClient]) -> dict[str, Any]:
    """A registration of tenant A, with its entity as ``parent_id``."""
    created = clients["profile"].post(
        "/v1/profile/registrations",
        json={"gstin": GSTIN, "name": "Tenant A Traders", "entity_name": "Tenant A Traders"},
        headers=AS_A,
    )
    assert created.status_code == 201
    node: dict[str, Any] = created.json()
    return node


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/v1/profile/nodes/{id}", None),
        ("GET", "/v1/profile/nodes/{id}/snapshot?fy=" + FY, None),
        ("GET", "/v1/profile/nodes/{id}/next-question?fy=" + FY, None),
        ("GET", "/v1/profile/nodes/{id}/review-tasks", None),
        (
            "PUT",
            "/v1/profile/nodes/{id}/attributes",
            {"changes": [{"key": "registration_type", "value": "regular"}], "source": "user_input"},
        ),
        ("POST", "/v1/profile/registrations/{id}/prefill", {}),
    ],
)
@pytest.mark.parametrize("node", ["registration", "entity"])
def test_tenant_b_cannot_reach_a_profile_node_of_tenant_a(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    node: str,
    registration: dict[str, Any],
    clients: dict[str, TestClient],
) -> None:
    profile = clients["profile"]
    node_id = registration["id"] if node == "registration" else registration["parent_id"]
    url = path.replace("{id}", node_id)
    as_b = profile.request(method, url, json=body, headers=AS_B)
    assert as_b.status_code == 404, as_b.text
    assert profile.get(f"/v1/profile/nodes/{node_id}", headers=AS_A).status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/v1/businesses/{id}", None),
        ("PATCH", "/v1/businesses/{id}", {"name": "Taken over"}),
        ("GET", "/v1/businesses/{id}/onboarding", None),
        ("POST", "/v1/businesses/{id}/registrations", {"gstin": GSTIN}),
    ],
)
def test_tenant_b_cannot_reach_a_business_of_tenant_a(
    method: str,
    path: str,
    body: dict[str, Any] | None,
    registration: dict[str, Any],
    clients: dict[str, TestClient],
) -> None:
    profile = clients["profile"]
    business = registration["parent_id"]
    headers = {**AS_B, "Idempotency-Key": f"cross-tenant-{method}-{len(path)}"}
    as_b = profile.request(method, path.replace("{id}", business), json=body, headers=headers)
    assert as_b.status_code == 404, as_b.text
    as_a = profile.get(f"/v1/businesses/{business}", headers=AS_A)
    assert as_a.json()["name"] == "Tenant A Traders"


def test_the_business_list_of_tenant_b_holds_nothing_of_tenant_a(
    registration: dict[str, Any], clients: dict[str, TestClient]
) -> None:
    profile = clients["profile"]
    second = profile.post(
        "/v1/businesses",
        json={"name": "Tenant A Holdings", "pan": "AAAAA1111A"},
        headers={**AS_A, "Idempotency-Key": "cross-tenant-list-01"},
    )
    assert second.status_code == 201, second.text
    mine = profile.get("/v1/businesses", params={"limit": 1}, headers=AS_A).json()
    assert mine["next_cursor"] is not None
    listed = profile.get("/v1/businesses", headers=AS_A).json()["items"]
    assert registration["parent_id"] in [item["id"] for item in listed]
    theirs = profile.get("/v1/businesses", params={"q": GSTIN}, headers=AS_B)
    assert theirs.json() == {"items": [], "next_cursor": None}
    refused = profile.get("/v1/businesses", params={"cursor": mine["next_cursor"]}, headers=AS_B)
    assert refused.status_code == 422, "tenant A's cursor names no business of tenant B"


def test_the_financial_year_confirmation_of_tenant_b_leaves_tenant_a_alone(
    registration: dict[str, Any], clients: dict[str, TestClient]
) -> None:
    profile = clients["profile"]
    entity = registration["parent_id"]
    before = profile.get(f"/v1/profile/nodes/{entity}/review-tasks", headers=AS_A).json()
    confirmed = profile.post(
        "/v1/profile/financial-year-confirmations", json={"fy": FY}, headers=AS_B
    )
    assert confirmed.status_code == 200
    assert confirmed.json() == {"fy": FY, "opened": []}
    after = profile.get(f"/v1/profile/nodes/{entity}/review-tasks", headers=AS_A).json()
    assert after == before
