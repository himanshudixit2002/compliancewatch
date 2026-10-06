"""Property tests of the rulebook API against its spec (schemathesis).

Schemathesis generates valid and invalid requests from the served schema, which
``test_openapi.py`` pins to the committed spec, and sends them in process with a tenant header
and the write and review tokens of the test settings, so the pipeline's writes and the analyst's
actions get past their token checks. Publishing is switched on, so the publish, withdraw and
sweep routes run their use cases instead of answering 503. Each response must not be a server
error, and its status code, content type and body must be the ones the spec documents.

That app runs in header mode. The writes run again in token mode, where the shared tokens are
refused: the pipeline's writes with a service token holding rulebook:write, and the analyst's
actions with the token of a user holding the analyst, reviewer and admin roles.

Only the operations in ``OPERATIONS`` run: those served when these tests arrived. A change that
adds an operation opts it in here. An operation that cannot pass yet, for a defect or because it
needs a redesign, goes in ``EXCLUDED`` with the reason.
"""

import os
from typing import Any, cast

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import CheckFunction, not_a_server_error
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from domain_kernel.access import REGULATORY_ROLES, Scope
from domain_kernel.ids import TenantId
from py_common.auth.testing import TestIssuer, bearer
from rulebook.main import build_app
from rulebook.testing import REVIEW_TOKEN, WRITE_TOKEN, rulebook_settings

TENANT_ID = "7d0f4d56-2a8e-4c1b-9f3e-5b6a1c2d3e4f"
OPERATIONS = frozenset(
    {
        "GET /health",
        "GET /ready",
        "PUT /v1/rulebook/clauses/embeddings",
        "GET /v1/rulebook/clauses/unembedded",
        "GET /v1/rulebook/clauses/{clause_id}",
        "GET /v1/rulebook/documents/{document_id}",
        "PUT /v1/rulebook/documents/{document_id}",
        "PUT /v1/rulebook/documents/{document_id}/mentions",
        "PUT /v1/rulebook/documents/{document_id}/relation-candidates",
        "GET /v1/rulebook/entities/resolve",
        "GET /v1/rulebook/entities/{entity_id}",
        "GET /v1/rulebook/entities/{entity_id}/clauses",
        "POST /v1/rulebook/maintenance/transitions",
        "GET /v1/rulebook/ping",
        "GET /v1/rulebook/relations",
        "GET /v1/rulebook/review/entities",
        "POST /v1/rulebook/review/entities/decisions",
        "GET /v1/rulebook/review/entities/items",
        "GET /v1/rulebook/review/relations",
        "POST /v1/rulebook/review/relations/{candidate_id}/approve",
        "POST /v1/rulebook/review/relations/{candidate_id}/reject",
        "GET /v1/rulebook/review/stats",
        "GET /v1/rulebook/review/tasks",
        "POST /v1/rulebook/review/tasks/seed",
        "GET /v1/rulebook/review/tasks/{task_id}",
        "POST /v1/rulebook/review/tasks/{task_id}/claim",
        "POST /v1/rulebook/review/tasks/{task_id}/decide",
        "PATCH /v1/rulebook/review/tasks/{task_id}/draft",
        "GET /v1/rulebook/rule-versions",
        "GET /v1/rulebook/rule-versions/{rule_version_id}",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/approve",
        "GET /v1/rulebook/rule-versions/{rule_version_id}/citations",
        "PUT /v1/rulebook/rule-versions/{rule_version_id}/citations",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/publish",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/return",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/submit",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/withdraw",
        "GET /v1/rulebook/rules",
        "GET /v1/rulebook/rules/{rule_key}/versions",
        "POST /v1/rulebook/search",
        "GET /v1/changes",
    }
)
PIPELINE_OPERATIONS = frozenset(
    {
        "PUT /v1/rulebook/clauses/embeddings",
        "PUT /v1/rulebook/documents/{document_id}",
        "PUT /v1/rulebook/documents/{document_id}/mentions",
        "PUT /v1/rulebook/documents/{document_id}/relation-candidates",
    }
)
ANALYST_OPERATIONS = frozenset(
    {
        "POST /v1/rulebook/maintenance/transitions",
        "POST /v1/rulebook/review/entities/decisions",
        "POST /v1/rulebook/review/relations/{candidate_id}/approve",
        "POST /v1/rulebook/review/relations/{candidate_id}/reject",
        "POST /v1/rulebook/review/tasks/seed",
        "POST /v1/rulebook/review/tasks/{task_id}/claim",
        "POST /v1/rulebook/review/tasks/{task_id}/decide",
        "PATCH /v1/rulebook/review/tasks/{task_id}/draft",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/approve",
        "PUT /v1/rulebook/rule-versions/{rule_version_id}/citations",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/publish",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/return",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/submit",
        "POST /v1/rulebook/rule-versions/{rule_version_id}/withdraw",
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
HEADERS = {
    "x-tenant-id": TENANT_ID,
    "x-cw-write-token": WRITE_TOKEN,
    "x-cw-review-token": REVIEW_TOKEN,
}
EXAMPLES = 200 if os.environ.get("HYPOTHESIS_PROFILE") == "nightly" else 25

app = build_app(rulebook_settings(rulebook_publish_enabled=True))
schema = schemathesis.openapi.from_asgi("/openapi.json", app).include(
    func=lambda ctx: ctx.operation.label in OPERATIONS and ctx.operation.label not in EXCLUDED
)

ISSUER = TestIssuer()
PIPELINE_TOKEN = ISSUER.service("pipeline", [Scope.RULEBOOK_WRITE])
ANALYST_TOKEN = ISSUER.user(TenantId.new(), REGULATORY_ROLES, mfa=True)
token_app = build_app(
    rulebook_settings(rulebook_publish_enabled=True, **ISSUER.settings_overrides("token"))
)
pipeline_schema = schemathesis.openapi.from_asgi("/openapi.json", token_app).include(
    func=lambda ctx: ctx.operation.label in PIPELINE_OPERATIONS
)
analyst_schema = schemathesis.openapi.from_asgi("/openapi.json", token_app).include(
    func=lambda ctx: ctx.operation.label in ANALYST_OPERATIONS
)


def test_every_listed_operation_is_served() -> None:
    paths = app.openapi()["paths"]
    labels = {f"{method.upper()} {path}" for path, item in paths.items() for method in item}
    assert labels >= OPERATIONS | EXCLUDED.keys() | PIPELINE_OPERATIONS | ANALYST_OPERATIONS


@schema.parametrize()
# Bodies with patterns and nested models make schemathesis discard many drafts; that is
# expected, not a slow or broken generator, so those two health checks do not apply.
@settings(
    max_examples=EXAMPLES,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
def test_responses_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(headers=HEADERS, checks=CHECKS)


@pipeline_schema.parametrize()
@settings(
    max_examples=EXAMPLES,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
def test_responses_to_the_pipeline_token_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(headers=bearer(PIPELINE_TOKEN), checks=CHECKS)


@analyst_schema.parametrize()
@settings(
    max_examples=EXAMPLES,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
def test_responses_to_an_analyst_token_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(headers=bearer(ANALYST_TOKEN), checks=CHECKS)
