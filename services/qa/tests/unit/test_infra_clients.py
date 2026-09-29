"""The rulebook, profile and obligation clients: the requests they send and how they read
the answers."""

import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import httpx2
import pytest

from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import (
    BusinessId,
    CanonicalEntityId,
    ClauseId,
    DocumentId,
    RuleVersionId,
    TenantId,
)
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import ObligationStatus
from qa.domain.errors import DependencyUnavailableError
from qa.domain.records import ResolutionStatus
from qa.infrastructure.obligation_client import HttpObligations
from qa.infrastructure.profile_client import HttpProfiles
from qa.infrastructure.rulebook_client import PAGE, HttpRulebook

TENANT = TenantId(UUID(int=1))
BUSINESS = BusinessId(UUID(int=2))
VERSION = RuleVersionId(UUID(int=3))
OTHER_VERSION = RuleVersionId(UUID(int=4))
CLAUSE = ClauseId(UUID(int=5))
DOCUMENT = DocumentId(UUID(int=6))
ENTITY = CanonicalEntityId(UUID(int=7))
MONTHLY = "gstr3b_monthly"


class Routes:
    """Answers by path; every request is kept."""

    def __init__(self, **routes: Any) -> None:
        self.routes = routes
        self.requests: list[httpx2.Request] = []

    def client(self) -> httpx2.Client:
        return httpx2.Client(base_url="http://svc.test", transport=httpx2.MockTransport(self))

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        found = self.routes.get(request.url.path)
        if found is None:
            return httpx2.Response(404, json={"title": "Not Found"})
        body = found(request) if callable(found) else found
        return httpx2.Response(200, json=body)


def version(key: str = MONTHLY, rule_version_id: UUID = VERSION.value) -> dict[str, Any]:
    return {
        "rule_version_id": str(rule_version_id),
        "rule_id": str(UUID(int=99)),
        "rule_key": key,
        "regulator": "cbic",
        "level": "registration",
        "version": 2,
        "status": "published",
        "title": "File FORM GSTR-3B every month",
        "summary": "Monthly return",
        "specification": {"attribute": "filing_scheme", "operator": "eq", "value": "x"},
        "obligation_template": {"title": "File GSTR-3B"},
        "recurrence": None,
        "effective_from": "2026-04-01",
        "effective_to": None,
        "source": {},
        "seed_status": "needs_review",
        "todo": [],
        "published_at": "2026-03-30T10:00:00Z",
        "high_impact": False,
    }


CLAUSE_OUT = {
    "clause_id": str(CLAUSE.value),
    "document_id": str(DOCUMENT.value),
    "clause_ref": "en.p3",
    "ordinal": 3,
    "page": 1,
    "text": "Clause text.",
    "regulator": "cbic",
    "doc_type": "notification",
    "external_ref": "01/2026-Central Tax",
    "title": "Notification 01/2026",
    "url": "https://example.invalid/n.pdf",
    "language": "en",
    "published_at": "2026-01-16",
}
ENTITY_OUT = {
    "entity_id": str(ENTITY.value),
    "entity_type": "form",
    "canonical_name": "GSTR-3B",
    "aliases": ["GSTR3B"],
}


def rulebook(routes: Routes) -> HttpRulebook:
    return HttpRulebook(client=routes.client())


def test_rules_in_force_are_read_page_by_page() -> None:
    def pages(request: httpx2.Request) -> list[dict[str, Any]]:
        if request.url.params.get("after") is None:
            return [version(f"k{n:03d}", UUID(int=1000 + n)) for n in range(PAGE)]
        return [version("zz", UUID(int=5000))]

    routes = Routes(**{"/v1/rulebook/rule-versions": pages})
    client = rulebook(routes)
    found = client.rules_in_force(date(2026, 4, 10), rule_key=MONTHLY, regulator="cbic")
    client.close()
    assert len(found) == PAGE + 1
    first = found[0]
    assert (first.rule_key, first.version, first.status, first.summary) == (
        "k000",
        2,
        "published",
        "Monthly return",
    )
    assert (first.effective_from, first.effective_to) == (date(2026, 4, 1), None)
    assert first.specification == {"attribute": "filing_scheme", "operator": "eq", "value": "x"}
    params = [dict(request.url.params) for request in routes.requests]
    assert params == [
        {"as_of": "2026-04-10", "limit": "500", "rule_key": MONTHLY, "regulator": "cbic"},
        {
            "as_of": "2026-04-10",
            "limit": "500",
            "rule_key": MONTHLY,
            "regulator": "cbic",
            "after": "k499",
        },
    ]


def test_a_rule_version_with_its_citations() -> None:
    citation = {
        "citation_id": str(UUID(int=11)),
        "rule_version_id": str(VERSION.value),
        "clause_id": str(CLAUSE.value),
        "document_id": str(DOCUMENT.value),
        "clause_ref": "en.p3",
        "quote": "is extended",
        "verified": True,
        "match_score": 1.0,
        "verified_at": "2026-03-30T10:00:00Z",
    }
    detail = {**version(), "effective_to": "2027-04-01", "citations": [citation]}
    routes = Routes(**{f"/v1/rulebook/rule-versions/{VERSION}": detail})
    found = rulebook(routes).rule_version(VERSION)
    assert found is not None
    assert found.version.effective_to == date(2027, 4, 1)
    (cited,) = found.citations
    assert (cited.clause_id, cited.document_id, cited.quote, cited.verified) == (
        CLAUSE,
        DOCUMENT,
        "is extended",
        True,
    )
    assert rulebook(Routes()).rule_version(OTHER_VERSION) is None


@pytest.mark.parametrize(
    ("answer", "status", "found", "candidates"),
    [
        ({"status": "resolved", "entity": ENTITY_OUT, "candidates": []}, "resolved", True, 0),
        (
            {"status": "ambiguous", "entity": None, "candidates": [ENTITY_OUT, ENTITY_OUT]},
            "ambiguous",
            False,
            2,
        ),
        ({"status": "unqualified", "entity": None, "candidates": []}, "unqualified", False, 0),
    ],
)
def test_resolving_a_name_reads_the_status(
    answer: dict[str, Any], status: str, found: bool, candidates: int
) -> None:
    body = {**answer, "entity_type": "form", "name": "gstr 3b", "normalised": "GSTR-3B"}
    routes = Routes(**{"/v1/rulebook/entities/resolve": body})
    resolution = rulebook(routes).resolve_entity(EntityType.FORM, "gstr 3b")
    assert resolution.status is ResolutionStatus(status)
    assert (resolution.entity is not None, len(resolution.candidates)) == (found, candidates)
    assert dict(routes.requests[0].url.params) == {"type": "form", "name": "gstr 3b"}
    if resolution.entity is not None:
        assert resolution.entity.aliases == ("GSTR3B",)


def test_the_clauses_of_an_entity() -> None:
    mentioned = {
        **CLAUSE_OUT,
        "mentions": [{"text": "GSTR-3B", "span_start": 0, "span_end": 7}],
        "out_of_force": True,
    }
    routes = Routes(**{f"/v1/rulebook/entities/{ENTITY}/clauses": [mentioned]})
    (clause,) = rulebook(routes).entity_clauses(ENTITY, as_of=date(2026, 4, 10), limit=5)
    assert (clause.clause_id, clause.source, clause.published_at, clause.out_of_force) == (
        CLAUSE,
        "01/2026-Central Tax",
        date(2026, 1, 16),
        True,
    )
    assert dict(routes.requests[0].url.params) == {"limit": "5", "as_of": "2026-04-10"}
    assert rulebook(Routes()).entity_clauses(ENTITY, as_of=None, limit=5) == ()


def test_relations_name_the_ends_asked_for() -> None:
    row: dict[str, Any] = {
        "relation_id": str(UUID(int=12)),
        "from_rule_version_id": str(OTHER_VERSION.value),
        "relation": "extends_deadline",
        "to_kind": "rule_version",
        "to_ref": str(VERSION.value),
        "to_rule_version_id": str(VERSION.value),
        "to_entity_id": None,
        "evidence_clause_id": str(CLAUSE.value),
        "evidence_clause_ref": "en.p3",
        "evidence_document_id": str(DOCUMENT.value),
        "candidate_id": None,
        "period_label": "2026-03",
        "new_due_on": "2026-04-24",
    }
    to_entity = {**row, "to_kind": "form", "to_ref": "GSTR-3B", "to_rule_version_id": None}
    to_entity.update(to_entity_id=str(ENTITY.value), period_label=None, new_due_on=None)
    routes = Routes(**{"/v1/rulebook/relations": [row, to_entity]})
    first, second = rulebook(routes).relations(to_rule_version_id=VERSION)
    assert (first.relation, first.to_rule_version_id, first.period_label, first.new_due_on) == (
        RelationKind.EXTENDS_DEADLINE,
        VERSION,
        "2026-03",
        date(2026, 4, 24),
    )
    assert (second.to_entity_id, second.to_rule_version_id) == (ENTITY, None)
    assert dict(routes.requests[0].url.params) == {
        "limit": "500",
        "to_rule_version_id": str(VERSION),
    }
    rulebook(routes).relations(from_rule_version_id=VERSION, to_entity_id=ENTITY)
    assert set(routes.requests[1].url.params) == {"limit", "from_rule_version_id", "to_entity_id"}


def test_a_clause_or_nothing() -> None:
    routes = Routes(**{f"/v1/rulebook/clauses/{CLAUSE}": CLAUSE_OUT})
    clause = rulebook(routes).clause(CLAUSE)
    assert clause is not None
    assert (clause.clause_ref, clause.text, clause.doc_type, clause.out_of_force) == (
        "en.p3",
        "Clause text.",
        "notification",
        False,
    )
    assert rulebook(Routes()).clause(CLAUSE) is None


def test_search_sends_the_vector_with_its_model() -> None:
    hit = {
        **{key: CLAUSE_OUT[key] for key in ("clause_id", "document_id", "clause_ref", "text")},
        "regulator": "cbic",
        "doc_type": "notification",
        "published_at": None,
        "score": 0.0325,
        "lexical_rank": 1,
        "vector_rank": None,
        "cited_by": [str(VERSION.value)],
        "out_of_force": False,
    }
    routes = Routes(**{"/v1/rulebook/search": [hit, {**hit, "out_of_force": True}]})
    found, ended = rulebook(routes).search(
        "due date", vector=(0.5, 0.5), model="fake/hash-ngram-512", as_of=date(2026, 4, 10), k=8
    )
    assert (found.score, found.cited_by, found.clause.published_at) == (0.0325, (VERSION,), None)
    assert (found.clause.out_of_force, ended.clause.out_of_force) == (False, True)
    assert json.loads(routes.requests[0].content) == {
        "text": "due date",
        "k": 8,
        "vector": [0.5, 0.5],
        "model": "fake/hash-ngram-512",
        "as_of": "2026-04-10",
    }
    rulebook(routes).search("due date", vector=None, model=None, as_of=None, k=3)
    assert json.loads(routes.requests[1].content) == {"text": "due date", "k": 3}


def test_an_answer_of_the_wrong_shape_is_a_dependency_failure() -> None:
    routes = Routes(**{"/v1/rulebook/rule-versions": [{"rule_key": "x"}]})
    with pytest.raises(DependencyUnavailableError, match="rulebook answered an unexpected shape"):
        rulebook(routes).rules_in_force(date(2026, 4, 10))


def test_a_profile_snapshot_with_sets_and_the_tenant() -> None:
    snapshot = {
        "business_id": str(BUSINESS.value),
        "tenant_id": str(TENANT.value),
        "version": 3,
        "attributes": {"state_codes": ["27", "29"], "filing_scheme": "regular_monthly"},
        "as_of_fy": "2026-27",
        "level": "registration",
        "lineage": [str(UUID(int=20))],
    }
    routes = Routes(**{f"/v1/profile/nodes/{BUSINESS}/snapshot": snapshot})
    client = HttpProfiles(client=routes.client())
    found = client.snapshot(TENANT, BUSINESS, FinancialYear(2026))
    client.close()
    assert found is not None
    assert found.attributes["state_codes"] == frozenset({"27", "29"})
    assert (found.version, found.as_of_fy, found.level) == (
        3,
        FinancialYear(2026),
        AttributeLevel.REGISTRATION,
    )
    assert found.lineage == (BusinessId(UUID(int=20)),)
    request = routes.requests[0]
    assert (request.headers["x-tenant-id"], dict(request.url.params)) == (
        str(TENANT),
        {"fy": "2026-27"},
    )
    bare = {**snapshot, "as_of_fy": None, "level": None, "lineage": []}
    routes.routes[f"/v1/profile/nodes/{BUSINESS}/snapshot"] = bare
    found = HttpProfiles(client=routes.client()).snapshot(TENANT, BUSINESS, None)
    assert found is not None
    assert (found.as_of_fy, found.level) == (None, None)
    assert dict(routes.requests[1].url.params) == {}
    assert HttpProfiles(client=Routes().client()).snapshot(TENANT, BUSINESS, None) is None


def test_obligations_in_a_window_with_the_tenant() -> None:
    row: dict[str, Any] = {
        "obligation_id": str(UUID(int=30)),
        "business_id": str(BUSINESS.value),
        "rule_version_id": str(VERSION.value),
        "decision_id": str(UUID(int=31)),
        "title": "File GSTR-3B for the month (2026-03)",
        "steps": [],
        "evidence_type": "filing_acknowledgement",
        "period_label": "2026-03",
        "period_start": "2026-03-01",
        "period_end": "2026-04-01",
        "due_at": "2026-04-20T18:29:59Z",
        "status": "open",
        "closed_at": None,
        "closed_reason": None,
    }
    undated = {**row, "due_at": None, "period_label": None, "status": "done"}
    routes = Routes(**{"/v1/obligation/obligations": [row, undated]})
    client = HttpObligations(client=routes.client())
    first, second = client.obligations(
        TENANT,
        BUSINESS,
        due_from=date(2026, 4, 1),
        due_to=date(2026, 4, 30),
        rule_version_id=VERSION,
    )
    client.close()
    assert first.due_at == datetime(2026, 4, 20, 18, 29, 59, tzinfo=UTC)
    assert (first.due_on, first.status, first.period_label) == (
        date(2026, 4, 20),
        ObligationStatus.OPEN,
        "2026-03",
    )
    assert (second.due_at, second.period_label, second.is_open) == (None, None, False)
    request = routes.requests[0]
    assert request.headers["x-tenant-id"] == str(TENANT)
    assert dict(request.url.params) == {
        "business_id": str(BUSINESS),
        "due_from": "2026-04-01",
        "due_to": "2026-04-30",
        "rule_version_id": str(VERSION),
    }
    assert HttpObligations(client=routes.client()).obligations(TENANT, BUSINESS)
    assert dict(routes.requests[1].url.params) == {"business_id": str(BUSINESS)}
