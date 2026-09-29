"""The knowledge and review routes over HTTP: write token, bodies, statuses."""

from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.documents import document_id_for
from domain_kernel.status import RuleVersionStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.testing import REVIEW_TOKEN, WRITE_TOKEN

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOC = document_id_for(DIGEST)
BASE = "/v1/rulebook"
AUTH = {"x-cw-write-token": WRITE_TOKEN}
REVIEW = {"x-cw-review-token": REVIEW_TOKEN}
P3 = "hereby extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"


@pytest.fixture
def registered(client: TestClient) -> TestClient:
    body = {
        "source_id": str(UUID(int=7)),
        "sha256": DIGEST,
        "regulator": "CBIC",
        "doc_type": "notification",
        "url": "https://example.invalid/n.pdf",
        "language": "en",
        "media_type": "application/pdf",
        "parser_version": "pdf@1",
        "fetched_at": "2026-09-28T06:00:00Z",
        "clauses": [{"clause_ref": "en.p3", "text": P3}],
    }
    assert client.put(f"{BASE}/documents/{DOC}", json=body, headers=AUTH).status_code == 201
    return client


def form_mention(**overrides: Any) -> dict[str, Any]:
    start = P3.index("FORM GSTR-3B")
    values: dict[str, Any] = {
        "clause_ref": "en.p3",
        "entity_type": "form",
        "text": "FORM GSTR-3B",
        "span_start": start,
        "span_end": start + 12,
        "proposed_name": "GSTR-3B",
    }
    values.update(overrides)
    return values


def candidate(**overrides: Any) -> dict[str, Any]:
    start = P3.index("FORM GSTR-3B")
    values: dict[str, Any] = {
        "relation": "extends_deadline",
        "target_type": "form",
        "target_name": "GSTR-3B",
        "target_clause_ref": "en.p3",
        "target_span_start": start,
        "target_span_end": start + 12,
        "evidence_clause_ref": "en.p3",
        "evidence_quote": "hereby extends the due date",
        "quote_score": 1.0,
        "period_label": "2026-03",
        "new_due_on": "2026-04-21",
        "confidence": 0.9,
        "needs_review": False,
    }
    values.update(overrides)
    return values


def test_mentions_are_aligned_and_queued(registered: TestClient) -> None:
    response = registered.put(
        f"{BASE}/documents/{DOC}/mentions",
        json={"extractor": "grammar@1", "mentions": [form_mention()]},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json() == {"aligned": 0, "queued": 1, "unchanged": 0}
    groups = registered.get(f"{BASE}/review/entities").json()
    assert [(g["entity_type"], g["proposed_name"], g["open_count"]) for g in groups] == [
        ("form", "GSTR-3B", 1)
    ]
    assert groups[0]["examples"][0]["reason"] == "no_match"


@pytest.mark.parametrize(
    ("mention", "slug"),
    [
        (form_mention(span_start=0, span_end=12), "rulebook-mention-span-mismatch"),
        (form_mention(proposed_name="gstr 3b"), "rulebook-name-not-canonical"),
        (form_mention(clause_ref="en.p9"), "rulebook-clause-not-found"),
    ],
)
def test_bad_mentions_are_422(registered: TestClient, mention: dict[str, Any], slug: str) -> None:
    response = registered.put(
        f"{BASE}/documents/{DOC}/mentions",
        json={"extractor": "grammar@1", "mentions": [mention]},
        headers=AUTH,
    )
    assert response.status_code == 422
    assert response.json()["type"].endswith(slug)


def test_a_backward_span_is_a_validation_error(registered: TestClient) -> None:
    response = registered.put(
        f"{BASE}/documents/{DOC}/mentions",
        json={"extractor": "grammar@1", "mentions": [form_mention(span_start=5, span_end=5)]},
        headers=AUTH,
    )
    assert response.status_code == 422


def test_mentions_of_an_unknown_document_are_404(registered: TestClient) -> None:
    response = registered.put(
        f"{BASE}/documents/{UUID(int=1)}/mentions",
        json={"extractor": "grammar@1", "mentions": [form_mention()]},
        headers=AUTH,
    )
    assert response.status_code == 404


def test_deciding_a_group_creates_the_entity(registered: TestClient) -> None:
    registered.put(
        f"{BASE}/documents/{DOC}/mentions",
        json={"extractor": "grammar@1", "mentions": [form_mention()]},
        headers=AUTH,
    )
    decision = {
        "entity_type": "form",
        "proposed_name": "GSTR-3B",
        "decision": "create_entity",
        "decided_by": "analyst",
    }
    response = registered.post(f"{BASE}/review/entities/decisions", json=decision, headers=REVIEW)
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["resolution"], body["items_closed"]) == ("resolved", "created", 1)
    again = registered.post(f"{BASE}/review/entities/decisions", json=decision, headers=REVIEW)
    assert again.status_code == 409
    missing = {**decision, "proposed_name": "GSTR-9"}
    assert (
        registered.post(
            f"{BASE}/review/entities/decisions", json=missing, headers=REVIEW
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "decision",
    [
        {"decision": "add_alias"},
        {"decision": "reject"},
        {"decision": "reject", "reject_reason": "because"},
    ],
)
def test_a_decision_needs_what_it_names(registered: TestClient, decision: dict[str, str]) -> None:
    body = {"entity_type": "form", "proposed_name": "GSTR-3B", "decided_by": "a", **decision}
    response = registered.post(f"{BASE}/review/entities/decisions", json=body, headers=REVIEW)
    assert response.status_code == 422


def test_candidates_are_staged_listed_and_approved(app: FastAPI, registered: TestClient) -> None:
    store: MemoryKnowledgeStore = app.state.wiring.unit_of_work
    _, new_version = store.add_rule("gstr3b_extension")
    _, affected = store.add_rule("gstr3b_monthly", status=RuleVersionStatus.PUBLISHED)
    staged = registered.put(
        f"{BASE}/documents/{DOC}/relation-candidates",
        json={
            "extractor": "extraction.rule_relations@1",
            "model": "scripted/golden",
            "outcome": "ok",
            "candidates": [candidate(rule_key="gstr3b_monthly")],
            "run_issues": [{"code": "detector_relation_missing", "detail": "none"}],
        },
        headers=AUTH,
    )
    assert staged.status_code == 200
    (candidate_id,) = staged.json()["candidate_ids"]
    listed = registered.get(f"{BASE}/review/relations").json()
    assert [c["candidate_id"] for c in listed] == [candidate_id]
    assert listed[0]["target_rule_key"] == "gstr3b_monthly"
    assert listed[0]["new_due_on"] == "2026-04-21"
    assert [issue["code"] for issue in listed[0]["issues"]] == ["target_unaligned"]

    approve = registered.post(
        f"{BASE}/review/relations/{candidate_id}/approve",
        json={"from_rule_version_id": str(new_version), "decided_by": "analyst"},
        headers=REVIEW,
    )
    assert approve.status_code == 422
    assert approve.json()["type"].endswith("rulebook-target-version-required")
    approve = registered.post(
        f"{BASE}/review/relations/{candidate_id}/approve",
        json={
            "from_rule_version_id": str(new_version),
            "target_rule_version_id": str(affected),
            "decided_by": "analyst",
        },
        headers=REVIEW,
    )
    assert approve.status_code == 200
    assert approve.json()["candidate_id"] == candidate_id
    again = registered.post(
        f"{BASE}/review/relations/{candidate_id}/reject",
        json={"reason": "duplicate", "decided_by": "analyst"},
        headers=REVIEW,
    )
    assert again.status_code == 409
    approved = registered.get(f"{BASE}/review/relations", params={"status": "approved"}).json()
    assert approved[0]["status"] == "approved"


def test_a_candidate_can_be_rejected(registered: TestClient) -> None:
    staged = registered.put(
        f"{BASE}/documents/{DOC}/relation-candidates",
        json={"extractor": "p@1", "outcome": "ok", "candidates": [candidate()]},
        headers=AUTH,
    )
    (candidate_id,) = staged.json()["candidate_ids"]
    rejected = registered.post(
        f"{BASE}/review/relations/{candidate_id}/reject",
        json={"reason": "wrong_target", "decided_by": "analyst", "note": "cites only"},
        headers=REVIEW,
    )
    assert rejected.status_code == 200
    assert (rejected.json()["status"], rejected.json()["reject_reason"]) == (
        "rejected",
        "wrong_target",
    )
    unknown = registered.post(
        f"{BASE}/review/relations/{UUID(int=3)}/reject",
        json={"reason": "wrong_target", "decided_by": "analyst"},
        headers=REVIEW,
    )
    assert unknown.status_code == 404


def test_a_detail_on_the_wrong_kind_is_rejected(registered: TestClient) -> None:
    response = registered.put(
        f"{BASE}/documents/{DOC}/relation-candidates",
        json={
            "extractor": "p@1",
            "outcome": "ok",
            "candidates": [candidate(relation="refers_to")],
        },
        headers=AUTH,
    )
    assert response.status_code == 422


def test_rules_are_listed(app: FastAPI, client: TestClient) -> None:
    store: MemoryKnowledgeStore = app.state.wiring.unit_of_work
    store.add_rule("gstr1_monthly", title="GSTR-1 monthly")
    rules = client.get(f"{BASE}/rules").json()
    assert [(r["rule_key"], r["title"]) for r in rules] == [("gstr1_monthly", "GSTR-1 monthly")]


PIPELINE_WRITES = [
    ("put", f"/documents/{DOC}"),
    ("put", f"/documents/{DOC}/mentions"),
    ("put", f"/documents/{DOC}/relation-candidates"),
    ("put", "/clauses/embeddings"),
]
ANALYST_ACTIONS = [
    ("post", "/review/entities/decisions"),
    ("post", f"/review/relations/{UUID(int=1)}/approve"),
    ("post", f"/review/relations/{UUID(int=1)}/reject"),
]


@pytest.mark.parametrize(("method", "path"), PIPELINE_WRITES)
def test_pipeline_writes_need_the_write_token(client: TestClient, method: str, path: str) -> None:
    for headers in ({}, REVIEW, {"x-cw-write-token": REVIEW_TOKEN}):
        response = client.request(method, f"{BASE}{path}", json={}, headers=headers)
        assert response.status_code == 401
        assert response.json()["type"].endswith("rulebook-write-token-invalid")


@pytest.mark.parametrize(("method", "path"), ANALYST_ACTIONS)
def test_analyst_actions_need_the_review_token(client: TestClient, method: str, path: str) -> None:
    for headers in ({}, AUTH, {"x-cw-review-token": WRITE_TOKEN}):
        response = client.request(method, f"{BASE}{path}", json={}, headers=headers)
        assert response.status_code == 401
        assert response.json()["type"].endswith("rulebook-review-token-invalid")


def test_an_unqualified_group_is_decided_by_its_items(registered: TestClient) -> None:
    start = P3.index("FORM GSTR-3B")
    bare = form_mention(
        entity_type="section", text=P3[start : start + 4], span_end=start + 4, proposed_name="4"
    )
    registered.put(
        f"{BASE}/documents/{DOC}/mentions",
        json={"extractor": "grammar@1", "mentions": [bare]},
        headers=AUTH,
    )
    items = registered.get(
        f"{BASE}/review/entities/items", params={"entity_type": "section", "proposed_name": "4"}
    ).json()
    assert len(items) == 1
    body = {
        "entity_type": "section",
        "proposed_name": "4",
        "decision": "reject",
        "reject_reason": "text_artifact",
        "decided_by": "analyst",
    }
    unnamed = registered.post(f"{BASE}/review/entities/decisions", json=body, headers=REVIEW)
    assert unnamed.status_code == 422
    named = registered.post(
        f"{BASE}/review/entities/decisions",
        json={**body, "review_ids": [items[0]["review_id"]]},
        headers=REVIEW,
    )
    assert named.status_code == 200
    assert named.json()["items_closed"] == 1


def test_a_backward_candidate_span_is_a_validation_error(registered: TestClient) -> None:
    response = registered.put(
        f"{BASE}/documents/{DOC}/relation-candidates",
        json={
            "extractor": "p@1",
            "outcome": "ok",
            "candidates": [candidate(target_span_start=10, target_span_end=10)],
        },
        headers=AUTH,
    )
    assert response.status_code == 422
