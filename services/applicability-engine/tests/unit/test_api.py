"""The routes on the memory store: evaluating with an Idempotency-Key, the problems, the
paginated listing of a business's decisions and reading one."""

from collections.abc import Sequence
from datetime import date
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicability_engine.domain.errors import DependencyUnavailableError
from applicability_engine.domain.model import RuleInForce, RuleVersionSpec
from applicability_engine.main import build_app
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import (
    BUSINESS,
    OTHER_TENANT,
    TENANT,
    MemoryProfiles,
    MemoryRulebook,
    rule_version,
)
from applicability_engine.wiring import Readers
from domain_kernel.ids import RuleVersionId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus

DECISIONS = f"/v1/applicability-engine/businesses/{BUSINESS}/decisions"
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
FREE_TEXT = {"attribute": "business_category", "free_text": "Runs a restaurant in a hotel"}
FIELDS = {
    "decision_id",
    "business_id",
    "rule_version_id",
    "result",
    "confidence",
    "needs_review",
    "profile_version",
    "as_of_fy",
    "trigger",
    "decided_at",
    "evaluated",
}


def headers(tenant: object = TENANT, key: str | None = None) -> dict[str, str]:
    return {"x-tenant-id": str(tenant), "Idempotency-Key": key or str(uuid4())}


def evaluate(client: TestClient, rule: RuleVersionSpec, **extra: object) -> dict[str, object]:
    response = client.post(
        DECISIONS, json={"rule_version_id": str(rule.rule_version_id), **extra}, headers=headers()
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def test_evaluating_stores_and_answers_the_decision(
    client: TestClient, profiles: MemoryProfiles, rulebook: MemoryRulebook
) -> None:
    profiles.put({"registration_type": "regular"}, version=2)
    rule = rulebook.put(rule_version({"all_of": [REGULAR, FREE_TEXT]}))
    body = evaluate(client, rule, fy="2025-26")
    assert set(body) == FIELDS
    assert (body["business_id"], body["rule_version_id"]) == (
        str(BUSINESS),
        str(rule.rule_version_id),
    )
    assert (body["result"], body["confidence"], body["needs_review"]) == ("unsure", 0.0, True)
    assert (body["profile_version"], body["trigger"]) == (2, "manual")
    assert body["evaluated"] == [
        {
            "attribute": "registration_type",
            "kind": "structured",
            "description": "registration_type = regular",
            "predicate": REGULAR,
            "outcome": "applies",
            "confidence": 1.0,
            "reason": "registration_type = regular holds",
            "needs_review": False,
        },
        {
            "attribute": "business_category",
            "kind": "free_text",
            "description": 'free text: "Runs a restaurant in a hotel"',
            "predicate": FREE_TEXT,
            "outcome": "unsure",
            "confidence": 0.0,
            "reason": "needs judgement: Runs a restaurant in a hotel",
            "needs_review": True,
        },
    ]
    assert profiles.asked[-1] is not None
    assert profiles.asked[-1].label == "2025-26"

    read = client.get(
        f"/v1/applicability-engine/decisions/{body['decision_id']}", headers=headers()
    )
    assert read.status_code == 200
    assert read.json() == body


def test_a_retry_with_the_same_key_replays_the_first_decision(
    app: FastAPI, client: TestClient, profiles: MemoryProfiles, rulebook: MemoryRulebook
) -> None:
    profiles.put({"registration_type": "regular"})
    rule = rulebook.put(rule_version(REGULAR))
    payload = {"rule_version_id": str(rule.rule_version_id)}
    first = client.post(DECISIONS, json=payload, headers=headers(key="evaluate-0001"))
    again = client.post(DECISIONS, json=payload, headers=headers(key="evaluate-0001"))
    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert again.headers["Idempotent-Replayed"] == "true"
    assert len(app.state.wiring.unit_of_work.decisions) == 1

    other_body = client.post(
        DECISIONS, json={**payload, "fy": "2024-25"}, headers=headers(key="evaluate-0001")
    )
    assert other_body.status_code == 422
    missing = client.post(DECISIONS, json=payload, headers={"x-tenant-id": str(TENANT)})
    assert missing.status_code == 428


def test_the_problems_of_evaluating(
    client: TestClient, profiles: MemoryProfiles, rulebook: MemoryRulebook
) -> None:
    profiles.put({"registration_type": "regular"})
    published = rulebook.put(rule_version(REGULAR))
    draft = rulebook.put(rule_version(REGULAR, status=RuleVersionStatus.DRAFT))

    def problem(rule_version_id: object, **extra: object) -> tuple[int, str]:
        response = client.post(
            DECISIONS, json={"rule_version_id": str(rule_version_id), **extra}, headers=headers()
        )
        assert response.headers["content-type"] == "application/problem+json"
        return response.status_code, str(response.json()["type"]).rsplit(":", 1)[-1]

    assert problem(RuleVersionId.new()) == (404, "applicability-rule-version-not-found")
    assert problem(draft.rule_version_id) == (409, "applicability-rule-version-not-published")
    assert problem(published.rule_version_id, fy="2025-2026")[0] == 422
    assert problem(published.rule_version_id, fy="2025-27") == (422, "invariant-violation")
    other_business = client.post(
        f"/v1/applicability-engine/businesses/{uuid4()}/decisions",
        json={"rule_version_id": str(published.rule_version_id)},
        headers=headers(),
    )
    assert other_business.status_code == 404
    assert other_business.json()["type"].endswith("applicability-business-not-found")
    no_tenant = client.post(
        DECISIONS,
        json={"rule_version_id": str(published.rule_version_id)},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert no_tenant.status_code == 401
    assert no_tenant.json()["type"].endswith("applicability-tenant-required")


class Unavailable:
    def rule_version(self, rule_version_id: RuleVersionId) -> RuleVersionSpec | None:
        raise DependencyUnavailableError("rulebook answered 502: bad gateway")

    def rules_in_force(self, as_of: date, level: AttributeLevel) -> Sequence[RuleInForce]:
        raise DependencyUnavailableError("rulebook answered 502: bad gateway")


def test_an_unavailable_dependency_is_a_503_and_frees_the_key(profiles: MemoryProfiles) -> None:
    settings = ApplicabilityEngineSettings(
        _env_file=None, service_name="applicability-engine", applicability_engine_store="memory"
    )
    app = build_app(settings, readers=Readers(profiles=profiles, rulebook=Unavailable()))
    with TestClient(app) as client:
        payload = {"rule_version_id": str(RuleVersionId.new())}
        for _ in range(2):
            response = client.post(DECISIONS, json=payload, headers=headers(key="evaluate-0002"))
            assert response.status_code == 503
            assert response.json()["type"].endswith("applicability-dependency-unavailable")


def test_the_listing_pages_newest_first_and_is_scoped_to_the_tenant(
    client: TestClient, profiles: MemoryProfiles, rulebook: MemoryRulebook
) -> None:
    profiles.put({"registration_type": "regular"})
    gst = rulebook.put(rule_version(REGULAR))
    other = rulebook.put(rule_version(FREE_TEXT))
    made = [evaluate(client, rule)["decision_id"] for rule in (gst, other, gst)]

    first = client.get(DECISIONS, params={"limit": 2}, headers=headers())
    assert first.status_code == 200
    page = first.json()
    assert [item["decision_id"] for item in page["items"]] == [made[2], made[1]]
    assert page["next_cursor"]
    rest = client.get(
        DECISIONS, params={"limit": 2, "cursor": page["next_cursor"]}, headers=headers()
    ).json()
    assert [item["decision_id"] for item in rest["items"]] == [made[0]]
    assert rest["next_cursor"] is None

    of_gst = client.get(
        DECISIONS, params={"rule_version_id": str(gst.rule_version_id)}, headers=headers()
    ).json()
    assert [item["decision_id"] for item in of_gst["items"]] == [made[2], made[0]]

    assert client.get(DECISIONS, headers=headers(OTHER_TENANT)).json() == {
        "items": [],
        "next_cursor": None,
    }
    bad = client.get(DECISIONS, params={"cursor": "not-a-cursor"}, headers=headers())
    assert bad.status_code == 422
    assert bad.json()["type"].endswith("pagination-cursor-invalid")
    elsewhere = client.get(
        f"/v1/applicability-engine/decisions/{made[0]}", headers=headers(OTHER_TENANT)
    )
    assert elsewhere.status_code == 404
    assert elsewhere.json()["type"].endswith("applicability-decision-not-found")
