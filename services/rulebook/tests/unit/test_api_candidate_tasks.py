"""Candidate tasks over HTTP on the memory store: the queue's kind filter and candidate summary,
the detail with the candidate and the draft it proposes, a version drafted from the candidate
(``POST .../draft``) with its problem types, the rejection with its reason and rule.rejected,
the stats, and who may draft in token mode."""

import hashlib
from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.access import Role, Scope
from domain_kernel.documents import clause_id_for, document_id_for
from domain_kernel.ids import TenantId, UserId
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.status import RuleVersionStatus
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode
from rulebook.application.intake import IngestRuleCandidate
from rulebook.domain.relations import RelationCandidate
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app
from rulebook.testing import REVIEW_TOKEN, WRITE_TOKEN, rulebook_settings

BASE = "/v1/rulebook"
TASKS = f"{BASE}/review/tasks"
WRITE = {"x-cw-write-token": WRITE_TOKEN}
REVIEW = {"x-cw-review-token": REVIEW_TOKEN}
ANALYST_ID, REVIEWER_ID, OTHER_REVIEWER_ID = (str(UUID(int=n)) for n in (71, 72, 73))
DIGEST = hashlib.sha256(b"example notification for the candidate routes").hexdigest()
DOC = document_id_for(DIGEST)
MONTHLY = "example_monthly"
EXTENSION = "example_extension_2000_01"
TEXT_EXTENDS = (
    "The example board extends the due date for furnishing the example return for the month "
    "of January, 2000 till the twenty-fifth day of February, 2000."
)
TEXT_EFFECT = "This example notification shall come into effect from 1st February, 2000."
QUOTE_EXTENDS = "extends the due date for furnishing the example return for the month of January"
QUOTE_EFFECT = "shall come into effect from 1st February, 2000"
NOTIFICATION = {
    "source_id": str(UUID(int=11)),
    "sha256": DIGEST,
    "regulator": "CBIC",
    "doc_type": "notification",
    "url": "https://example.invalid/notification-01-2000.pdf",
    "language": "en",
    "media_type": "application/pdf",
    "parser_version": "pdf@1",
    "external_ref": "01/2000-Example",
    "title": "Example notification 01/2000",
    "published_at": "2000-01-02",
    "fetched_at": "2000-01-03T06:00:00Z",
    "clauses": [
        {"clause_ref": "en.p1", "text": "Example notification No. 01/2000 of the example board."},
        {"clause_ref": "en.p2", "text": TEXT_EXTENDS},
        {"clause_ref": "en.p3", "text": TEXT_EFFECT},
    ],
}
SPECIFICATION = {
    "all_of": [
        {"attribute": "registration_type", "operator": "eq", "value": "regular"},
        {"attribute": "filing_scheme", "operator": "eq", "value": "regular_monthly"},
    ]
}
FIELDS: dict[str, Any] = {
    "title": "Example: the due date of the example return is extended",
    "summary": "An example notification extends the due date of the example return.",
    "doc_kind": "notification",
    "change_kind": "extension",
    "effective_from": "2000-02-01",
    "effective_to": None,
    "references": [],
    "applies_to": [{**predicate, "clause_ref": "en.p2"} for predicate in SPECIFICATION["all_of"]],
    "obligation": {
        "title": "File the example return for January 2000",
        "steps": ["Furnish the example return"],
        "evidence_type": "filing_acknowledgement",
        "due_in_days": 25,
        "clause_ref": "en.p2",
    },
    "recurrence": None,
    "amounts": [],
    "citations": [
        {"clause_ref": "en.p2", "quote": QUOTE_EXTENDS},
        {"clause_ref": "en.p3", "quote": QUOTE_EFFECT},
    ],
    "confidence": 0.9,
}
ISSUER = TestIssuer()
INTERNAL = TenantId.new()
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True, user_id=UserId.new()))
REVIEWER = bearer(ISSUER.user(INTERNAL, [Role.REVIEWER], mfa=True, user_id=UserId.new()))
PIPELINE = bearer(ISSUER.service("pipeline", [Scope.RULEBOOK_WRITE]))


def app_in(mode: AuthMode = "header") -> FastAPI:
    return build_app(
        rulebook_settings(rulebook_publish_enabled=True, **ISSUER.settings_overrides(mode))
    )


def store_of(client: TestClient) -> MemoryKnowledgeStore:
    app = client.app
    assert isinstance(app, FastAPI)
    memory: MemoryKnowledgeStore = app.state.wiring.unit_of_work
    return memory


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app_in()) as test_client:
        stored = test_client.put(f"{BASE}/documents/{DOC}", json=NOTIFICATION, headers=WRITE)
        assert stored.status_code == 201, stored.text
        store_of(test_client).add_rule(
            MONTHLY,
            title="Example monthly return",
            regulator="cbic",
            status=RuleVersionStatus.PUBLISHED,
            effective_from=date(2000, 1, 1),
            specification=SPECIFICATION,
            obligation_template={"title": "File the example return", "steps": []},
            recurrence={"frequency": "monthly", "due_day": 20, "due_month_offset": 0},
        )
        yield test_client


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def received(client: TestClient, **overrides: Any) -> str:
    """A candidate taken in as the worker's consumer takes it, and its task's id."""
    body: dict[str, Any] = {
        "candidate_id": str(uuid4()),
        "document_id": str(DOC),
        "regulator": "CBIC",
        "model": "fake/echo",
        "prompt_version": "extraction.rule_candidate@1",
        "confidence": 0.9,
        "citation_count": 2,
        "needs_review": False,
        "outcome": "extracted",
        "candidate": FIELDS,
        "suggested_rule_key": MONTHLY,
        "clause_ids": [str(clause_id_for(DOC, ref)) for ref in ("en.p2", "en.p3")],
        **overrides,
    }
    intake = IngestRuleCandidate(store_of(client)).run(body, uuid4())
    assert intake.task is not None
    return str(intake.task.task_id)


def claim(client: TestClient, task_id: str, actor: str = ANALYST_ID) -> Any:
    return client.post(f"{TASKS}/{task_id}/claim", json={"actor_id": actor}, headers=REVIEW)


def draft(client: TestClient, task_id: str, headers: dict[str, str] = REVIEW, **body: Any) -> Any:
    values: dict[str, Any] = {
        "actor_id": ANALYST_ID,
        "rule_key": EXTENSION,
        "new_rule": {"regulator": "cbic", "level": "registration"},
    }
    values.update(body)
    return client.post(f"{TASKS}/{task_id}/draft", json=values, headers=headers)


def decide(client: TestClient, task_id: str, actor: str, **body: Any) -> Any:
    return client.post(
        f"{TASKS}/{task_id}/decide", json={"actor_id": actor, **body}, headers=REVIEW
    )


def test_the_queue_shows_a_candidate_task_and_filters_by_kind(client: TestClient) -> None:
    task_id = received(client)
    page = client.get(TASKS, params={"kind": "candidate", "regulator": "CBIC"}, headers=REVIEW)
    assert page.status_code == 200, page.text
    (item,) = page.json()["items"]
    assert item["task_id"] == task_id
    assert (item["kind"], item["rule_version_id"], item["version"], item["rule_key"]) == (
        "candidate",
        None,
        None,
        MONTHLY,
    )
    assert (item["priority"], item["high_impact"], item["required_approvals"]) == (100, True, 2)
    assert item["candidate"]["outcome"] == "extracted"
    seed = client.get(TASKS, params={"kind": "seed"}, headers=REVIEW)
    assert seed.json()["items"] == []
    bad = client.get(TASKS, params={"kind": "other"}, headers=REVIEW)
    assert bad.status_code == 422


def test_the_detail_carries_the_candidate_before_drafting(client: TestClient) -> None:
    task_id = received(client)
    detail = client.get(f"{TASKS}/{task_id}", headers=REVIEW)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["rule_version"] is None
    assert body["task"]["candidate_id"] == body["candidate"]["candidate_id"]
    candidate = body["candidate"]
    assert candidate["document"]["external_ref"] == "01/2000-Example"
    assert candidate["document_id"] == str(DOC)
    assert (candidate["suggested_rule_known"], candidate["high_impact_reasons"]) == (
        True,
        ["change_kind is extension"],
    )
    proposed = candidate["proposed"]
    assert proposed["specification"] == SPECIFICATION
    assert proposed["effective_from"] == "2000-02-01"
    assert [c["clause_id"] for c in proposed["citations"]] == [
        str(clause_id_for(DOC, "en.p2")),
        str(clause_id_for(DOC, "en.p3")),
    ]
    assert proposed["problems"] == []


def test_a_claimed_candidate_is_drafted_approved_by_two_and_counted(client: TestClient) -> None:
    task_id = received(client)
    assert claim(client, task_id).status_code == 200
    drafted = draft(client, task_id, note="as extracted")
    assert drafted.status_code == 200, drafted.text
    body = drafted.json()
    version = body["rule_version"]
    assert (version["rule_key"], version["version"], version["status"]) == (EXTENSION, 1, "draft")
    assert version["high_impact"]
    assert body["task"]["rule_version_id"] == version["rule_version_id"]
    assert [c["verified"] for c in body["citations"]] == [True, True]
    assert body["candidate"]["status"] == "drafted"
    again = draft(client, task_id, rule_key="example_other")
    assert (again.status_code, problem(again)) == (409, "rulebook-candidate-already-drafted")
    first = decide(client, task_id, REVIEWER_ID, decision="approve")
    assert first.json()["candidate_status"] == "drafted"
    second = decide(client, task_id, OTHER_REVIEWER_ID, decision="approve")
    assert second.status_code == 200, second.text
    assert (second.json()["candidate_status"], second.json()["version"]["status"]) == (
        "approved",
        "approved",
    )
    stats = client.get(f"{BASE}/review/stats", headers=REVIEW).json()["candidates"]
    assert stats == {
        "decided": 1,
        "approved": 1,
        "approved_without_edits": 1,
        "rejected": 0,
        "acceptance_rate": 1.0,
    }


def test_drafting_answers_its_problem_types(client: TestClient) -> None:
    task_id = received(client, candidate={**FIELDS, "effective_from": None})
    not_claimed = draft(client, task_id)
    assert (not_claimed.status_code, problem(not_claimed)) == (
        409,
        "rulebook-review-task-not-claimed",
    )
    claim(client, task_id)
    incomplete = draft(client, task_id)
    assert (incomplete.status_code, problem(incomplete)) == (422, "rulebook-draft-incomplete")
    assert incomplete.json()["detail"] == "effective_from: the candidate gives none"
    fixed = {"edits": {"effective_from": "2000-02-01"}}
    unknown = draft(client, task_id, rule_key="example_unknown", new_rule=None, **fixed)
    assert (unknown.status_code, problem(unknown)) == (422, "rulebook-rule-key-unknown")
    taken = draft(client, task_id, rule_key=MONTHLY, **fixed)
    assert (taken.status_code, problem(taken)) == (409, "rulebook-rule-key-taken")
    unverified = draft(
        client,
        task_id,
        citations=[{"clause_id": str(clause_id_for(DOC, "en.p2")), "quote": "Example absent"}],
        **fixed,
    )
    assert (unverified.status_code, problem(unverified)) == (422, "rulebook-citation-not-verified")
    bad_key = draft(client, task_id, rule_key="Not A Key", **fixed)
    assert bad_key.status_code == 422
    done = draft(client, task_id, **fixed)
    assert done.status_code == 200, done.text
    (edited,) = done.json()["decisions"]
    assert edited["action"] == "edited"
    assert edited["note"].endswith("changed effective_from")


def test_a_candidate_is_rejected_with_its_reason_before_drafting(client: TestClient) -> None:
    task_id = received(client)
    approve = decide(client, task_id, REVIEWER_ID, decision="approve")
    assert (approve.status_code, problem(approve)) == (409, "rulebook-candidate-not-drafted")
    edit = client.patch(
        f"{TASKS}/{task_id}/draft", json={"actor_id": ANALYST_ID, "title": "x"}, headers=REVIEW
    )
    assert edit.status_code == 409
    no_reason = decide(client, task_id, REVIEWER_ID, decision="reject", note="no rule here")
    assert no_reason.status_code == 422
    rejected = decide(
        client,
        task_id,
        REVIEWER_ID,
        decision="reject",
        note="The example notification states no rule",
        reason="not_a_rule",
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert (body["version"], body["candidate_status"], body["task"]["decision"]) == (
        None,
        "rejected",
        "reject",
    )
    (event,) = body["events"]
    assert event["topic"] == "rule.rejected"
    detail = client.get(f"{TASKS}/{task_id}", headers=REVIEW).json()
    assert detail["candidate"]["reject_reason"] == "not_a_rule"


def staged_extension(client: TestClient) -> str:
    """The extension the knowledge child staged for the notification, as staging stores it."""
    clause = clause_id_for(DOC, "en.p2")
    start = TEXT_EXTENDS.index("example return")
    candidate = RelationCandidate(
        candidate_id=uuid4(),
        document_id=DOC,
        relation=RelationKind.EXTENDS_DEADLINE,
        target_type=EntityType.FORM,
        target_name="example return",
        target_clause_id=clause,
        target_span_start=start,
        target_span_end=start + len("example return"),
        evidence_clause_id=clause,
        evidence_quote=QUOTE_EXTENDS,
        quote_score=1.0,
        prompt_version="extraction.rule_relations@1",
        confidence=0.9,
        needs_review=False,
        target_rule_key=MONTHLY,
        period_label="2000-01",
        new_due_on=date(2000, 2, 25),
    )
    with store_of(client)() as uow:
        uow.candidates.add(candidate)
    return str(candidate.candidate_id)


def test_a_rejection_after_drafting_reopens_the_relations_approved_onto_the_draft(
    client: TestClient,
) -> None:
    relation = staged_extension(client)
    monthly = client.get(f"{BASE}/rules/{MONTHLY}/versions").json()[0]["rule_version_id"]
    task_id = received(client)
    claim(client, task_id)
    choice = {"candidate_id": relation, "target_rule_version_id": monthly}
    drafted = draft(client, task_id, relation_candidates=[choice])
    assert drafted.status_code == 200, drafted.text
    version_id = drafted.json()["rule_version"]["rule_version_id"]
    approved = client.get(
        f"{BASE}/review/relations", params={"status": "approved"}, headers=REVIEW
    ).json()
    assert [c["candidate_id"] for c in approved] == [relation]
    rejected = decide(
        client,
        task_id,
        REVIEWER_ID,
        decision="reject",
        note="The model read the date wrongly",
        reason="wrong_extraction",
    )
    assert rejected.status_code == 200, rejected.text
    reopened = client.get(
        f"{BASE}/review/relations", params={"document_id": str(DOC)}, headers=REVIEW
    ).json()
    assert [(c["candidate_id"], c["status"], c["decided_by"]) for c in reopened] == [
        (relation, "open", "")
    ]
    with store_of(client)() as uow:
        stored = uow.candidates.lock(UUID(relation))
    assert stored is not None
    assert f"its draft {version_id} no longer carries this relation" in stored.note
    relations = client.get(
        f"{BASE}/relations",
        params={"from_rule_version_id": version_id, "published_only": "false"},
    ).json()
    assert relations == [], "the closed draft's rule relation is gone"
    corrected = received(client)
    claim(client, corrected)
    again = draft(
        client, corrected, rule_key=f"{EXTENSION}_corrected", relation_candidates=[choice]
    )
    assert again.status_code == 200, again.text


def test_a_rejected_candidates_draft_is_closed_over_http(client: TestClient) -> None:
    task_id = received(client)
    claim(client, task_id)
    drafted = draft(client, task_id, rule_key=MONTHLY, new_rule=None)
    assert drafted.status_code == 200, drafted.text
    version = drafted.json()["rule_version"]
    assert (version["version"], version["title"]) == (2, FIELDS["title"])
    titles = {rule["rule_key"]: rule["title"] for rule in client.get(f"{BASE}/rules").json()}
    assert titles[MONTHLY] == FIELDS["title"], "the candidate's draft is the latest version"
    rejected = decide(
        client,
        task_id,
        REVIEWER_ID,
        decision="reject",
        note="The model read the date wrongly",
        reason="wrong_extraction",
    )
    assert rejected.status_code == 200, rejected.text
    titles = {rule["rule_key"]: rule["title"] for rule in client.get(f"{BASE}/rules").json()}
    assert titles[MONTHLY] == "Example monthly return", "a closed draft is never the latest"
    path = f"{BASE}/rule-versions/{version['rule_version_id']}"
    quote = {"clause_id": str(clause_id_for(DOC, "en.p3")), "quote": QUOTE_EFFECT}
    refused = [
        client.put(f"{path}/citations", json={"citations": [quote]}, headers=REVIEW),
        client.post(f"{path}/submit", json={"actor_id": ANALYST_ID}, headers=REVIEW),
        client.post(f"{path}/approve", json={"actor_id": REVIEWER_ID}, headers=REVIEW),
        client.post(f"{path}/publish", json={"actor_id": REVIEWER_ID}, headers=REVIEW),
    ]
    assert [(r.status_code, problem(r)) for r in refused] == [
        (409, "rulebook-rule-version-closed")
    ] * 4
    read = client.get(path).json()
    assert (read["status"], read["closed"]) == ("draft", True)
    listed = client.get(f"{BASE}/rules/{MONTHLY}/versions").json()
    assert [(v["version"], v["closed"]) for v in listed] == [(1, False), (2, True)], (
        "listed with the flag, so a reader after the latest version skips it"
    )
    detail = client.get(f"{TASKS}/{task_id}", headers=REVIEW).json()
    assert detail["rule_version"]["closed"] is True


def test_token_mode_lets_an_analyst_draft_and_not_a_reviewer() -> None:
    with TestClient(app_in("token")) as client:
        stored = client.put(f"{BASE}/documents/{DOC}", json=NOTIFICATION, headers=PIPELINE)
        assert stored.status_code == 201, stored.text
        task_id = received(client)
        claimed = client.post(
            f"{TASKS}/{task_id}/claim", json={"actor_id": ANALYST_ID}, headers=ANALYST
        )
        assert claimed.status_code == 200, claimed.text
        refused = draft(client, task_id, headers=REVIEWER)
        assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
        drafted = draft(client, task_id, headers=ANALYST)
        assert drafted.status_code == 200, drafted.text
        assert drafted.json()["candidate"]["status"] == "drafted"
