"""The public API's list of a business's obligations, ``GET /v1/businesses/{business_id}/
obligations``, on the memory store: the order, the pages, the filters, the facts of each rule
version, and the 404 of a business the tenant does not have, which the profile service decides
only when a page is empty."""

from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from domain_kernel.access import Role, Scope
from domain_kernel.ids import BusinessId, DecisionId, ObligationId
from domain_kernel.rules import RuleVersionSnapshot
from obligation.api.router import LIST_SCOPE
from obligation.application.materialise import IST, MaterialiseObligations, MaterialiseRequest
from obligation.application.queries import BusinessObligationsQuery, ListBusinessObligations
from obligation.domain.errors import BusinessNotFoundError
from obligation.domain.repository import ListingAfter
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
    FakeProfileNodes,
    FakeRuleVersionReader,
    FakeTenantMembers,
    ref_of,
    rule,
)
from py_common.auth.testing import TestIssuer, bearer
from py_common.pagination import encode_cursor
from py_common.settings import AuthMode

ISSUER = TestIssuer()
AS_TENANT = {"x-tenant-id": str(TENANT)}
AS_OTHER = {"x-tenant-id": str(OTHER_TENANT)}
EMPTY = BusinessId(UUID(int=0xE0))
"""A business of the tenant with no obligation."""
AS_OF = date(2026, 9, 28)


def path(business: object = BUSINESS) -> str:
    return f"/v1/businesses/{business}/obligations"


class Api:
    """The app with the monthly rule's obligations of ``BUSINESS``, a one-off one without a
    date, and the profile service knowing ``BUSINESS`` and ``EMPTY`` as the tenant's."""

    def __init__(self, mode: AuthMode = "header") -> None:
        self.monthly: RuleVersionSnapshot = rule()
        self.undated: RuleVersionSnapshot = rule(recurrence=None)
        self.profiles = FakeProfileNodes([(TENANT, BUSINESS), (TENANT, EMPTY)])
        settings = ObligationSettings(
            _env_file=None,
            service_name="obligation",
            obligation_store="memory",
            **ISSUER.settings_overrides(mode),
        )
        self.app: FastAPI = build_app(
            settings,
            rules=FakeRuleVersionReader([self.monthly, self.undated]),
            members=FakeTenantMembers(),
            profiles=self.profiles,
        )
        made = self.app.state.wiring.materialise.run(
            MaterialiseRequest(TENANT, BUSINESS, DECISION, self.monthly, AS_OF, profile_version=2)
        )
        self.monthly_ids: tuple[ObligationId, ...] = made.created
        undated = self.app.state.wiring.materialise.run(
            MaterialiseRequest(TENANT, BUSINESS, DecisionId.new(), self.undated, AS_OF)
        )
        (self.undated_id,) = undated.created
        self.store.rule_version_refs().merge(ref_of(self.monthly))
        self.client = TestClient(self.app)

    @property
    def store(self) -> MemoryStore:
        store = self.app.state.wiring.unit_of_work
        assert isinstance(store, MemoryStore)
        return store

    def get(
        self, business: object = BUSINESS, headers: dict[str, str] | None = None, **params: Any
    ) -> Any:
        return self.client.get(
            path(business), params=params, headers=AS_TENANT if headers is None else headers
        )


@pytest.fixture
def api() -> Iterator[Api]:
    served = Api()
    with served.client:
        yield served


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def ids(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["obligation_id"] for item in response.json()["items"]]


def test_the_list_comes_by_due_date_with_the_rule_versions_facts(api: Api) -> None:
    response = api.get()
    assert response.status_code == 200, response.text
    body = response.json()
    items = body["items"]
    dated = [api.store.obligations[o] for o in api.monthly_ids]
    expected = [str(o.id) for o in sorted(dated, key=lambda o: (o.due_at, o.id.value))]
    assert [item["obligation_id"] for item in items] == [*expected, str(api.undated_id)]
    assert body["next_cursor"] is None
    first = items[0]
    assert (first["status"], first["profile_version"], first["business_id"]) == (
        "open",
        2,
        str(BUSINESS),
    )
    assert first["rule_version"]["rule_key"] == "gstr3b_monthly"
    assert first["rule_version"]["title"] == api.monthly.title
    assert (first["rule_version"]["seed_status"], first["rule_version"]["reviewed"]) == (
        "needs_review",
        False,
    )
    assert first["rule_version"]["approved_by"] == [str(ANALYST)]
    assert [c["quote"] for c in first["citations"]] == [CITATION.quote]
    last = items[-1]
    assert (last["due_at"], last["rule_version"], last["citations"]) == (None, None, [])
    assert api.profiles.asked == [], "a page with obligations needs no profile read"


def test_pages_follow_one_another_without_a_gap_or_a_repeat(api: Api) -> None:
    every = ids(api.get())
    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 1}
        if cursor is not None:
            params["cursor"] = cursor
        response = api.get(**params)
        seen += ids(response)
        cursor = response.json()["next_cursor"]
        if cursor is None:
            break
    assert seen == every
    assert len(every) == len(api.monthly_ids) + 1


class NaiveCursor(BaseModel):
    """A keyset this list never issues: a due date without its offset."""

    due_at: str
    id: str


def test_a_cursor_of_another_list_or_with_a_naive_date_is_422(api: Api) -> None:
    other_list = api.get(cursor=encode_cursor("profile.businesses", NaiveCursor(due_at="", id="")))
    naive = api.get(
        cursor=encode_cursor(
            LIST_SCOPE, NaiveCursor(due_at="2026-10-20T23:59:59", id=str(api.undated_id))
        )
    )
    assert (other_list.status_code, problem(other_list)) == (422, "pagination-cursor-invalid")
    assert (naive.status_code, problem(naive)) == (422, "pagination-cursor-invalid")


def test_the_status_and_the_window_keep_what_they_name(api: Api) -> None:
    done = api.monthly_ids[0]
    completed = api.client.post(
        f"/v1/obligations/{done}/status",
        json={"action": "complete"},
        headers={**AS_TENANT, "Idempotency-Key": "list-test-complete-1"},
    )
    assert completed.status_code == 200, completed.text
    assert ids(api.get(status="done")) == [str(done)]
    still = ids(api.get(status=["open", "in_progress"]))
    assert str(done) not in still
    assert str(api.undated_id) in still
    first_due = api.store.obligations[done].due_at
    assert first_due is not None
    day = first_due.astimezone(IST).date()
    windowed = ids(api.get(due_from=day.isoformat(), due_to=day.isoformat()))
    assert windowed == [str(done)], "a window keeps dated obligations of those days"
    assert str(api.undated_id) not in ids(api.get(due_from="2000-01-01"))


def test_a_window_longer_than_366_days_or_backwards_is_422(api: Api) -> None:
    long = api.get(due_from="2026-04-01", due_to="2027-04-02")
    backwards = api.get(due_from="2026-10-01", due_to="2026-09-30")
    assert (long.status_code, problem(long)) == (422, "obligation-window-invalid")
    assert (backwards.status_code, problem(backwards)) == (422, "obligation-window-invalid")
    assert api.get(due_from="2026-04-01", due_to="2027-04-01").status_code == 200


def test_a_business_without_obligations_reads_empty_once_the_profile_knows_it(api: Api) -> None:
    response = api.get(EMPTY)
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}
    assert api.profiles.asked == [(TENANT, EMPTY)]


def test_a_business_the_tenant_does_not_have_is_404(api: Api) -> None:
    unknown = api.get(BusinessId(UUID(int=0xBAD)))
    theirs = api.get(BUSINESS, headers=AS_OTHER)
    assert (unknown.status_code, problem(unknown)) == (404, "obligation-business-not-found")
    assert (theirs.status_code, problem(theirs)) == (404, "obligation-business-not-found")
    assert (OTHER_TENANT, BUSINESS) in api.profiles.asked, "row-level security hid them all"


def test_the_profile_is_asked_only_for_an_empty_page_and_its_outage_is_503(api: Api) -> None:
    api.profiles.down = True
    assert api.get().status_code == 200
    empty = api.get(EMPTY)
    assert (empty.status_code, problem(empty)) == (503, "profile-unavailable")


def test_a_tenant_is_required(api: Api) -> None:
    response = api.get(headers={})
    assert (response.status_code, problem(response)) == (401, "obligation-tenant-required")


def test_the_spec_names_the_member_roles_and_the_page_parameters(api: Api) -> None:
    spec = api.client.get("/openapi.json").json()
    operation = spec["paths"]["/v1/businesses/{business_id}/obligations"]["get"]
    assert operation["tags"] == ["public", "obligations"]
    assert operation["x-roles"] == ["owner", "staff", "ca_admin", "ca_staff", "compliance_lead"]
    names = {parameter["name"] for parameter in operation["parameters"]}
    assert {"status", "due_from", "due_to", "limit", "cursor"} <= names
    assert set(operation["responses"]) >= {"200", "401", "403", "404", "422", "503"}


def test_in_token_mode_a_member_reads_and_another_tenants_member_gets_404() -> None:
    api = Api("token")
    owner = bearer(ISSUER.user(TENANT, [Role.OWNER]))
    ca_staff = bearer(ISSUER.user(OTHER_TENANT, [Role.CA_STAFF]))
    acting = bearer(ISSUER.service("qa", [Scope.TENANT_ACT]))
    analyst = bearer(ISSUER.user(TENANT, [Role.ANALYST], mfa=True))
    with api.client:
        assert len(ids(api.get(headers=owner))) == len(api.monthly_ids) + 1
        assert len(ids(api.get(headers={**acting, **AS_TENANT}))) == len(api.monthly_ids) + 1
        foreign = api.get(headers=ca_staff)
        refused = api.get(headers=analyst)
        missing = api.get(headers=AS_TENANT)
    assert (foreign.status_code, problem(foreign)) == (404, "obligation-business-not-found")
    assert (refused.status_code, problem(refused)) == (403, "auth-forbidden")
    assert (missing.status_code, problem(missing)) == (401, "auth-token-required")


# ---------------------------------------------------------------- the use case and the store


def test_the_use_case_reads_a_page_after_a_keyset_and_keeps_the_order() -> None:
    store = MemoryStore()
    profiles = FakeProfileNodes([(TENANT, BUSINESS)])
    listing = ListBusinessObligations(store, profiles)
    monthly = rule()
    made = (
        MaterialiseObligations(store, window=4)
        .run(MaterialiseRequest(TENANT, BUSINESS, DECISION, monthly, AS_OF))
        .created
    )
    everything = listing.run(BusinessObligationsQuery(TENANT, BUSINESS, limit=50))
    assert [listed.obligation.id for listed in everything] == sorted(
        made, key=lambda o: (store.obligations[o].due_at, o.value)
    )
    second = everything[1].obligation
    rest = listing.run(
        BusinessObligationsQuery(
            TENANT, BUSINESS, limit=50, after=ListingAfter(second.due_at, second.id)
        )
    )
    assert [listed.obligation.id for listed in rest] == [
        listed.obligation.id for listed in everything[2:]
    ]
    assert all(listed.ref is None for listed in everything), "nothing cached yet"
    with pytest.raises(BusinessNotFoundError):
        listing.run(BusinessObligationsQuery(OTHER_TENANT, BUSINESS, limit=50))
    assert profiles.asked == [(OTHER_TENANT, BUSINESS)]
