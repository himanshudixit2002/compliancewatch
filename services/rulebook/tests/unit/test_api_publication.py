"""The citation, review and publish routes over HTTP: the review token, the publish flag, the
problem types, and a version taken from draft to published."""

from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.documents import clause_id_for, document_id_for
from domain_kernel.ids import RuleVersionId
from domain_kernel.knowledge import RelationKind, RuleRelation
from domain_kernel.status import RuleVersionStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app
from rulebook.testing import REVIEW_TOKEN, WRITE_TOKEN, rulebook_settings

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOC = document_id_for(DIGEST)
CLAUSE = clause_id_for(DOC, "en.p1")
BASE = "/v1/rulebook"
TEXT = "hereby extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"
QUOTE = "extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
REVIEW = {"x-cw-review-token": REVIEW_TOKEN}
ANALYST = str(UUID(int=11))
REVIEWER = str(UUID(int=12))
PROBLEM = "urn:compliancewatch:problem:"


@pytest.fixture
def publishing_app() -> FastAPI:
    return build_app(rulebook_settings(rulebook_publish_enabled=True))


@pytest.fixture
def publishing(publishing_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(publishing_app) as test_client:
        yield test_client


def store_of(app: FastAPI, client: TestClient) -> MemoryKnowledgeStore:
    body = {
        "source_id": str(UUID(int=7)),
        "sha256": DIGEST,
        "regulator": "CBIC",
        "doc_type": "notification",
        "url": "https://example.invalid/n.pdf",
        "language": "en",
        "media_type": "application/pdf",
        "parser_version": "pdf@1",
        "published_at": "2026-03-28",
        "fetched_at": "2026-09-28T06:00:00Z",
        "clauses": [{"clause_ref": "en.p1", "text": TEXT, "page": 1}],
    }
    assert client.put(f"{BASE}/documents/{DOC}", json=body, headers=WRITE).status_code == 201
    memory: MemoryKnowledgeStore = app.state.wiring.unit_of_work
    return memory


def cite(client: TestClient, version: RuleVersionId, quote: str = QUOTE) -> Any:
    return client.put(
        f"{BASE}/rule-versions/{version}/citations",
        json={"citations": [{"clause_id": str(CLAUSE), "quote": quote}]},
        headers=REVIEW,
    )


def step(client: TestClient, version: RuleVersionId, action: str, **body: object) -> Any:
    return client.post(
        f"{BASE}/rule-versions/{version}/{action}",
        json={"actor_id": ANALYST, **body},
        headers=REVIEW,
    )


ROUTES = [
    (
        "put",
        "/rule-versions/{id}/citations",
        {"citations": [{"clause_id": str(CLAUSE), "quote": "q"}]},
    ),
    ("post", "/rule-versions/{id}/submit", {"actor_id": ANALYST}),
    ("post", "/rule-versions/{id}/return", {"actor_id": ANALYST}),
    ("post", "/rule-versions/{id}/approve", {"actor_id": ANALYST}),
    ("post", "/rule-versions/{id}/publish", {"actor_id": ANALYST}),
    ("post", "/rule-versions/{id}/withdraw", {"actor_id": ANALYST}),
    ("post", "/maintenance/transitions", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_needs_the_review_token(
    client: TestClient, method: str, path: str, body: dict[str, object]
) -> None:
    url = BASE + path.format(id=UUID(int=1))
    for headers in ({}, {"x-cw-review-token": "wrong"}, WRITE, {"x-cw-review-token": WRITE_TOKEN}):
        response = client.request(method, url, json=body, headers=headers)
        assert (response.status_code, response.json()["type"]) == (
            401,
            PROBLEM + "rulebook-review-token-invalid",
        )


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_is_closed_without_a_review_token(
    method: str, path: str, body: dict[str, object]
) -> None:
    with TestClient(build_app(rulebook_settings(rulebook_review_token=None))) as closed:
        response = closed.request(
            method, BASE + path.format(id=UUID(int=1)), json=body, headers={**WRITE, **REVIEW}
        )
    assert (response.status_code, response.json()["type"]) == (
        503,
        PROBLEM + "rulebook-reviews-disabled",
    )


@pytest.mark.parametrize("path", ["/rule-versions/{id}/publish", "/rule-versions/{id}/withdraw"])
def test_publishing_answers_503_while_the_flag_is_off(client: TestClient, path: str) -> None:
    response = client.post(
        BASE + path.format(id=UUID(int=1)), json={"actor_id": ANALYST}, headers=REVIEW
    )
    assert response.status_code == 503
    assert response.json()["type"] == PROBLEM + "rulebook-publishing-disabled"
    sweep = client.post(f"{BASE}/maintenance/transitions", json={}, headers=REVIEW)
    assert (sweep.status_code, sweep.json()["type"]) == (
        503,
        PROBLEM + "rulebook-publishing-disabled",
    )


def test_review_works_while_publishing_is_off(app: FastAPI, client: TestClient) -> None:
    store = store_of(app, client)
    _, version = store.add_rule("gstr3b_extension", title="Extension")
    assert cite(client, version).status_code == 200
    assert step(client, version, "submit").json()["status"] == "in_review"
    assert step(client, version, "approve").json()["status"] == "approved"


def test_a_version_goes_from_draft_to_published(
    publishing_app: FastAPI, publishing: TestClient
) -> None:
    store = store_of(publishing_app, publishing)
    rule_id, version = store.add_rule(
        "gstr3b_extension", title="Extension", effective_from=date(2026, 4, 1)
    )
    cited = cite(publishing, version)
    assert cited.status_code == 200
    body = cited.json()
    assert (body["added"], body["unchanged"]) == (1, 0)
    assert body["citations"][0]["verified"] is True
    assert cite(publishing, version).json()["unchanged"] == 1

    submitted = step(publishing, version, "submit", high_impact=True, note="two needed")
    assert submitted.status_code == 200
    assert submitted.json()["high_impact"] is True
    assert submitted.json()["required_approvals"] == 2
    first = step(publishing, version, "approve")
    assert (first.json()["status"], first.json()["approved_by"]) == ("in_review", [ANALYST])
    twice = step(publishing, version, "approve")
    assert (twice.status_code, twice.json()["type"]) == (
        409,
        PROBLEM + "rulebook-duplicate-approver",
    )
    second = publishing.post(
        f"{BASE}/rule-versions/{version}/approve", json={"actor_id": REVIEWER}, headers=REVIEW
    )
    assert second.json()["status"] == "approved"
    assert second.json()["seed_status"] == "reviewed"

    published = step(publishing, version, "publish")
    assert published.status_code == 200
    out = published.json()
    assert out["status"] == "published"
    assert out["rule_id"] == str(rule_id)
    assert out["approved_by"] == sorted([ANALYST, REVIEWER])
    assert out["replacements"] == []
    assert out["deadline_changes"] == []
    (event,) = out["events"]
    assert event["topic"] == "rule.published"
    assert event["correlation_id"] == out["correlation_id"]
    assert event["causation_id"] is None

    detail = publishing.get(f"{BASE}/rule-versions/{version}").json()
    assert (detail["status"], detail["high_impact"]) == ("published", True)
    assert detail["published_at"] is not None
    assert [type(e).topic for e in store.events()] == ["rule.published"]

    withdrawn = step(publishing, version, "withdraw", note="rescinded")
    assert withdrawn.json()["status"] == "withdrawn"
    assert [e["topic"] for e in withdrawn.json()["events"]] == ["rule.withdrawn"]
    sweep = publishing.post(f"{BASE}/maintenance/transitions", json={}, headers=REVIEW)
    assert sweep.status_code == 200
    assert sweep.json()["transitions"] == []


def test_problem_types_of_the_flow(publishing_app: FastAPI, publishing: TestClient) -> None:
    store = store_of(publishing_app, publishing)
    _, version = store.add_rule("gstr3b_extension", title="Extension")
    unknown = step(publishing, RuleVersionId(UUID(int=5)), "submit")
    assert (unknown.status_code, unknown.json()["type"]) == (
        404,
        PROBLEM + "rulebook-rule-version-not-found",
    )
    wrong = cite(publishing, version, "extends the due date for March, 2027")
    assert (wrong.status_code, wrong.json()["type"]) == (
        422,
        PROBLEM + "rulebook-citation-not-verified",
    )
    skipped = step(publishing, version, "approve")
    assert (skipped.status_code, skipped.json()["type"]) == (409, PROBLEM + "invalid-transition")
    step(publishing, version, "submit")
    step(publishing, version, "approve")
    uncited = step(publishing, version, "publish")
    assert (uncited.status_code, uncited.json()["type"]) == (
        409,
        PROBLEM + "rulebook-citations-missing",
    )
    ahead = publishing.post(
        f"{BASE}/maintenance/transitions", json={"as_of": "2999-01-01"}, headers=REVIEW
    )
    assert (ahead.status_code, ahead.json()["type"]) == (422, PROBLEM + "invariant-violation")
    _, live = store.add_rule("gstr1_monthly", status=RuleVersionStatus.PUBLISHED)
    frozen = cite(publishing, live)
    assert (frozen.status_code, frozen.json()["type"]) == (
        409,
        PROBLEM + "rulebook-rule-version-not-editable",
    )
    empty = publishing.put(
        f"{BASE}/rule-versions/{version}/citations", json={"citations": []}, headers=REVIEW
    )
    assert empty.status_code == 422


def test_a_version_waiting_to_replace_another_is_not_withdrawn(
    publishing_app: FastAPI, publishing: TestClient
) -> None:
    store = store_of(publishing_app, publishing)
    _, old = store.add_rule("gstr3b_monthly", status=RuleVersionStatus.PUBLISHED)
    new = store.add_version("gstr3b_monthly", title="Amended", effective_from=date(2999, 1, 1))
    with store() as uow:
        uow.relations.add(
            RuleRelation(new, RelationKind.SUPERSEDES, old, CLAUSE),
            relation_id=uuid4(),
            candidate_id=None,
        )
    cite(publishing, new)
    for action in ("submit", "approve", "publish"):
        assert step(publishing, new, action).status_code == 200
    refused = step(publishing, new, "withdraw")
    assert (refused.status_code, refused.json()["type"]) == (
        409,
        PROBLEM + "rulebook-replacements-pending",
    )
