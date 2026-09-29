"""Property tests of the identity API against its spec (schemathesis).

Schemathesis generates valid and invalid requests from the served schema, which
``test_openapi.py`` pins to the committed spec, and sends them in process with a tenant header
and the service token of the test settings, so the channel consent routes get past their token
check. Each response must not be a server error, and its status code, content type and body must be
the ones the spec documents.

That app runs in header mode. The routes that read a signed-in user run again in token mode, on an
app where a tenant was signed up first, with that user's access token and no tenant header, so
``/me`` answers 200 and a generated ``x-tenant-id`` meets the tenant check.

Only the operations in ``OPERATIONS`` run: those served when these tests arrived. A change that
adds an operation opts it in here. An operation that cannot pass yet, for a defect or because it
needs a redesign, goes in ``EXCLUDED`` with the reason.
"""

import os
from typing import Any, cast

import schemathesis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, settings
from schemathesis.checks import CheckFunction, not_a_server_error
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from identity.main import build_app
from identity.testing import CHANNEL_TOKEN, identity_settings
from py_common.auth.testing import bearer

TENANT_ID = "7d0f4d56-2a8e-4c1b-9f3e-5b6a1c2d3e4f"
OPERATIONS = frozenset(
    {
        "GET /health",
        "GET /ready",
        "GET /v1/identity/billing/plans",
        "POST /v1/identity/billing/subscriptions",
        "POST /v1/identity/billing/webhook",
        "POST /v1/identity/channel-consents",
        "GET /v1/identity/channel-consents/{channel}/{subject}",
        "GET /v1/identity/consents",
        "POST /v1/identity/consents",
        "GET /v1/identity/ping",
        "POST /v1/identity/sessions",
        "POST /v1/identity/service-tokens",
        "GET /v1/identity/.well-known/jwks.json",
        "GET /v1/identity/me",
        "POST /v1/identity/dev/provider-tokens",
        "POST /v1/identity/tenants",
    }
)
TOKEN_OPERATIONS = frozenset(
    {
        "GET /v1/identity/me",
        "GET /v1/identity/consents",
        "POST /v1/identity/consents",
    }
)
EXCLUDED: dict[str, str] = {}
CHECKS = cast(
    list[CheckFunction],
    [
        not_a_server_error,
        status_code_conformance,
        content_type_conformance,
        response_schema_conformance,
    ],
)
EXAMPLES = 200 if os.environ.get("HYPOTHESIS_PROFILE") == "nightly" else 25

app = build_app(identity_settings())
schema = schemathesis.openapi.from_asgi("/openapi.json", app).include(
    func=lambda ctx: ctx.operation.label in OPERATIONS and ctx.operation.label not in EXCLUDED
)


def signed_up(target: FastAPI) -> str:
    """The access token of the first user of a tenant signed up on ``target``."""
    with TestClient(target) as client:
        provider_token = client.post(
            "/v1/identity/dev/provider-tokens", json={"phone": "+919876543210"}
        ).json()["provider_token"]
        created = client.post(
            "/v1/identity/tenants",
            json={"kind": "business", "name": "Acme Traders", "provider_token": provider_token},
        )
    token: str = created.json()["session"]["access_token"]
    return token


token_app = build_app(identity_settings(auth_mode="token"))
USER_TOKEN = signed_up(token_app)
token_schema = schemathesis.openapi.from_asgi("/openapi.json", token_app).include(
    func=lambda ctx: ctx.operation.label in TOKEN_OPERATIONS
)


def test_every_listed_operation_is_served() -> None:
    paths = app.openapi()["paths"]
    labels = {f"{method.upper()} {path}" for path, item in paths.items() for method in item}
    assert labels >= OPERATIONS | EXCLUDED.keys() | TOKEN_OPERATIONS


@schema.parametrize()
# Bodies with patterns and nested models make schemathesis discard many drafts; that is
# expected, not a slow or broken generator, so those two health checks do not apply.
@settings(
    max_examples=EXAMPLES,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
def test_responses_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(
        headers={"x-tenant-id": TENANT_ID, "x-cw-service-token": CHANNEL_TOKEN}, checks=CHECKS
    )


@token_schema.parametrize()
@settings(
    max_examples=EXAMPLES,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
def test_signed_in_responses_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(headers=bearer(USER_TOKEN), checks=CHECKS)
