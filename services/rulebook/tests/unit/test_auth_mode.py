"""Rulebook writes in header, dual and token mode: the pipeline's writes by the write token or
rulebook:write, an analyst's actions by the review token or the route's roles, and the signed-in
user recorded as who decided or acted."""

from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.documents import clause_id_for, document_id_for
from domain_kernel.ids import RuleVersionId, TenantId, UserId
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app
from rulebook.testing import REVIEW_TOKEN, WRITE_TOKEN, rulebook_settings

ISSUER = TestIssuer()
BASE = "/v1/rulebook"
DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOC = document_id_for(DIGEST)
CLAUSE = clause_id_for(DOC, "en.p1")
TEXT = "hereby extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"
QUOTE = "extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
REVIEW = {"x-cw-review-token": REVIEW_TOKEN}
INTERNAL = TenantId.new()
ANALYST_ID, REVIEWER_ID, OTHER_REVIEWER_ID = UserId.new(), UserId.new(), UserId.new()
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True, user_id=ANALYST_ID))
REVIEWER = bearer(ISSUER.user(INTERNAL, [Role.REVIEWER], mfa=True, user_id=REVIEWER_ID))
OTHER_REVIEWER = bearer(ISSUER.user(INTERNAL, [Role.REVIEWER], mfa=True, user_id=OTHER_REVIEWER_ID))
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True))
OWNER = bearer(ISSUER.user(TenantId.new(), [Role.OWNER]))
PIPELINE = bearer(ISSUER.service("pipeline", [Scope.RULEBOOK_WRITE, Scope.LLM_CALL]))
QA = bearer(ISSUER.service("qa", [Scope.LLM_CALL, Scope.TENANT_ACT]))
ASSERTED = str(UUID(int=99))
"""An actor id a body asserts; a signed-in user's token overrides it."""
DOCUMENT = {
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


def app_in(mode: AuthMode, **overrides: Any) -> FastAPI:
    return build_app(
        rulebook_settings(
            rulebook_publish_enabled=True, **ISSUER.settings_overrides(mode), **overrides
        )
    )


def client_in(mode: AuthMode, **overrides: Any) -> Iterator[TestClient]:
    with TestClient(app_in(mode, **overrides)) as client:
        yield client


@pytest.fixture
def header_mode() -> Iterator[TestClient]:
    yield from client_in("header")


@pytest.fixture
def dual_mode() -> Iterator[TestClient]:
    yield from client_in("dual")


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    yield from client_in("token")


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def register(client: TestClient, headers: dict[str, str]) -> Any:
    return client.put(f"{BASE}/documents/{DOC}", json=DOCUMENT, headers=headers)


def store_of(client: TestClient) -> MemoryKnowledgeStore:
    app = client.app
    assert isinstance(app, FastAPI)
    memory: MemoryKnowledgeStore = app.state.wiring.unit_of_work
    return memory


def draft(client: TestClient, headers: dict[str, str]) -> RuleVersionId:
    """A draft version whose clause is registered with ``headers``."""
    assert register(client, headers).status_code in {200, 201}
    _, version = store_of(client).add_rule(
        "gstr3b_extension", title="Extension", effective_from=date(2026, 4, 1)
    )
    return version


def cite(client: TestClient, version: RuleVersionId, headers: dict[str, str]) -> Any:
    return client.put(
        f"{BASE}/rule-versions/{version}/citations",
        json={"citations": [{"clause_id": str(CLAUSE), "quote": QUOTE}]},
        headers=headers,
    )


def step(
    client: TestClient, version: RuleVersionId, action: str, headers: dict[str, str], **body: Any
) -> Any:
    return client.post(
        f"{BASE}/rule-versions/{version}/{action}",
        json={"actor_id": ASSERTED, **body},
        headers=headers,
    )


def stage_candidate(client: TestClient, headers: dict[str, str]) -> str:
    start = TEXT.index("FORM GSTR-3B")
    staged = client.put(
        f"{BASE}/documents/{DOC}/relation-candidates",
        json={
            "extractor": "p@1",
            "outcome": "ok",
            "candidates": [
                {
                    "relation": "extends_deadline",
                    "target_type": "form",
                    "target_name": "GSTR-3B",
                    "target_clause_ref": "en.p1",
                    "target_span_start": start,
                    "target_span_end": start + 12,
                    "evidence_clause_ref": "en.p1",
                    "evidence_quote": "hereby extends the due date",
                    "quote_score": 1.0,
                    "confidence": 0.9,
                    "needs_review": False,
                }
            ],
        },
        headers=headers,
    )
    assert staged.status_code == 200, staged.text
    candidate_id: str = staged.json()["candidate_ids"][0]
    return candidate_id


# ---------------------------------------------------------------- header mode


def test_header_mode_takes_the_shared_tokens_and_ignores_a_bearer(header_mode: TestClient) -> None:
    assert register(header_mode, WRITE).status_code == 201
    refused = register(header_mode, PIPELINE)
    assert (refused.status_code, problem(refused)) == (401, "rulebook-write-token-invalid")
    version = draft(header_mode, WRITE)
    assert cite(header_mode, version, REVIEW).status_code == 200
    submitted = step(header_mode, version, "submit", REVIEW)
    assert submitted.status_code == 200
    approved = step(header_mode, version, "approve", {**REVIEW, **ANALYST})
    assert approved.json()["approved_by"] == [ASSERTED], "header mode reads the body"


# ---------------------------------------------------------------- dual mode


def test_dual_mode_takes_a_pipeline_write_by_scope_or_by_token(dual_mode: TestClient) -> None:
    assert register(dual_mode, PIPELINE).status_code == 201
    assert register(dual_mode, WRITE).status_code == 200
    for caller in (ANALYST, QA):
        refused = register(dual_mode, {**WRITE, **caller})
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    bad = register(dual_mode, bearer("not-a-token"))
    assert (bad.status_code, problem(bad)) == (401, "auth-token-invalid")


def test_dual_mode_takes_an_analyst_action_by_role_or_by_token(dual_mode: TestClient) -> None:
    version = draft(dual_mode, WRITE)
    assert cite(dual_mode, version, REVIEW).status_code == 200
    assert cite(dual_mode, version, ANALYST).json()["unchanged"] == 1
    assert step(dual_mode, version, "submit", REVIEW).status_code == 200
    refused = step(dual_mode, version, "approve", {**REVIEW, **PIPELINE})
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    approved = step(dual_mode, version, "approve", REVIEWER)
    assert approved.json()["approved_by"] == [str(REVIEWER_ID)]
    refused = register(dual_mode, REVIEW)
    assert (refused.status_code, problem(refused)) == (401, "rulebook-write-token-invalid")


def test_dual_mode_without_the_shared_tokens_asks_for_an_access_token() -> None:
    for client in client_in("dual", rulebook_write_token=None, rulebook_review_token=None):
        refused = register(client, WRITE)
        assert (refused.status_code, problem(refused)) == (401, "auth-token-required")
        assert register(client, PIPELINE).status_code == 201
        sweep = client.post(f"{BASE}/maintenance/transitions", json={}, headers=REVIEW)
        assert (sweep.status_code, problem(sweep)) == (401, "auth-token-required")
        assert (
            client.post(f"{BASE}/maintenance/transitions", json={}, headers=ADMIN).status_code
            == 200
        )


# ---------------------------------------------------------------- token mode


def test_token_mode_refuses_the_shared_tokens(token_mode: TestClient) -> None:
    for response in (
        register(token_mode, WRITE),
        token_mode.post(f"{BASE}/maintenance/transitions", json={}, headers=REVIEW),
    ):
        assert (response.status_code, problem(response)) == (401, "auth-token-required")
        assert response.headers["www-authenticate"] == "Bearer"
    assert token_mode.get(f"{BASE}/rules").status_code == 200, "the read API needs no token"


REVIEW_QUEUES = (
    f"{BASE}/review/entities",
    f"{BASE}/review/entities/items?entity_type=form&proposed_name=GSTR-3B",
    f"{BASE}/review/relations",
)


def test_token_mode_shows_the_review_queues_to_regulatory_roles_only(
    token_mode: TestClient,
) -> None:
    assert register(token_mode, PIPELINE).status_code in {200, 201}
    stage_candidate(token_mode, PIPELINE)
    for queue in REVIEW_QUEUES:
        anonymous = token_mode.get(queue)
        assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")
        for outsider in (OWNER, PIPELINE, QA):
            refused = token_mode.get(queue, headers=outsider)
            assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
        for regulatory in (ANALYST, REVIEWER, ADMIN):
            assert token_mode.get(queue, headers=regulatory).status_code == 200, queue
    (candidate,) = token_mode.get(f"{BASE}/review/relations", headers=ANALYST).json()
    assert candidate["relation"] == "extends_deadline"


def test_the_review_queues_stay_open_without_a_token(
    header_mode: TestClient, dual_mode: TestClient
) -> None:
    for queue in REVIEW_QUEUES:
        assert header_mode.get(queue).status_code == 200
        assert header_mode.get(queue, headers=OWNER).status_code == 200, "header reads no token"
        assert dual_mode.get(queue).status_code == 200
        assert dual_mode.get(queue, headers=ANALYST).status_code == 200
        refused = dual_mode.get(queue, headers=OWNER)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")


def test_token_mode_records_the_signed_in_actors_of_the_flow(token_mode: TestClient) -> None:
    version = draft(token_mode, PIPELINE)
    assert cite(token_mode, version, ANALYST).status_code == 200
    for caller in (REVIEWER, OWNER):
        refused = step(token_mode, version, "submit", caller, high_impact=True)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    submitted = step(token_mode, version, "submit", ANALYST, high_impact=True)
    assert submitted.status_code == 200, submitted.text
    for caller in (ANALYST, ADMIN, PIPELINE):
        refused = step(token_mode, version, "approve", caller)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    first = step(token_mode, version, "approve", REVIEWER)
    assert first.json()["approved_by"] == [str(REVIEWER_ID)]
    spoofed = step(token_mode, version, "approve", REVIEWER, actor_id=str(OTHER_REVIEWER_ID))
    assert (spoofed.status_code, problem(spoofed)) == (409, "rulebook-duplicate-approver")
    second = step(token_mode, version, "approve", OTHER_REVIEWER)
    assert second.json()["status"] == "approved"
    refused = step(token_mode, version, "publish", ANALYST)
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    published = step(token_mode, version, "publish", REVIEWER)
    assert published.status_code == 200, published.text
    assert published.json()["approved_by"] == sorted([str(REVIEWER_ID), str(OTHER_REVIEWER_ID)])
    withdrawn = step(token_mode, version, "withdraw", OTHER_REVIEWER)
    assert withdrawn.json()["status"] == "withdrawn"


def test_token_mode_lets_the_pipeline_draft_and_a_reviewer_return(token_mode: TestClient) -> None:
    version = draft(token_mode, PIPELINE)
    assert cite(token_mode, version, PIPELINE).status_code == 200
    submitted = step(token_mode, version, "submit", PIPELINE)
    assert submitted.status_code == 200, "a service has no person to name, so the body does"
    returned = step(token_mode, version, "return", REVIEWER, note="needs a second clause")
    assert returned.json()["status"] == "draft"
    refused = step(token_mode, version, "return", OWNER)
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")


def test_token_mode_records_who_decided_a_review(token_mode: TestClient) -> None:
    assert register(token_mode, PIPELINE).status_code == 201
    candidate_id = stage_candidate(token_mode, PIPELINE)
    path = f"{BASE}/review/relations/{candidate_id}/reject"
    body = {"reason": "wrong_target", "decided_by": "someone else"}
    refused = token_mode.post(path, json=body, headers=PIPELINE)
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    rejected = token_mode.post(path, json=body, headers=ANALYST)
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["decided_by"] == str(ANALYST_ID)
    for caller in (REVIEWER, ADMIN, ANALYST):
        assert (
            token_mode.post(f"{BASE}/maintenance/transitions", json={}, headers=caller).status_code
            == 200
        )
