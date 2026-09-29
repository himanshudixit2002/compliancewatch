"""Property tests of the rulebook API against its spec (schemathesis).

Schemathesis generates valid and invalid requests from the served schema, which
``test_openapi.py`` pins to the committed spec, and sends them in process with a tenant header
and the write token of the test settings, so the write routes get past their token check. Each
response must not be a server error, and its status code, content type and body must be the ones
the spec documents.

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

from rulebook.main import build_app
from rulebook.testing import WRITE_TOKEN, rulebook_settings

TENANT_ID = "7d0f4d56-2a8e-4c1b-9f3e-5b6a1c2d3e4f"
OPERATIONS = frozenset(
    {
        "GET /health",
        "GET /ready",
        "GET /v1/rulebook/documents/{document_id}",
        "PUT /v1/rulebook/documents/{document_id}",
        "PUT /v1/rulebook/documents/{document_id}/mentions",
        "PUT /v1/rulebook/documents/{document_id}/relation-candidates",
        "GET /v1/rulebook/ping",
        "GET /v1/rulebook/review/entities",
        "POST /v1/rulebook/review/entities/decisions",
        "GET /v1/rulebook/review/entities/items",
        "GET /v1/rulebook/review/relations",
        "POST /v1/rulebook/review/relations/{candidate_id}/approve",
        "POST /v1/rulebook/review/relations/{candidate_id}/reject",
        "GET /v1/rulebook/rules",
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

app = build_app(rulebook_settings())
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
    case.call_and_validate(
        headers={"x-tenant-id": TENANT_ID, "x-cw-write-token": WRITE_TOKEN}, checks=CHECKS
    )
