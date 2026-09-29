"""Property tests of the identity API against its spec (schemathesis).

Schemathesis generates valid and invalid requests from the served schema, which
``test_openapi.py`` pins to the committed spec, and sends them in process with a tenant header.
Each response must not be a server error, and its status code, content type and body must be
the ones the spec documents.

Only the operations in ``OPERATIONS`` run: those served when these tests arrived. A change that
adds an operation opts it in here. An operation that cannot pass yet, for a defect or because it
needs a redesign, goes in ``EXCLUDED`` with the reason.
"""

import os
from typing import Any, cast

import schemathesis
from hypothesis import settings
from schemathesis.checks import CheckFunction, not_a_server_error
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from identity.main import build_app
from identity.testing import identity_settings

TENANT_ID = "7d0f4d56-2a8e-4c1b-9f3e-5b6a1c2d3e4f"
OPERATIONS = frozenset(
    {
        "GET /health",
        "GET /ready",
        "GET /v1/identity/billing/plans",
        "POST /v1/identity/billing/subscriptions",
        "POST /v1/identity/billing/webhook",
        "GET /v1/identity/consents",
        "POST /v1/identity/consents",
        "GET /v1/identity/ping",
    }
)
UNLISTED_400 = "a body that is not UTF-8 is answered with a 400 the spec does not list"
VALIDATION_422 = "the spec gives a 422 as FastAPI's HTTPValidationError, the answer is a Problem"
EXCLUDED: dict[str, str] = {
    "POST /v1/identity/billing/subscriptions": UNLISTED_400,
    "POST /v1/identity/billing/webhook": VALIDATION_422,
    "GET /v1/identity/consents": VALIDATION_422,
    "POST /v1/identity/consents": UNLISTED_400,
}
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


def test_every_listed_operation_is_served() -> None:
    paths = app.openapi()["paths"]
    labels = {f"{method.upper()} {path}" for path, item in paths.items() for method in item}
    assert labels >= OPERATIONS | EXCLUDED.keys()


@schema.parametrize()
@settings(max_examples=EXAMPLES)
def test_responses_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(headers={"x-tenant-id": TENANT_ID}, checks=CHECKS)
