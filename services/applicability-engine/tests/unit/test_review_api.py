"""The review routes on the memory store: listing a tenant's queue a page at a time, settling an
item and its audit entry, the problems, and who may do either in header, dual and token mode."""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from applicability_engine.application.review import RESOLVE_ACTION
from applicability_engine.infrastructure.memory import MemoryStore
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
from domain_kernel.access import Role, Scope
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.ids import TenantId, UserId
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ENGINE = "/v1/applicability-engine"
ITEMS = f"{ENGINE}/review-items"
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
FREE_TEXT = {"attribute": "business_category", "free_text": "Example premises shared with a hotel"}
ISSUER = TestIssuer()
INTERNAL = TenantId.new()
"""The tenant of the regulatory team."""
REVIEWER_ID = UserId.new()
REVIEWER = bearer(ISSUER.user(INTERNAL, [Role.REVIEWER], mfa=True, user_id=REVIEWER_ID))
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True))
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True))
OWNER = bearer(ISSUER.user(TENANT, [Role.OWNER]))
ENGINE_SERVICE = bearer(ISSUER.service("applicability-engine", [Scope.TENANT_ACT]))
ITEM_FIELDS = {
    "item_id",
    "business_id",
    "rule_version_id",
    "reason",
    "status",
    "opened_at",
    "decision",
    "resolution",
    "resolved_by",
    "resolved_at",
    "note",
    "resolution_decision_id",
}


def as_tenant(tenant: object = TENANT, **headers: str) -> dict[str, str]:
    return {"x-tenant-id": str(tenant), **headers}


def resolution(kind: str = "applies", **changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "resolution": kind,
        "note": "Example premises checked against the clause",
        "resolved_by": str(uuid4()),
    }
    body.update(changes)
    return body


def audit_of(client: TestClient) -> list[AuditEntry]:
    """The audit entries the app's memory store committed."""
    store = client.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
    assert isinstance(store, MemoryStore)
    return list(store.audit)


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def open_items(client: TestClient, rulebook: MemoryRulebook, count: int = 1) -> list[str]:
    """``count`` open items of the tenant: a manual evaluation of a free-text rule each."""
    for _ in range(count):
        rule = rulebook.put(rule_version({"all_of": [REGULAR, FREE_TEXT]}))
        answer = client.post(
            f"{ENGINE}/businesses/{BUSINESS}/decisions",
            json={"rule_version_id": str(rule.rule_version_id)},
            headers=as_tenant(**{"Idempotency-Key": str(uuid4())}),
        )
        assert answer.status_code == 201, answer.text
    page = client.get(ITEMS, params={"status": "open", "limit": 200}, headers=as_tenant())
    assert page.status_code == 200, page.text
    ids = [item["item_id"] for item in page.json()["items"]]
    return ids


@pytest.fixture
def seeded(client: TestClient, profiles: MemoryProfiles, rulebook: MemoryRulebook) -> TestClient:
    profiles.put({"registration_type": "regular"}, version=2)
    return client


def test_the_queue_lists_items_with_their_decision_oldest_first_a_page_at_a_time(
    seeded: TestClient, rulebook: MemoryRulebook
) -> None:
    ids = open_items(seeded, rulebook, count=3)
    first = seeded.get(ITEMS, params={"limit": 2}, headers=as_tenant())
    assert first.status_code == 200, first.text
    body = first.json()
    assert [item["item_id"] for item in body["items"]] == ids[:2]
    item = body["items"][0]
    assert set(item) == ITEM_FIELDS
    assert (item["reason"], item["status"], item["resolution"], item["note"]) == (
        "free_text",
        "open",
        None,
        "",
    )
    assert item["decision"]["needs_review"] is True
    assert item["decision"]["trigger"] == "manual"
    assert [p["kind"] for p in item["decision"]["evaluated"]] == ["structured", "free_text"]
    second = seeded.get(
        ITEMS, params={"limit": 2, "cursor": body["next_cursor"]}, headers=as_tenant()
    )
    assert [i["item_id"] for i in second.json()["items"]] == ids[2:]
    assert second.json()["next_cursor"] is None
    other = seeded.get(ITEMS, headers=as_tenant(OTHER_TENANT))
    assert other.json() == {"items": [], "next_cursor": None}


def test_settling_an_item_appends_a_review_decision(
    seeded: TestClient, rulebook: MemoryRulebook
) -> None:
    (item_id,) = open_items(seeded, rulebook)
    reviewer = str(uuid4())
    answer = seeded.post(
        f"{ITEMS}/{item_id}/resolve",
        json=resolution("not_applicable", resolved_by=reviewer),
        headers=as_tenant(**{"x-request-id": "review-request-7"}),
    )
    assert answer.status_code == 200, answer.text
    (audited,) = audit_of(seeded)
    assert (audited.action, audited.tenant_id, audited.subject_id) == (
        RESOLVE_ACTION,
        TENANT,
        item_id,
    )
    assert audited.actor == AuditActor.system("applicability-engine"), "no verified caller"
    assert (audited.reason, audited.correlation_id) == (
        "Example premises checked against the clause",
        "review-request-7",
    )
    assert audited.after is not None
    assert audited.after["resolved_by"] == reviewer, "the body's reviewer, as the item records"
    body = answer.json()
    assert (body["status"], body["resolution"], body["resolved_by"]) == (
        "resolved",
        "not_applicable",
        reviewer,
    )
    assert body["note"] == "Example premises checked against the clause"
    appended = seeded.get(
        f"{ENGINE}/decisions/{body['resolution_decision_id']}", headers=as_tenant()
    ).json()
    assert (appended["result"], appended["trigger"], appended["confidence"]) == (
        "not_applicable",
        "review",
        1.0,
    )
    latest = seeded.get(
        f"{ENGINE}/businesses/{BUSINESS}/decisions",
        params={"rule_version_id": body["rule_version_id"]},
        headers=as_tenant(),
    ).json()["items"][0]
    assert latest["decision_id"] == body["resolution_decision_id"]

    again = seeded.post(f"{ITEMS}/{item_id}/resolve", json=resolution(), headers=as_tenant())
    assert (again.status_code, problem(again)) == (409, "applicability-review-item-resolved")
    assert len(audit_of(seeded)) == 1
    resolved = seeded.get(ITEMS, params={"status": "resolved"}, headers=as_tenant()).json()
    assert [i["item_id"] for i in resolved["items"]] == [item_id]


def test_the_problems_of_the_resolve_route(seeded: TestClient, rulebook: MemoryRulebook) -> None:
    (item_id,) = open_items(seeded, rulebook)
    missing = seeded.post(f"{ITEMS}/{uuid4()}/resolve", json=resolution(), headers=as_tenant())
    assert (missing.status_code, problem(missing)) == (404, "applicability-review-item-not-found")
    elsewhere = seeded.post(
        f"{ITEMS}/{item_id}/resolve", json=resolution(), headers=as_tenant(OTHER_TENANT)
    )
    assert elsewhere.status_code == 404
    no_tenant = seeded.post(f"{ITEMS}/{item_id}/resolve", json=resolution())
    assert (no_tenant.status_code, problem(no_tenant)) == (401, "applicability-tenant-required")
    for body in (resolution(note=""), resolution("maybe"), {**resolution(), "extra": 1}):
        assert (
            seeded.post(f"{ITEMS}/{item_id}/resolve", json=body, headers=as_tenant()).status_code
            == 422
        )
    bad_status = seeded.get(ITEMS, params={"status": "pending"}, headers=as_tenant())
    assert bad_status.status_code == 422


def client_in(mode: AuthMode) -> Iterator[tuple[TestClient, MemoryRulebook]]:
    profiles, rulebook = MemoryProfiles(), MemoryRulebook()
    profiles.put({"registration_type": "regular"}, version=2)
    settings = ApplicabilityEngineSettings(
        _env_file=None,
        service_name="applicability-engine",
        applicability_engine_store="memory",
        **ISSUER.settings_overrides(mode),
    )
    app = build_app(settings, readers=Readers(profiles=profiles, rulebook=rulebook))
    with TestClient(app) as client:
        yield client, rulebook


@pytest.fixture
def token_mode() -> Iterator[tuple[TestClient, MemoryRulebook]]:
    yield from client_in("token")


@pytest.fixture
def dual_mode() -> Iterator[tuple[TestClient, MemoryRulebook]]:
    yield from client_in("dual")


def open_one_as_service(client: TestClient, rulebook: MemoryRulebook) -> str:
    """An item opened by an evaluation the engine's own service client asks for."""
    rule = rulebook.put(rule_version({"all_of": [REGULAR, FREE_TEXT]}))
    answer = client.post(
        f"{ENGINE}/businesses/{BUSINESS}/decisions",
        json={"rule_version_id": str(rule.rule_version_id)},
        headers=as_tenant(**ENGINE_SERVICE, **{"Idempotency-Key": str(uuid4())}),
    )
    assert answer.status_code == 201, answer.text
    page = client.get(ITEMS, headers=as_tenant(**REVIEWER)).json()
    item_id: str = page["items"][0]["item_id"]
    return item_id


def test_in_token_mode_the_regulatory_team_names_the_tenant_it_reviews(
    token_mode: tuple[TestClient, MemoryRulebook],
) -> None:
    client, rulebook = token_mode
    item_id = open_one_as_service(client, rulebook)
    for reader in (REVIEWER, ADMIN, ANALYST):
        listed = client.get(ITEMS, headers=as_tenant(**reader))
        assert [i["item_id"] for i in listed.json()["items"]] == [item_id]
    for refused in (OWNER, ENGINE_SERVICE):
        answer = client.get(ITEMS, headers=as_tenant(**refused))
        assert (answer.status_code, problem(answer)) == (403, "auth-forbidden")
    unnamed = client.get(ITEMS, headers=REVIEWER)
    assert (unnamed.status_code, problem(unnamed)) == (401, "applicability-tenant-required")
    anonymous = client.get(ITEMS, headers=as_tenant())
    assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")

    analyst = client.post(
        f"{ITEMS}/{item_id}/resolve", json=resolution(), headers=as_tenant(**ANALYST)
    )
    assert (analyst.status_code, problem(analyst)) == (403, "auth-forbidden")
    assert audit_of(client) == [], "a refused resolution writes no entry"
    settled = client.post(
        f"{ITEMS}/{item_id}/resolve", json=resolution(), headers=as_tenant(**REVIEWER)
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["resolved_by"] == str(REVIEWER_ID), "the token's user, not the body's"
    (audited,) = audit_of(client)
    assert audited.actor == AuditActor.user(REVIEWER_ID, [Role.REVIEWER])
    assert audited.correlation_id == settled.headers["x-request-id"]


def test_in_dual_mode_a_resolution_needs_a_token_while_the_queue_reads_without_one(
    dual_mode: tuple[TestClient, MemoryRulebook],
) -> None:
    client, rulebook = dual_mode
    item_id = open_one_as_service(client, rulebook)
    assert client.get(ITEMS, headers=as_tenant()).status_code == 200
    anonymous = client.post(f"{ITEMS}/{item_id}/resolve", json=resolution(), headers=as_tenant())
    assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")
    owner = client.post(f"{ITEMS}/{item_id}/resolve", json=resolution(), headers=as_tenant(**OWNER))
    assert (owner.status_code, problem(owner)) == (403, "auth-forbidden")
    admin = client.post(
        f"{ITEMS}/{item_id}/resolve", json=resolution("dismiss"), headers=as_tenant(**ADMIN)
    )
    assert admin.status_code == 200, admin.text
    assert admin.json()["resolution_decision_id"] is None
    (audited,) = audit_of(client)
    assert (audited.actor.kind.value, audited.actor.label) == ("user", "admin")
