"""The review task routes over HTTP on the memory store: the queue and its pages, a claim, a
draft edited and cited, the decisions, the stats, the problem types, and who may do what in
header, dual and token mode (the actor of a token is the one recorded)."""

import hashlib
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.documents import clause_id_for, document_id_for
from domain_kernel.ids import TenantId, UserId
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app
from rulebook.testing import REVIEW_TOKEN, WRITE_TOKEN, rulebook_settings

BASE = "/v1/rulebook"
TASKS = f"{BASE}/review/tasks"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
REVIEW = {"x-cw-review-token": REVIEW_TOKEN}
ANALYST_ID, REVIEWER_ID, OTHER_REVIEWER_ID = (str(UUID(int=n)) for n in (31, 32, 33))
DIGEST = hashlib.sha256(b"example statute for the review routes").hexdigest()
DOC = document_id_for(DIGEST)
CLAUSE = clause_id_for(DOC, "en.p1")
TEXT = (
    "Example section 1. Every example person shall furnish the example statement of outward "
    "supplies by the eleventh day of the following month."
)
QUOTE = "shall furnish the example statement of outward supplies by the eleventh day"
STATUTE = {
    "source_id": str(UUID(int=9)),
    "sha256": DIGEST,
    "regulator": "cbic",
    "doc_type": "statute",
    "url": "upload://cgst_act/example",
    "language": "en",
    "media_type": "text/html",
    "parser_version": "html@1",
    "title": "Example Act (synthetic)",
    "published_at": "2000-01-01",
    "fetched_at": "2000-01-03T06:00:00Z",
    "clauses": [{"clause_ref": "en.p1", "text": TEXT}],
}
ISSUER = TestIssuer()
INTERNAL = TenantId.new()
ANALYST_USER, REVIEWER_USER, OTHER_USER = UserId.new(), UserId.new(), UserId.new()
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True, user_id=ANALYST_USER))
REVIEWER = bearer(ISSUER.user(INTERNAL, [Role.REVIEWER], mfa=True, user_id=REVIEWER_USER))
OTHER_REVIEWER = bearer(ISSUER.user(INTERNAL, [Role.REVIEWER], mfa=True, user_id=OTHER_USER))
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True))
OWNER = bearer(ISSUER.user(TenantId.new(), [Role.OWNER]))
PIPELINE = bearer(ISSUER.service("pipeline", [Scope.RULEBOOK_WRITE]))
MONTHLY = "gstr1_monthly"


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def app_in(mode: AuthMode = "header", **overrides: Any) -> FastAPI:
    return build_app(
        rulebook_settings(
            rulebook_publish_enabled=True,
            rulebook_seed_on_start=True,
            **ISSUER.settings_overrides(mode),
            **overrides,
        )
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_in()) as test_client:
        stored = test_client.put(f"{BASE}/documents/{DOC}", json=STATUTE, headers=WRITE)
        assert stored.status_code == 201, stored.text
        yield test_client


@pytest.fixture
def token_mode() -> Iterator[TestClient]:
    with TestClient(app_in("token")) as test_client:
        stored = test_client.put(f"{BASE}/documents/{DOC}", json=STATUTE, headers=PIPELINE)
        assert stored.status_code == 201, stored.text
        yield test_client


def store_of(client: TestClient) -> MemoryKnowledgeStore:
    app = client.app
    assert isinstance(app, FastAPI)
    memory: MemoryKnowledgeStore = app.state.wiring.unit_of_work
    return memory


def queue(client: TestClient, headers: dict[str, str], **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = {**params, **({} if cursor is None else {"cursor": cursor})}
        page = client.get(TASKS, params=query, headers=headers)
        assert page.status_code == 200, page.text
        items += page.json()["items"]
        cursor = page.json()["next_cursor"]
        if cursor is None:
            return items


def task_of(client: TestClient, rule_key: str, headers: dict[str, str] = REVIEW) -> str:
    (task,) = [
        item
        for item in queue(client, headers)
        if item["rule_key"] == rule_key and item["status"] != "decided"
    ]
    task_id: str = task["task_id"]
    return task_id


def claim(
    client: TestClient, task_id: str, headers: dict[str, str], actor: str = ANALYST_ID
) -> Any:
    return client.post(f"{TASKS}/{task_id}/claim", json={"actor_id": actor}, headers=headers)


def edit(client: TestClient, task_id: str, headers: dict[str, str], **body: Any) -> Any:
    return client.patch(
        f"{TASKS}/{task_id}/draft", json={"actor_id": ANALYST_ID, **body}, headers=headers
    )


def decide(
    client: TestClient, task_id: str, headers: dict[str, str], actor: str, **body: Any
) -> Any:
    return client.post(
        f"{TASKS}/{task_id}/decide",
        json={"actor_id": actor, "decision": "approve", **body},
        headers=headers,
    )


CITATION = {"citations": [{"clause_id": str(CLAUSE), "quote": QUOTE}]}


# ---------------------------------------------------------------- header mode


def test_seed_tasks_open_once_and_page_through_the_queue(client: TestClient) -> None:
    opened = client.post(f"{TASKS}/seed", headers=REVIEW)
    assert opened.status_code == 200, opened.text
    assert opened.json()["opened"] == 13
    again = client.post(f"{TASKS}/seed", headers=REVIEW).json()
    assert again == {"opened": 0, "task_ids": []}
    page = client.get(TASKS, params={"limit": 5}).json()
    assert len(page["items"]) == 5
    assert page["next_cursor"] is not None
    every = queue(client, REVIEW, limit=4)
    assert len(every) == 13
    assert {item["task_id"] for item in every} == set(opened.json()["task_ids"])
    first = every[0]
    assert (first["kind"], first["status"], first["priority"], first["regulator"]) == (
        "seed",
        "open",
        50,
        "cbic",
    )
    assert (first["version_status"], first["approvals"], first["required_approvals"]) == (
        "draft",
        0,
        1,
    )
    assert queue(client, REVIEW, status="claimed") == []
    assert queue(client, REVIEW, regulator="gstn") == []
    assert len(queue(client, REVIEW, regulator="cbic", status="open", limit=4)) == 13
    assert [item["rule_key"] for item in every] == sorted(item["rule_key"] for item in every)
    stale = client.get(TASKS, params={"status": "open", "cursor": page["next_cursor"]})
    assert (stale.status_code, problem(stale)) == (422, "pagination-cursor-invalid")


def test_a_claimed_task_is_edited_cited_approved_and_read(client: TestClient) -> None:
    client.post(f"{TASKS}/seed", headers=REVIEW)
    task_id = task_of(client, MONTHLY)
    refused = edit(client, task_id, REVIEW, **CITATION)
    assert (refused.status_code, problem(refused)) == (409, "rulebook-review-task-not-claimed")
    claimed = claim(client, task_id, REVIEW)
    assert claimed.status_code == 200, claimed.text
    assert (claimed.json()["status"], claimed.json()["claimed_by"]) == ("claimed", ANALYST_ID)
    assert claim(client, task_id, REVIEW).json() == claimed.json(), "the claimant again"
    taken = claim(client, task_id, REVIEW, actor=REVIEWER_ID)
    assert (taken.status_code, problem(taken)) == (409, "rulebook-review-task-claimed")

    wrong = edit(
        client, task_id, REVIEW, citations=[{"clause_id": str(CLAUSE), "quote": "not in it"}]
    )
    assert (wrong.status_code, problem(wrong)) == (422, "rulebook-citation-not-verified")
    unknown = edit(client, task_id, REVIEW, specification={"attribute": "no_such", "x": 1})
    assert (unknown.status_code, problem(unknown)) == (422, "invariant-violation")
    nothing = edit(client, task_id, REVIEW)
    assert (nothing.status_code, problem(nothing)) == (422, "invariant-violation")
    cleared = edit(client, task_id, REVIEW, title=None)
    assert (cleared.status_code, problem(cleared)) == (422, "invariant-violation")

    edited = edit(client, task_id, REVIEW, title="File the example statement", **CITATION)
    assert edited.status_code == 200, edited.text
    detail = edited.json()
    assert detail["rule_version"]["title"] == "File the example statement"
    (citation,) = detail["citations"]
    assert (citation["verified"], citation["quote"]) == (True, QUOTE)
    (document,) = detail["documents"]
    assert (document["document_id"], document["doc_type"]) == (str(DOC), "statute")
    assert detail["specification_described"][0] == "all of:"
    assert [entry["action"] for entry in detail["decisions"]] == ["edited"]
    assert detail["decisions"][0]["actor_id"] == ANALYST_ID

    first = decide(client, task_id, REVIEW, REVIEWER_ID, high_impact=True, note="checked")
    assert first.status_code == 200, first.text
    assert first.json()["task"]["status"] == "open", "the round needs a second reviewer"
    assert first.json()["version"]["status"] == "in_review"
    assert first.json()["version"]["required_approvals"] == 2
    twice = decide(client, task_id, REVIEW, REVIEWER_ID)
    assert (twice.status_code, problem(twice)) == (409, "rulebook-duplicate-approver")
    second = decide(client, task_id, REVIEW, OTHER_REVIEWER_ID)
    assert second.status_code == 200, second.text
    decided = second.json()
    assert (decided["task"]["status"], decided["task"]["decision"]) == ("decided", "approve")
    assert decided["version"]["status"] == "approved", "approving never publishes"
    assert sorted(decided["version"]["approved_by"]) == [REVIEWER_ID, OTHER_REVIEWER_ID]
    closed = decide(client, task_id, REVIEW, ANALYST_ID)
    assert (closed.status_code, problem(closed)) == (409, "rulebook-review-task-closed")

    version_id = decided["version"]["rule_version_id"]
    published = client.post(
        f"{BASE}/rule-versions/{version_id}/publish",
        json={"actor_id": REVIEWER_ID},
        headers=REVIEW,
    )
    assert published.status_code == 200, published.text
    read = client.get(f"{TASKS}/{task_id}").json()
    assert read["rule_version"]["status"] == "published"
    assert [entry["action"] for entry in read["decisions"]] == [
        "edited",
        "submitted",
        "approved",
        "approved",
        "published",
    ]
    assert [task["status"] for task in read["tasks"]] == ["decided"]

    stats = client.get(f"{BASE}/review/stats").json()
    assert stats["by_status"] == {"open": 12, "claimed": 0, "decided": 1}
    assert stats["by_regulator"] == [{"regulator": "cbic", "open": 12, "claimed": 0, "decided": 1}]
    assert stats["decisions"] == {"approved": 1, "returned": 0, "rejected": 0}
    assert stats["median_seconds_to_decide"] >= 0
    assert stats["oldest_open_age_seconds"] >= 0


def test_return_and_reject_need_a_note_and_a_return_opens_the_next_task(
    client: TestClient,
) -> None:
    client.post(f"{TASKS}/seed", headers=REVIEW)
    task_id = task_of(client, MONTHLY)
    silent = decide(client, task_id, REVIEW, REVIEWER_ID, decision="return")
    assert (silent.status_code, problem(silent)) == (422, "invariant-violation")
    returned = decide(client, task_id, REVIEW, REVIEWER_ID, decision="return", note="rework")
    assert returned.status_code == 200, returned.text
    following = returned.json()["next_task_id"]
    assert following is not None
    rejected = decide(client, following, REVIEW, REVIEWER_ID, decision="reject", note="not now")
    assert rejected.json()["next_task_id"] is None
    assert rejected.json()["version"]["status"] == "draft"
    tasks = client.get(f"{TASKS}/{following}").json()["tasks"]
    assert [(task["decision"], task["note"]) for task in tasks] == [
        ("return", "rework"),
        ("reject", "not now"),
    ]


def test_unknown_tasks_are_404(client: TestClient) -> None:
    unknown = uuid4()
    for response in (
        client.get(f"{TASKS}/{unknown}"),
        claim(client, str(unknown), REVIEW),
        edit(client, str(unknown), REVIEW, title="x"),
        decide(client, str(unknown), REVIEW, REVIEWER_ID),
    ):
        assert (response.status_code, problem(response)) == (404, "rulebook-review-task-not-found")


WRITES = [
    ("post", "/review/tasks/seed", None),
    ("post", "/review/tasks/{id}/claim", {"actor_id": ANALYST_ID}),
    ("patch", "/review/tasks/{id}/draft", {"actor_id": ANALYST_ID, "title": "x"}),
    ("post", "/review/tasks/{id}/decide", {"actor_id": ANALYST_ID, "decision": "approve"}),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
def test_every_write_needs_the_review_token(
    client: TestClient, method: str, path: str, body: dict[str, object] | None
) -> None:
    url = BASE + path.format(id=uuid4())
    for headers in ({}, {"x-cw-review-token": "wrong"}, WRITE):
        response = client.request(method, url, json=body, headers=headers)
        assert (response.status_code, problem(response)) == (401, "rulebook-review-token-invalid")
    with TestClient(build_app(rulebook_settings(rulebook_review_token=None))) as closed:
        response = closed.request(method, url, json=body, headers=REVIEW)
    assert (response.status_code, problem(response)) == (503, "rulebook-reviews-disabled")


# ---------------------------------------------------------------- token mode


def test_token_mode_records_the_signed_in_actors_and_two_distinct_approvers(
    token_mode: TestClient,
) -> None:
    for caller in (OWNER, PIPELINE):
        refused = token_mode.post(f"{TASKS}/seed", headers=caller)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    shared = token_mode.post(f"{TASKS}/seed", headers=REVIEW)
    assert (shared.status_code, problem(shared)) == (401, "auth-token-required")
    assert token_mode.post(f"{TASKS}/seed", headers=ADMIN).json()["opened"] == 13
    task_id = task_of(token_mode, MONTHLY, ANALYST)

    for caller in (REVIEWER, ADMIN, PIPELINE, OWNER):
        refused = claim(token_mode, task_id, caller)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden"), caller
    claimed = claim(token_mode, task_id, ANALYST, actor=REVIEWER_ID)
    assert claimed.json()["claimed_by"] == str(ANALYST_USER), "the token names the claimant"
    for caller in (REVIEWER, PIPELINE):
        refused = edit(token_mode, task_id, caller, **CITATION)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    edited = edit(token_mode, task_id, ANALYST, **CITATION)
    assert edited.status_code == 200, edited.text
    assert edited.json()["decisions"][0]["actor_id"] == str(ANALYST_USER)

    refused = decide(token_mode, task_id, PIPELINE, REVIEWER_ID)
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    first = decide(token_mode, task_id, REVIEWER, ANALYST_ID, high_impact=True)
    assert first.json()["version"]["approved_by"] == [str(REVIEWER_USER)]
    spoofed = decide(token_mode, task_id, REVIEWER, str(OTHER_USER))
    assert (spoofed.status_code, problem(spoofed)) == (409, "rulebook-duplicate-approver")
    second = decide(token_mode, task_id, OTHER_REVIEWER, ANALYST_ID)
    decided = second.json()
    assert decided["task"]["decided_by"] == str(OTHER_USER)
    assert sorted(decided["version"]["approved_by"]) == sorted(
        [str(REVIEWER_USER), str(OTHER_USER)]
    )


def test_token_mode_shows_the_queue_to_regulatory_roles_only(token_mode: TestClient) -> None:
    token_mode.post(f"{TASKS}/seed", headers=ADMIN)
    task_id = task_of(token_mode, MONTHLY, REVIEWER)
    for path in (TASKS, f"{TASKS}/{task_id}", f"{BASE}/review/stats"):
        anonymous = token_mode.get(path)
        assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")
        for outsider in (OWNER, PIPELINE):
            refused = token_mode.get(path, headers=outsider)
            assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
        for regulatory in (ANALYST, REVIEWER, ADMIN):
            assert token_mode.get(path, headers=regulatory).status_code == 200, path


def test_dual_mode_takes_a_bearer_or_the_review_token() -> None:
    with TestClient(app_in("dual")) as dual:
        assert dual.post(f"{TASKS}/seed", headers=REVIEW).json()["opened"] == 13
        task_id = task_of(dual, MONTHLY)
        assert claim(dual, task_id, ANALYST).json()["claimed_by"] == str(ANALYST_USER)
        refused = dual.get(TASKS, headers=OWNER)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
        assert dual.get(TASKS).status_code == 200, "without a token the queue stays open"
