"""Every route a hosted service serves has an exposure class, and the public ones are few."""

import json
from pathlib import Path

import pytest

from cw_mvp.app import CombinedApp
from cw_mvp.dispatch import served_routes
from cw_mvp.exposure import ADMIN, EXPOSURE, INTERNAL, PUBLIC, Exposure, served_publicly
from cw_mvp.registry import REGISTRY

PUBLIC_SPEC = Path(__file__).resolve().parents[4] / "packages/contracts/openapi/public.v1.json"
ENGINE = "/v1/applicability-engine"

RULEBOOK_PUBLIC_READS = {
    "GET /v1/rulebook/rule-versions",
    "GET /v1/rulebook/rule-versions/{rule_version_id}",
    "GET /v1/rulebook/rule-versions/{rule_version_id}/citations",
    "GET /v1/rulebook/entities/resolve",
    "GET /v1/rulebook/entities/{entity_id}",
    "GET /v1/rulebook/entities/{entity_id}/clauses",
    "GET /v1/rulebook/relations",
    "GET /v1/rulebook/clauses/{clause_id}",
    "POST /v1/rulebook/search",
    "GET /v1/changes",
}
"""The rulebook's public reads, exactly, the public API's changes feed among them: every other
rulebook route is admin or internal."""


def test_every_service_has_a_table() -> None:
    assert set(EXPOSURE) == {entry.name for entry in REGISTRY}


@pytest.mark.parametrize("service", sorted(EXPOSURE))
def test_every_served_route_has_a_class_and_every_class_a_route(
    memory_app: CombinedApp, service: str
) -> None:
    served = {f"{method} {path}" for method, path in served_routes(memory_app.services[service])}
    listed = set(EXPOSURE[service])
    assert not sorted(served - listed), f"{service}: routes without an exposure class"
    assert not sorted(listed - served), f"{service}: classed routes it no longer serves"


def test_the_rulebook_serves_only_its_published_reads_to_the_public() -> None:
    public = {key for key, exposure in EXPOSURE["rulebook"].items() if exposure is PUBLIC}
    assert public == RULEBOOK_PUBLIC_READS


def test_every_path_of_the_public_api_is_public() -> None:
    spec = json.loads(PUBLIC_SPEC.read_text("utf-8"))
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if not isinstance(operation, dict):
                continue
            key = f"{method.upper()} {path}"
            assert EXPOSURE[operation["x-service"]].get(key) is PUBLIC, key


def test_service_to_service_routes_stay_internal() -> None:
    for service, key in (
        ("identity", "POST /v1/identity/service-tokens"),
        ("identity", "POST /v1/identity/channel-consents"),
        ("notification", "POST /v1/notification/send"),
        ("notification", "POST /v1/notification/receipts/whatsapp"),
        ("rulebook", "PUT /v1/rulebook/documents/{document_id}"),
        ("llm-gateway", "POST /v1/llm-gateway/completions"),
        ("applicability-engine", f"POST {ENGINE}/businesses/{{business_id}}/decisions"),
        ("eval", "POST /v1/eval/runs"),
    ):
        assert EXPOSURE[service][key] is INTERNAL, key


def test_tenants_read_their_decisions_and_operators_their_eval_runs() -> None:
    engine, runs = EXPOSURE["applicability-engine"], EXPOSURE["eval"]
    assert engine[f"GET {ENGINE}/businesses/{{business_id}}/decisions"] is PUBLIC
    assert engine[f"GET {ENGINE}/decisions/{{decision_id}}"] is PUBLIC
    assert runs["GET /v1/eval/runs"] is ADMIN
    assert runs["GET /v1/eval/runs/{run_id}"] is ADMIN


def test_the_review_queue_is_the_regulatory_teams_and_public_only_in_token_mode() -> None:
    engine = EXPOSURE["applicability-engine"]
    for key in (f"GET {ENGINE}/review-items", f"POST {ENGINE}/review-items/{{item_id}}/resolve"):
        assert engine[key] is ADMIN, key
        assert served_publicly(engine[key], "token")
        assert not served_publicly(engine[key], "dual")
        assert not served_publicly(engine[key], "header")


@pytest.mark.parametrize(
    ("exposure", "mode", "served"),
    [
        (PUBLIC, "header", True),
        (PUBLIC, "token", True),
        (ADMIN, "header", False),
        (ADMIN, "dual", False),
        (ADMIN, "token", True),
        (INTERNAL, "token", False),
        (None, "token", False),
    ],
)
def test_the_public_listener_serves_admin_routes_only_with_tokens(
    exposure: Exposure | None, mode: str, served: bool
) -> None:
    assert served_publicly(exposure, mode) is served  # type: ignore[arg-type]
