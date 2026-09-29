"""Property tests of the llm-gateway API against its spec (schemathesis).

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

from llm_gateway.main import build_app
from llm_gateway.settings import GatewaySettings

TENANT_ID = "7d0f4d56-2a8e-4c1b-9f3e-5b6a1c2d3e4f"
OPERATIONS = frozenset(
    {
        "GET /health",
        "GET /ready",
        "POST /v1/llm-gateway/completions",
        "GET /v1/llm-gateway/models",
        "GET /v1/llm-gateway/ping",
        "GET /v1/llm-gateway/prompts",
        "GET /v1/llm-gateway/usage",
    }
)
EXCLUDED: dict[str, str] = {
    "GET /v1/llm-gateway/usage": "months 0000-01 and 9999-12 match the pattern and end in a 500",
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

# The fake provider and the memory ledger, as in tests/conftest.py; no .env, no Langfuse.
app = build_app(
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
