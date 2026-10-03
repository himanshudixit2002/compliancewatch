"""The profile and rulebook clients against the routes and bodies of the committed specs."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx2
import pytest

from applicability_engine.domain.errors import DependencyUnavailableError
from applicability_engine.infrastructure.profile_client import HttpProfiles
from applicability_engine.infrastructure.rulebook_client import HttpRulebook
from applicability_engine.testing import BUSINESS, TENANT
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import RuleVersionId
from domain_kernel.operators import Operator
from domain_kernel.predicates import AllOf, Predicate
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
    ],
    ids=["5xx", "refused", "not-json", "bad-specification", "bad-status"],
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
