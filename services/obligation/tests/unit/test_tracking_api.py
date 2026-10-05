"""The tracking routes on the memory store in header mode, under the service's prefix and as the
public API serves them: the detail, the status, the assignee and the comments, each change with
its Idempotency-Key."""

from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.ids import ObligationId
from domain_kernel.rules import RuleVersionSnapshot
from obligation.application.materialise import MaterialiseRequest
from obligation.application.tracking import COMMENT_ACTION
from obligation.infrastructure.memory import MemoryStore
from obligation.main import build_app
from obligation.settings import ObligationSettings
from obligation.testing import (
    ANALYST,
    BUSINESS,
    CITATION,
    DECISION,
    OTHER_TENANT,
    TENANT,
    FakeRuleVersionReader,
    FakeTenantMembers,
    rule,
)
from py_common.idempotency.fastapi import REPLAYED_HEADER

SERVICE_ROUTE = "/v1/obligation/obligations"
PUBLIC_ROUTE = "/v1/obligations"
WAIVER = "Filed by the head office under the group registration (synthetic)"
SOMEONE = UUID(int=0x5AF)


class Api:
    """The app with two obligations of a monthly rule, and requests against one base path."""

    def __init__(self, base: str) -> None:
        self.rule: RuleVersionSnapshot = rule()
        self.reader = FakeRuleVersionReader([self.rule])
        self.members = FakeTenantMembers()
        settings = ObligationSettings(
            _env_file=None, service_name="obligation", obligation_store="memory"
        )
        self.app: FastAPI = build_app(settings, rules=self.reader, members=self.members)
        made = self.app.state.wiring.materialise.run(
            MaterialiseRequest(
                TENANT, BUSINESS, DECISION, self.rule, date(2026, 9, 28), profile_version=3
            )
        )
        self.first: ObligationId = made.created[0]
        self.base = base
        self.client = TestClient(self.app)

    @property
    def store(self) -> MemoryStore:
        store = self.app.state.wiring.unit_of_work
        assert isinstance(store, MemoryStore)
        return store

    def url(self, suffix: str = "", obligation_id: object = None) -> str:
        return f"{self.base}/{obligation_id or self.first}{suffix}"

    def post(
        self, suffix: str, body: dict[str, Any], key: str | None = None, tenant: object = TENANT
    ) -> Any:
        headers = {"x-tenant-id": str(tenant)}
        if key is not None:
            headers["Idempotency-Key"] = key
        return self.client.post(self.url(suffix), json=body, headers=headers)

    def put(self, body: dict[str, Any], key: str, tenant: object = TENANT) -> Any:
        headers = {"x-tenant-id": str(tenant), "Idempotency-Key": key}
        return self.client.put(self.url("/assignee"), json=body, headers=headers)

    def detail(self, tenant: object = TENANT) -> Any:
        return self.client.get(self.url(), headers={"x-tenant-id": str(tenant)})


@pytest.fixture(params=[SERVICE_ROUTE, PUBLIC_ROUTE], ids=["service", "public"])
def api(request: pytest.FixtureRequest) -> Iterator[Api]:
    served = Api(request.param)
    with served.client:
        yield served


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def key() -> str:
    return str(uuid4())


def test_the_detail_shows_the_review_the_citations_and_the_history(api: Api) -> None:
    response = api.detail()
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["obligation_id"], body["status"], body["profile_version"]) == (
        str(api.first),
        "open",
        3,
    )
    assert body["assignee_id"] is None
    assert body["rule_version"] == {
        "rule_version_id": str(api.rule.rule_version_id),
        "rule_key": "gstr3b_monthly",
        "title": api.rule.title,
        "status": "published",
        "effective_from": "2026-04-01",
        "effective_to": None,
        "seed_status": "needs_review",
        "reviewed": False,
        "approved_by": [str(ANALYST)],
        "published_at": "2026-09-28T10:00:00Z",
    }
    (citation,) = body["citations"]
    assert (citation["clause_ref"], citation["quote"]) == (CITATION.clause_ref, CITATION.quote)
    assert [change["kind"] for change in body["history"]] == ["created"]
    assert body["comments"] == []
    assert api.reader.reads == [api.rule.rule_version_id], "the cache was empty: read once"
    assert api.detail().json() == body
    assert api.reader.reads == [api.rule.rule_version_id]


def test_another_tenant_reads_and_changes_nothing(api: Api) -> None:
    assert problem(api.detail(OTHER_TENANT)) == "obligation-not-found"
    started = api.post("/status", {"action": "start"}, key(), tenant=OTHER_TENANT)
    assert (started.status_code, problem(started)) == (404, "obligation-not-found")
    commented = api.post("/comments", {"body": "Example (synthetic)"}, key(), OTHER_TENANT)
    assert commented.status_code == 404
    assigned = api.put({"assignee_id": str(SOMEONE)}, key(), tenant=OTHER_TENANT)
    assert assigned.status_code == 404
    assert api.detail().json()["status"] == "open"
    assert api.store.audit == []


def test_a_change_needs_an_idempotency_key(api: Api) -> None:
    for suffix, body in (("/status", {"action": "start"}), ("/comments", {"body": "Example"})):
        missing = api.post(suffix, body)
        assert (missing.status_code, problem(missing)) == (428, "idempotency-key-required")
    unkeyed = api.client.put(
        api.url("/assignee"), json={"assignee_id": None}, headers={"x-tenant-id": str(TENANT)}
    )
    assert (unkeyed.status_code, problem(unkeyed)) == (428, "idempotency-key-required")
    assert api.store.audit == []


def test_completing_twice_with_one_key_is_one_transition_with_one_answer(api: Api) -> None:
    once = key()
    first = api.post("/status", {"action": "complete"}, once)
    second = api.post("/status", {"action": "complete"}, once)
    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json() == second.json()
    assert first.json()["status"] == "done"
    assert first.json()["closed_reason"] == "completed"
    assert second.headers[REPLAYED_HEADER] == "true"
    assert REPLAYED_HEADER not in first.headers
    history = api.detail().json()["history"]
    assert [change["kind"] for change in history] == ["created", "closed"]
    assert len([e for e in api.store.events if e.topic == "obligation.closed"]) == 1
    reused = api.post("/status", {"action": "start"}, once)
    assert (reused.status_code, problem(reused)) == (422, "idempotency-key-reused")
    closed = api.post("/status", {"action": "start"}, key())
    assert (closed.status_code, problem(closed)) == (409, "obligation-closed")


def test_start_moves_to_in_progress_once(api: Api) -> None:
    started = api.post("/status", {"action": "start", "reason": "Collecting invoices"}, key())
    assert started.json()["status"] == "in_progress"
    again = api.post("/status", {"action": "start"}, key())
    assert (again.status_code, problem(again)) == (422, "invalid-transition")
    (change,) = [c for c in api.detail().json()["history"] if c["kind"] == "started"]
    assert (change["note"], change["actor"], change["status_after"]) == (
        "Collecting invoices",
        None,
        "in_progress",
    )


def test_a_waiver_needs_a_reason_of_ten_characters(api: Api) -> None:
    for body in ({"action": "waive"}, {"action": "waive", "reason": "   short    "}):
        refused = api.post("/status", body, key())
        assert (refused.status_code, problem(refused)) == (422, "request-invalid")
    unknown = api.post("/status", {"action": "archive"}, key())
    assert (unknown.status_code, problem(unknown)) == (422, "request-invalid")
    waived = api.post("/status", {"action": "waive", "reason": WAIVER}, key())
    assert (waived.json()["status"], waived.json()["closed_reason"]) == (
        "waived",
        "waived_by_user",
    )
    (closed,) = [c for c in api.detail().json()["history"] if c["kind"] == "closed"]
    assert (closed["reason"], closed["note"]) == ("waived_by_user", WAIVER)


def test_header_mode_assigns_as_named_and_unassigns(api: Api) -> None:
    once = key()
    assigned = api.put({"assignee_id": str(SOMEONE)}, once)
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignee_id"] == str(SOMEONE)
    assert api.put({"assignee_id": str(SOMEONE)}, once).json() == assigned.json()
    assert api.members.asked == [], "an unverified caller cannot be held to the tenant's users"
    unassigned = api.put({"assignee_id": None}, key())
    assert unassigned.json()["assignee_id"] is None
    history = api.detail().json()["history"]
    assert [(c["kind"], c["previous_assignee_id"], c["new_assignee_id"]) for c in history] == [
        ("created", None, None),
        ("assigned", None, str(SOMEONE)),
        ("unassigned", str(SOMEONE), None),
    ]
    missing = api.put({}, key())
    assert (missing.status_code, problem(missing)) == (422, "request-invalid")
    api.post("/status", {"action": "complete"}, key())
    closed = api.put({"assignee_id": str(SOMEONE)}, key())
    assert (closed.status_code, problem(closed)) == (409, "obligation-closed")


def test_comments_are_created_once_per_key_and_listed_oldest_first(api: Api) -> None:
    once = key()
    created = api.post("/comments", {"body": "  Acknowledgement filed (synthetic) "}, once)
    assert created.status_code == 201, created.text
    comment = created.json()
    assert (comment["body"], comment["author_id"], comment["author_label"]) == (
        "Acknowledgement filed (synthetic)",
        None,
        "system:obligation",
    )
    replayed = api.post("/comments", {"body": "  Acknowledgement filed (synthetic) "}, once)
    assert (replayed.status_code, replayed.json()) == (201, comment)
    api.post("/comments", {"body": "Example follow-up (synthetic)"}, key())
    listed = api.detail().json()["comments"]
    assert [c["body"] for c in listed] == [
        "Acknowledgement filed (synthetic)",
        "Example follow-up (synthetic)",
    ]
    for body in ({"body": "   "}, {"body": "x" * 2001}, {}):
        refused = api.post("/comments", body, key())
        assert (refused.status_code, problem(refused)) == (422, "request-invalid")
    assert [e.action for e in api.store.audit] == [COMMENT_ACTION, COMMENT_ACTION]
    unknown = api.client.post(
        api.url("/comments", uuid4()),
        json={"body": "Example (synthetic)"},
        headers={"x-tenant-id": str(TENANT), "Idempotency-Key": key()},
    )
    assert (unknown.status_code, problem(unknown)) == (404, "obligation-not-found")


def test_the_rulebook_down_on_a_missing_cache_row_is_a_503(api: Api) -> None:
    api.reader.down = True
    response = api.detail()
    assert (response.status_code, problem(response)) == (503, "rulebook-unavailable")
