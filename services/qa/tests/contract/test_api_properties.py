"""Property tests of the qa API against its spec (schemathesis).

Schemathesis generates valid and invalid requests from the served schema, which
``test_openapi.py`` pins to the committed spec, and sends them in process with a tenant header
and a fixed request id. The app runs on the memory fakes with one published test rule, its cited
clause and a business with a profile and an obligation, and with the KAG layer on, so a question
can reach every layer. Every model call the question makes carries that request id, and the
scripted model answers it: the planner's reply is not a plan, so the KAG layer falls through,
and the answerer's reply says the question is not covered. Each response must not be a server
error, and its status code, content type and body must be the ones the spec documents.

Only the operations in ``OPERATIONS`` run: those served when these tests arrived. A change that
adds an operation opts it in here. An operation that cannot pass yet, for a defect or because it
needs a redesign, goes in ``EXCLUDED`` with the reason.
"""

import os
from datetime import date
from typing import Any, cast
from uuid import UUID

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import CheckFunction, not_a_server_error
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from domain_kernel.ids import BusinessId, TenantId
from ontology import load as load_ontology
from qa.main import ANSWER_PROMPT, PLAN_PROMPT, build_app
from qa.testing import (
    MemoryObligations,
    MemoryProfiles,
    MemoryRulebook,
    ScriptedProvider,
    answer_text,
    memory_ports,
    qa_settings,
)
from qa.wiring import Ports

TENANT_ID = "7d0f4d56-2a8e-4c1b-9f3e-5b6a1c2d3e4f"
REQUEST_ID = "property-question"
BUSINESS = BusinessId(UUID(int=10))
QUOTE = "furnish the return in FORM GSTR-3B for a month by the 20th day"
OPERATIONS = frozenset(
    {
        "GET /health",
        "GET /ready",
        "POST /v1/qa/ask",
        "GET /v1/qa/ping",
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


def _rulebook() -> MemoryRulebook:
    """One published test rule citing one clause of a test notice, not a regulator's text."""
    rulebook = MemoryRulebook()
    clause = rulebook.add_clause(
        "A registered person shall " + QUOTE + " of the month succeeding that month.",
        external_ref="TEST-01",
        published_at=date(2026, 1, 5),
    )
    rule = rulebook.add_version(
        "gstr3b_monthly", effective_from=date(2026, 4, 1), title="File FORM GSTR-3B every month"
    )
    rulebook.cite(rule, clause, QUOTE)
    return rulebook


def _provider() -> ScriptedProvider:
    provider = ScriptedProvider()
    provider.add(REQUEST_ID, "@".join(PLAN_PROMPT), "not a plan")
    provider.add(REQUEST_ID, "@".join(ANSWER_PROMPT), answer_text("Not covered.", covered=False))
    return provider


def _ports() -> Ports:
    rulebook = _rulebook()
    rule = next(iter(rulebook.versions.values()))
    tenant = TenantId(UUID(TENANT_ID))
    profiles = MemoryProfiles()
    profiles.add(tenant, BUSINESS, {"registration_type": "regular"})
    obligations = MemoryObligations()
    obligations.add(tenant, BUSINESS, rule, "File GSTR-3B (2026-04)", date(2026, 5, 20))
    return memory_ports(
        rulebook=rulebook,
        search=rulebook,
        profiles=profiles,
        obligations=obligations,
        provider=_provider(),
    )


app = build_app(qa_settings(qa_kag_enabled=True), ports=_ports(), ontology=load_ontology())
schema = schemathesis.openapi.from_asgi("/openapi.json", app).include(
    func=lambda ctx: ctx.operation.label in OPERATIONS and ctx.operation.label not in EXCLUDED
)


def test_every_listed_operation_is_served() -> None:
    paths = app.openapi()["paths"]
    labels = {f"{method.upper()} {path}" for path, item in paths.items() for method in item}
    assert labels >= OPERATIONS | EXCLUDED.keys()


@schema.parametrize()
# Bodies with patterns and nested models make schemathesis discard many drafts; that is
# expected, not a slow or broken generator, so those two health checks do not apply.
@settings(
    max_examples=EXAMPLES,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
def test_responses_conform_to_the_spec(case: schemathesis.Case[Any]) -> None:
    case.call_and_validate(
        headers={"x-tenant-id": TENANT_ID, "x-request-id": REQUEST_ID}, checks=CHECKS
    )
