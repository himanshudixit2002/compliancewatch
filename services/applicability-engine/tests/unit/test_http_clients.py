"""The profile and rulebook clients against the routes and bodies of the committed specs."""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx2
import pytest

from applicability_engine.domain.errors import DependencyUnavailableError
from applicability_engine.domain.model import Schedule
from applicability_engine.infrastructure.profile_client import HttpProfiles
from applicability_engine.infrastructure.rulebook_client import HttpRulebook
from applicability_engine.testing import BUSINESS, TENANT
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, RuleVersionId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.operators import Operator
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import AllOf, Predicate
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import RuleVersionStatus

OPENAPI = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "openapi"
RULE_VERSION = RuleVersionId.new()

SNAPSHOT: dict[str, Any] = {
    "business_id": str(BUSINESS),
    "tenant_id": str(TENANT),
    "version": 4,
    "level": "registration",
    "lineage": [str(uuid4())],
    "as_of_fy": "2026-27",
    "attributes": {"registration_type": "regular", "state_codes": ["27", "29"]},
}
DETAIL: dict[str, Any] = {
    "rule_version_id": str(RULE_VERSION),
    "rule_id": str(uuid4()),
    "rule_key": "gst.gstr3b.monthly",
    "regulator": "cbic",
    "level": "registration",
    "version": 2,
    "status": "published",
    "title": "File GSTR-3B every month",
    "summary": "",
    "specification": {
        "all_of": [{"attribute": "registration_type", "operator": "eq", "value": "regular"}]
    },
    "obligation_template": {"title": "File GSTR-3B"},
    "recurrence": None,
    "effective_from": "2026-04-01",
    "effective_to": None,
    "source": {},
    "seed_status": "reviewed",
    "todo": [],
    "published_at": "2026-04-01T00:00:00Z",
    "high_impact": False,
    "approved_by": [str(uuid4())],
    "citations": [],
}

type Handler = Callable[[httpx2.Request], httpx2.Response]


def required(spec: str, schema: str) -> set[str]:
    document = json.loads((OPENAPI / spec).read_text(encoding="utf-8"))
    return set(document["components"]["schemas"][schema]["required"])


def test_the_sample_bodies_carry_every_field_the_specs_require() -> None:
    assert required("profile.v1.json", "SnapshotOut") <= set(SNAPSHOT)
    assert required("rulebook.v1.json", "RuleVersionDetailOut") <= set(DETAIL)


def answering(handler: Handler) -> httpx2.Client:
    return httpx2.Client(base_url="http://upstream.test", transport=httpx2.MockTransport(handler))


def test_the_profile_snapshot_is_read_for_the_tenant_and_year() -> None:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=SNAPSHOT)

    snapshot = HttpProfiles(client=answering(answer)).snapshot(
        TENANT, BUSINESS, FinancialYear(2026)
    )
    [request] = seen
    assert request.url.path == f"/v1/profile/nodes/{BUSINESS}/snapshot"
    assert request.url.params["fy"] == "2026-27"
    assert request.headers["x-tenant-id"] == str(TENANT)
    assert snapshot is not None
    assert (snapshot.business_id, snapshot.tenant_id, snapshot.version) == (BUSINESS, TENANT, 4)
    assert snapshot.as_of_fy == FinancialYear(2026)
    assert snapshot.attributes["state_codes"] == frozenset({"27", "29"})


def test_the_rule_version_is_read_with_its_status_and_specification() -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == f"/v1/rulebook/rule-versions/{RULE_VERSION}"
        return httpx2.Response(200, json=DETAIL)

    spec = HttpRulebook(client=answering(answer)).rule_version(RULE_VERSION)
    assert spec is not None
    assert (spec.rule_version_id, spec.status) == (RULE_VERSION, RuleVersionStatus.PUBLISHED)
    assert spec.specification == AllOf((Predicate("registration_type", Operator.EQ, "regular"),))
    assert (spec.rule_key, spec.level) == ("gst.gstr3b.monthly", AttributeLevel.REGISTRATION)
    assert spec.schedule == Schedule(EffectivePeriod(date(2026, 4, 1)))


def test_a_superseded_version_is_read_with_its_schedule() -> None:
    superseded = {
        **DETAIL,
        "status": "superseded",
        "effective_to": "2026-10-01",
        "recurrence": {"frequency": "monthly", "due_day": 20, "due_month_offset": 0},
        "obligation_template": {"title": "File GSTR-3B", "due_in_days": None},
    }

    def answer(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=superseded)

    spec = HttpRulebook(client=answering(answer)).rule_version(RULE_VERSION)
    assert spec is not None
    assert spec.schedule == Schedule(
        EffectivePeriod(date(2026, 4, 1), date(2026, 10, 1)), Recurrence.monthly(20)
    )
    assert spec.still_governs(date(2026, 10, 5)), "September is due on 20 October"
    assert not spec.still_governs(date(2026, 10, 21))


def test_a_404_is_none() -> None:
    def missing(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"type": "not-found"})

    assert HttpProfiles(client=answering(missing)).snapshot(TENANT, BUSINESS, None) is None
    assert HttpRulebook(client=answering(missing)).rule_version(RULE_VERSION) is None


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx2.Response(500, text="boom"),
        lambda request: httpx2.Response(403, json={"type": "forbidden"}),
        lambda request: httpx2.Response(200, text="not json"),
        lambda request: httpx2.Response(200, json={**DETAIL, "specification": {"oops": []}}),
        lambda request: httpx2.Response(200, json={**DETAIL, "status": "invented"}),
        lambda request: httpx2.Response(200, json={**DETAIL, "recurrence": {"due_day": 20}}),
        lambda request: httpx2.Response(
            200, json={**DETAIL, "obligation_template": {"due_in_days": -1}}
        ),
    ],
    ids=[
        "5xx",
        "refused",
        "not-json",
        "bad-specification",
        "bad-status",
        "bad-recurrence",
        "bad-due-in-days",
    ],
)
def test_anything_else_is_a_dependency_failure(handler: Handler) -> None:
    with pytest.raises(DependencyUnavailableError):
        HttpRulebook(client=answering(handler)).rule_version(RULE_VERSION)


def test_a_snapshot_of_the_wrong_shape_or_no_connection_is_a_dependency_failure() -> None:
    def wrong(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={**SNAPSHOT, "version": 0})

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    for handler in (wrong, unreachable):
        with pytest.raises(DependencyUnavailableError):
            HttpProfiles(client=answering(handler)).snapshot(TENANT, BUSINESS, None)


ENTITY = uuid4()
BUSINESS_BODY: dict[str, Any] = {
    "id": str(ENTITY),
    "name": "Example Traders",
    "pan": "ZZZZZ0000Z",
    "version": 3,
    "created_at": "2026-10-01T04:30:00Z",
    "updated_at": "2026-10-01T04:30:00Z",
    "attributes": [],
    "registrations": [
        {
            "id": str(BUSINESS),
            "level": "registration",
            "key": "29ZZZZZ0000Z1Z5",
            "name": "Example Traders Bengaluru",
            "parent_id": str(ENTITY),
            "version": 2,
            "created": False,
            "attributes": [],
        }
    ],
}
IN_FORCE = {key: DETAIL[key] for key in DETAIL if key != "citations"}


def version_body(
    rule_key: str, *, level: str = "registration", status: str = "published"
) -> dict[str, Any]:
    return {
        **IN_FORCE,
        "rule_version_id": str(uuid4()),
        "rule_key": rule_key,
        "level": level,
        "status": status,
    }


def test_the_sample_listing_bodies_carry_every_field_the_specs_require() -> None:
    assert required("profile.v1.json", "BusinessOut") <= set(BUSINESS_BODY)
    assert required("rulebook.v1.json", "RuleVersionOut") <= set(IN_FORCE)


def test_the_registrations_of_an_entity_are_read_for_the_tenant() -> None:
    seen: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=BUSINESS_BODY)

    profiles = HttpProfiles(client=answering(answer))
    assert profiles.registrations(TENANT, BusinessId(ENTITY)) == (BUSINESS,)
    [request] = seen
    assert request.url.path == f"/v1/businesses/{ENTITY}"
    assert request.headers["x-tenant-id"] == str(TENANT)

    def missing(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"type": "not-found"})

    assert HttpProfiles(client=answering(missing)).registrations(TENANT, BusinessId(ENTITY)) is None


def test_the_rules_in_force_are_paged_by_rule_key_and_kept_by_level_and_status() -> None:
    first = [version_body(f"rule_{index:03d}") for index in range(500)]
    first[1]["status"] = "superseded"
    first[2]["level"] = "entity"
    second = [version_body("rule_500")]
    asked: list[httpx2.QueryParams] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/rulebook/rule-versions"
        asked.append(request.url.params)
        return httpx2.Response(200, json=first if "after" not in request.url.params else second)

    rulebook = HttpRulebook(client=answering(answer))
    found = rulebook.rules_in_force(date(2026, 10, 1), AttributeLevel.REGISTRATION)
    assert [params.get("after") for params in asked] == [None, "rule_499"]
    assert {params["as_of"] for params in asked} == {"2026-10-01"}
    assert {params["limit"] for params in asked} == {"500"}
    assert len(found) == 499, "one superseded and one of the entity level left out"
    assert found[0].rule_key == "rule_000"
    assert found[0].spec.status is RuleVersionStatus.PUBLISHED
    assert found[0].effective_from == date(2026, 4, 1)
    assert found[0].effective_to is None
    (entity,) = rulebook.rules_in_force(date(2026, 10, 1), AttributeLevel.ENTITY)
    assert entity.rule_key == "rule_002"
    assert len(asked) == 4, "no cache: each read asks again"


def test_the_superseded_versions_are_paged_by_rule_key_and_version_and_kept_by_level() -> None:
    """A rule can have several superseded versions, so a page continues after a rule key and a
    version; a withdrawn version the rulebook would never list is left out all the same."""
    monthly = {"frequency": "monthly", "due_day": 20, "due_month_offset": 0}

    def ended(rule_key: str, version: int, **changes: Any) -> dict[str, Any]:
        return {
            **version_body(rule_key, status="superseded"),
            "version": version,
            "effective_to": "2026-10-01",
            "recurrence": monthly,
            **changes,
        }

    first = [ended(f"rule_{index:03d}", 1) for index in range(499)] + [ended("rule_499", 1)]
    first[1]["status"] = "withdrawn"
    first[2]["level"] = "entity"
    second = [ended("rule_499", 2, effective_from="2026-10-01", effective_to="2026-11-01")]
    asked: list[httpx2.QueryParams] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/rulebook/rule-versions"
        asked.append(request.url.params)
        return httpx2.Response(200, json=first if "after" not in request.url.params else second)

    rulebook = HttpRulebook(client=answering(answer))
    found = rulebook.rules_superseded_since(date(2025, 9, 1), AttributeLevel.REGISTRATION)
    assert [(p.get("after"), p.get("after_version")) for p in asked] == [
        (None, None),
        ("rule_499", "1"),
    ]
    assert {(p["ended_on_or_after"], p["status"], p["limit"]) for p in asked} == {
        ("2025-09-01", "superseded", "500")
    }
    assert "as_of" not in asked[0]
    assert len(found) == 499, "the withdrawn one and the one of the entity level left out"
    assert {rule.spec.status for rule in found} == {RuleVersionStatus.SUPERSEDED}
    last = found[-1]
    assert (last.rule_key, last.effective_from, last.effective_to) == (
        "rule_499",
        date(2026, 10, 1),
        date(2026, 11, 1),
    )
    assert last.spec.schedule == Schedule(
        EffectivePeriod(date(2026, 10, 1), date(2026, 11, 1)), Recurrence.monthly(20)
    )
    (entity,) = rulebook.rules_superseded_since(date(2025, 9, 1), AttributeLevel.ENTITY)
    assert entity.rule_key == "rule_002"


def test_the_listing_of_a_day_is_cached_for_its_ttl() -> None:
    asked: list[str] = []
    now = [100.0]

    def answer(request: httpx2.Request) -> httpx2.Response:
        asked.append(request.url.params["as_of"])
        return httpx2.Response(200, json=[version_body("only")])

    rulebook = HttpRulebook(client=answering(answer), cache_seconds=5, monotonic=lambda: now[0])
    day, other_day = date(2026, 10, 1), date(2026, 10, 2)
    for _ in range(3):
        assert len(rulebook.rules_in_force(day, AttributeLevel.REGISTRATION)) == 1
    rulebook.rules_in_force(day, AttributeLevel.ENTITY)
    rulebook.rules_in_force(other_day, AttributeLevel.REGISTRATION)
    assert asked == ["2026-10-01", "2026-10-02"]
    now[0] += 5.0
    rulebook.rules_in_force(day, AttributeLevel.REGISTRATION)
    assert asked == ["2026-10-01", "2026-10-02", "2026-10-01"], "read again once expired"
    rulebook.forget_in_force()
    rulebook.rules_in_force(day, AttributeLevel.REGISTRATION)
    assert asked[-1] == "2026-10-01", "a rule event drops the listing at once"
    assert len(asked) == 4
    with pytest.raises(ValueError, match="negative"):
        HttpRulebook(client=answering(answer), cache_seconds=-1)


def test_the_listing_of_superseded_versions_is_cached_apart_and_forgotten_with_it() -> None:
    asked: list[tuple[str, str]] = []
    now = [100.0]

    def answer(request: httpx2.Request) -> httpx2.Response:
        params = request.url.params
        listing = "as_of" if "as_of" in params else "ended_on_or_after"
        asked.append((listing, params[listing]))
        body = version_body("only", status="published" if listing == "as_of" else "superseded")
        return httpx2.Response(200, json=[{**body, "effective_to": "2026-10-01"}])

    rulebook = HttpRulebook(client=answering(answer), cache_seconds=5, monotonic=lambda: now[0])
    day = date(2026, 10, 1)
    for _ in range(2):
        assert len(rulebook.rules_superseded_since(day, AttributeLevel.REGISTRATION)) == 1
        rulebook.rules_in_force(day, AttributeLevel.REGISTRATION)
    assert asked == [("ended_on_or_after", "2026-10-01"), ("as_of", "2026-10-01")]
    rulebook.forget_in_force()
    rulebook.rules_superseded_since(day, AttributeLevel.ENTITY)
    assert asked[-1] == ("ended_on_or_after", "2026-10-01"), "a rule event drops both listings"
    now[0] += 5.0
    rulebook.rules_superseded_since(day, AttributeLevel.REGISTRATION)
    assert len(asked) == 4, "read again once expired"


def test_a_listing_of_the_wrong_shape_is_a_dependency_failure() -> None:
    def wrong(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[{**version_body("x"), "level": "planet"}])

    with pytest.raises(DependencyUnavailableError):
        HttpRulebook(client=answering(wrong)).rules_in_force(
            date(2026, 10, 1), AttributeLevel.REGISTRATION
        )
