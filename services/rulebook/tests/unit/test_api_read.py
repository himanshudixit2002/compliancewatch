"""The read routes over HTTP: open reads, route order, statuses and problem types."""

from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.documents import clause_id_for, document_id_for
from domain_kernel.knowledge import EntityType, RelationKind, RuleRelation
from domain_kernel.status import RuleVersionStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.testing import WRITE_TOKEN

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOC = document_id_for(DIGEST)
BASE = "/v1/rulebook"
TEXT = "hereby extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"
JULY = date(2026, 7, 1)
OCTOBER = date(2026, 10, 1)


@pytest.fixture
def store(app: FastAPI, client: TestClient) -> MemoryKnowledgeStore:
    body = {
        "source_id": str(UUID(int=7)),
        "sha256": DIGEST,
        "regulator": "CBIC",
        "doc_type": "notification",
        "external_ref": "09/2026-Central Tax",
        "url": "https://example.invalid/n.pdf",
        "language": "en",
        "media_type": "application/pdf",
        "parser_version": "pdf@1",
        "published_at": "2026-03-28",
        "fetched_at": "2026-09-28T06:00:00Z",
        "clauses": [{"clause_ref": "en.p1", "text": TEXT, "page": 1}],
    }
    headers = {"x-cw-write-token": WRITE_TOKEN}
    assert client.put(f"{BASE}/documents/{DOC}", json=body, headers=headers).status_code == 201
    memory: MemoryKnowledgeStore = app.state.wiring.unit_of_work
    return memory


def test_rule_versions_in_force_on_a_date(client: TestClient, store: MemoryKnowledgeStore) -> None:
    _, version = store.add_rule(
        "gstr3b_monthly",
        title="GSTR-3B",
        status=RuleVersionStatus.PUBLISHED,
        effective_from=date(2026, 4, 1),
        effective_to=date(2026, 7, 1),
    )
    store.add_rule("gstr1_monthly", status=RuleVersionStatus.DRAFT)
    response = client.get(f"{BASE}/rule-versions", params={"as_of": "2026-06-30"})
    assert response.status_code == 200
    (found,) = response.json()
    assert found["rule_version_id"] == str(version)
    assert (found["status"], found["effective_to"], found["seed_status"]) == (
        "published",
        "2026-07-01",
        "needs_review",
    )
    assert client.get(f"{BASE}/rule-versions", params={"as_of": "2026-07-01"}).json() == []
    assert client.get(f"{BASE}/rule-versions").status_code == 422
    paged = client.get(
        f"{BASE}/rule-versions", params={"as_of": "2026-06-30", "after": "gstr3b_monthly"}
    )
    assert paged.json() == []


def test_rule_versions_that_ended_on_or_after_a_date(
    client: TestClient, store: MemoryKnowledgeStore
) -> None:
    """The versions superseded since a day, whose periods may still be due; never a withdrawn
    one, and never one still open-ended."""
    superseded, published = RuleVersionStatus.SUPERSEDED, RuleVersionStatus.PUBLISHED
    _, old = store.add_rule(
        "gstr3b_monthly", status=superseded, effective_from=date(2026, 4, 1), effective_to=OCTOBER
    )
    store.add_version("gstr3b_monthly", status=published, effective_from=OCTOBER)
    _, cut = store.add_rule(
        "gstr1_monthly",
        status=published,
        effective_from=date(2026, 4, 1),
        effective_to=date(2027, 1, 1),
    )
    store.add_rule(
        "cmp08_quarterly",
        status=RuleVersionStatus.WITHDRAWN,
        effective_from=date(2026, 4, 1),
        effective_to=OCTOBER,
    )
    store.add_rule("gstr9_annual", status=published, effective_from=date(2026, 4, 1))

    def listed(**params: str) -> list[tuple[str, str]]:
        response = client.get(f"{BASE}/rule-versions", params=params)
        assert response.status_code == 200, response.text
        return [(v["rule_version_id"], v["status"]) for v in response.json()]

    since = {"ended_on_or_after": "2026-09-15"}
    assert listed(**since, status="superseded") == [(str(old), "superseded")]
    assert listed(**since) == [(str(cut), "published"), (str(old), "superseded")]
    assert listed(**since, status="published") == [(str(cut), "published")]
    assert listed(ended_on_or_after="2026-10-01", status="superseded") == [(str(old), "superseded")]
    assert listed(ended_on_or_after="2026-10-02", status="superseded") == []
    assert listed(as_of="2026-10-01", status="superseded") == [], "no longer in force"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"as_of": "2026-10-01", "ended_on_or_after": "2026-09-01"},
        {"ended_on_or_after": "2026-09-01", "status": "withdrawn"},
        {"ended_on_or_after": "2026-09-01", "status": "draft"},
        {"ended_on_or_after": "2026-09-01", "after_version": "1"},
        {"ended_on_or_after": "2026-09-01", "after": "a_rule", "after_version": "0"},
    ],
)
def test_a_listing_names_one_day_and_a_listed_status(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get(f"{BASE}/rule-versions", params=params)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_ended_versions_page_by_rule_key_and_version(
    client: TestClient, store: MemoryKnowledgeStore
) -> None:
    superseded = RuleVersionStatus.SUPERSEDED
    store.add_rule(
        "gstr3b_monthly", status=superseded, effective_from=date(2026, 4, 1), effective_to=JULY
    )
    store.add_version(
        "gstr3b_monthly", status=superseded, effective_from=JULY, effective_to=OCTOBER
    )
    store.add_version("gstr3b_monthly", status=RuleVersionStatus.PUBLISHED, effective_from=OCTOBER)
    store.add_rule(
        "gstr1_monthly", status=superseded, effective_from=date(2026, 4, 1), effective_to=OCTOBER
    )
    pages: list[list[tuple[str, int]]] = []
    params: dict[str, str | int] = {
        "ended_on_or_after": "2026-07-01",
        "status": "superseded",
        "limit": 1,
    }
    while True:
        page = client.get(f"{BASE}/rule-versions", params=params).json()
        if not page:
            break
        pages.append([(v["rule_key"], v["version"]) for v in page])
        params.update(after=page[-1]["rule_key"], after_version=page[-1]["version"])
    assert pages == [[("gstr1_monthly", 1)], [("gstr3b_monthly", 1)], [("gstr3b_monthly", 2)]]
    by_key = client.get(
        f"{BASE}/rule-versions",
        params={"ended_on_or_after": "2026-07-01", "after": "gstr1_monthly"},
    )
    assert [(v["rule_key"], v["version"]) for v in by_key.json()] == [
        ("gstr3b_monthly", 1),
        ("gstr3b_monthly", 2),
    ]


def test_a_rule_version_with_its_citations(client: TestClient, store: MemoryKnowledgeStore) -> None:
    _, version = store.add_rule("gstr3b_extension", title="Extension")
    citation = store.add_citation(version, clause_id_for(DOC, "en.p1"), "extends the due date")
    detail = client.get(f"{BASE}/rule-versions/{version}")
    assert detail.status_code == 200
    body = detail.json()
    assert (body["status"], body["title"], body["published_at"]) == ("draft", "Extension", None)
    assert body["approved_by"] == [], "no approvers until it is published"
    assert [c["citation_id"] for c in body["citations"]] == [str(citation)]
    assert body["citations"][0]["clause_ref"] == "en.p1"
    assert body["citations"][0]["document_id"] == str(DOC)
    listed = client.get(f"{BASE}/rule-versions/{version}/citations")
    assert listed.json() == body["citations"]


@pytest.mark.parametrize("suffix", ["", "/citations"])
def test_an_unknown_rule_version_is_404(client: TestClient, suffix: str) -> None:
    response = client.get(f"{BASE}/rule-versions/{UUID(int=5)}{suffix}")
    assert response.status_code == 404
    assert response.json()["type"].endswith("rulebook-rule-version-not-found")


def test_every_version_of_a_rule(client: TestClient, store: MemoryKnowledgeStore) -> None:
    _, first = store.add_rule("gstr3b_monthly", title="GSTR-3B", status=RuleVersionStatus.PUBLISHED)
    second = store.add_version("gstr3b_monthly", title="GSTR-3B", effective_from=date(2026, 7, 1))
    response = client.get(f"{BASE}/rules/gstr3b_monthly/versions")
    assert response.status_code == 200
    assert [(v["rule_version_id"], v["version"], v["status"]) for v in response.json()] == [
        (str(first), 1, "published"),
        (str(second), 2, "draft"),
    ]
    unknown = client.get(f"{BASE}/rules/no_such_rule/versions")
    assert (unknown.status_code, unknown.json()["type"]) == (
        404,
        "urn:compliancewatch:problem:rulebook-rule-not-found",
    )
    assert client.get(f"{BASE}/rules/Not-A-Key/versions").status_code == 422


def test_resolve_answers_200_with_a_status(client: TestClient, store: MemoryKnowledgeStore) -> None:
    form = store.add_entity(EntityType.FORM, "GSTR-3B")
    resolved = client.get(f"{BASE}/entities/resolve", params={"type": "form", "name": "gstr 3b"})
    assert resolved.status_code == 200
    assert resolved.json() == {
        "status": "resolved",
        "entity_type": "form",
        "name": "gstr 3b",
        "normalised": "GSTR-3B",
        "entity": {
            "entity_id": str(form),
            "entity_type": "form",
            "canonical_name": "GSTR-3B",
            "aliases": [],
        },
        "candidates": [],
    }
    for name, status in (("GSTR-9", "not_found"), ("", "empty")):
        response = client.get(f"{BASE}/entities/resolve", params={"type": "form", "name": name})
        assert (response.status_code, response.json()["status"]) == (200, status)
    unqualified = client.get(
        f"{BASE}/entities/resolve", params={"type": "section", "name": "section 39"}
    )
    assert unqualified.json()["status"] == "unqualified"


@pytest.mark.parametrize(
    "params", [{"type": "colour", "name": "x"}, {"name": "x"}, {"type": "form"}]
)
def test_resolve_needs_a_known_type_and_a_name(client: TestClient, params: dict[str, str]) -> None:
    assert client.get(f"{BASE}/entities/resolve", params=params).status_code == 422


def test_an_entity_and_the_clauses_that_mention_it(
    client: TestClient, store: MemoryKnowledgeStore
) -> None:
    form = store.add_entity(EntityType.FORM, "GSTR-3B", aliases=["GSTR-3B-M"])
    start = TEXT.index("FORM GSTR-3B")
    with store() as uow:
        uow.mentions.add(
            clause_id_for(DOC, "en.p1"),
            form,
            "FORM GSTR-3B",
            start,
            start + 12,
            method="grammar",
            extractor="grammar@1",
        )
    entity = client.get(f"{BASE}/entities/{form}")
    assert entity.status_code == 200
    assert entity.json()["aliases"] == ["GSTR-3B-M"]
    clauses = client.get(f"{BASE}/entities/{form}/clauses").json()
    assert [(c["clause_ref"], c["external_ref"], c["published_at"]) for c in clauses] == [
        ("en.p1", "09/2026-Central Tax", "2026-03-28")
    ]
    assert clauses[0]["mentions"] == [
        {"text": "FORM GSTR-3B", "span_start": start, "span_end": start + 12}
    ]
    before = client.get(f"{BASE}/entities/{form}/clauses", params={"as_of": "2026-03-27"})
    assert before.json() == []
    assert clauses[0]["out_of_force"] is False
    _, withdrawn = store.add_rule("gstr3b_monthly", status=RuleVersionStatus.WITHDRAWN)
    store.add_citation(withdrawn, clause_id_for(DOC, "en.p1"), "FORM GSTR-3B")
    later = client.get(f"{BASE}/entities/{form}/clauses", params={"as_of": "2026-10-01"})
    assert [c["out_of_force"] for c in later.json()] == [True]


@pytest.mark.parametrize("suffix", ["", "/clauses"])
def test_an_unknown_entity_is_404(client: TestClient, suffix: str) -> None:
    response = client.get(f"{BASE}/entities/{UUID(int=5)}{suffix}")
    assert response.status_code == 404
    assert response.json()["type"].endswith("rulebook-entity-not-found")


def test_relations_need_one_end(client: TestClient, store: MemoryKnowledgeStore) -> None:
    _, monthly = store.add_rule("gstr3b_monthly", status=RuleVersionStatus.PUBLISHED)
    _, extension = store.add_rule("gstr3b_extension", status=RuleVersionStatus.PUBLISHED)
    relation_id = uuid4()
    with store() as uow:
        uow.relations.add(
            RuleRelation(
                extension, RelationKind.EXTENDS_DEADLINE, monthly, clause_id_for(DOC, "en.p1")
            ),
            relation_id=relation_id,
            candidate_id=None,
        )
    response = client.get(f"{BASE}/relations", params={"to_rule_version_id": str(monthly)})
    assert response.status_code == 200
    (found,) = response.json()
    assert found["relation_id"] == str(relation_id)
    assert (found["relation"], found["to_kind"], found["evidence_clause_ref"]) == (
        "extends_deadline",
        "rule_version",
        "en.p1",
    )
    assert found["evidence_document_id"] == str(DOC)
    missing = client.get(f"{BASE}/relations", params={"relation": "supersedes"})
    assert missing.status_code == 422
    assert missing.json()["type"].endswith("invariant-violation")


def test_a_clause_with_its_document(client: TestClient, store: MemoryKnowledgeStore) -> None:
    clause_id = clause_id_for(DOC, "en.p1")
    response = client.get(f"{BASE}/clauses/{clause_id}")
    assert response.status_code == 200
    body = response.json()
    assert (body["clause_ref"], body["text"], body["regulator"], body["doc_type"]) == (
        "en.p1",
        TEXT,
        "CBIC",
        "notification",
    )
    unknown = client.get(f"{BASE}/clauses/{UUID(int=5)}")
    assert unknown.status_code == 404
    assert unknown.json()["type"].endswith("rulebook-clause-unknown")
