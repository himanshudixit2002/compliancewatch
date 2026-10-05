"""The changes feed on the memory store: one item per published change from the decision log
(publications, supersessions, withdrawals and deadline changes), what each carries of its
version, the filters, and the pages; then ``GET /v1/changes`` over HTTP."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, RuleVersionId, SourceId, UserId
from domain_kernel.knowledge import EntityType, RelationKind, RuleRelation
from domain_kernel.status import RuleVersionStatus
from rulebook.application.changes import ListChanges
from rulebook.application.documents import RegisterDocument
from rulebook.application.publication import (
    AddCitations,
    ApproveVersion,
    CitationInput,
    PublishVersion,
    SubmitForReview,
    WithdrawVersion,
)
from rulebook.domain.changes import (
    ChangeEntry,
    ChangeKey,
    ChangeQuery,
    RuleChangeKind,
    deadline_change_id,
    newest_first,
)
from rulebook.domain.documents import StoredDocument
from rulebook.domain.relations import RelationCandidate
from rulebook.domain.seed import SeedStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app
from rulebook.testing import rulebook_settings

TEXT = (
    "The due date for furnishing the return in FORM GSTR-3B for the month of September, 2026 "
    "is extended till the 27th day of October, 2026."
)
QUOTE = "furnishing the return in FORM GSTR-3B for the month of September, 2026"
APRIL = date(2026, 4, 1)
JULY = date(2026, 7, 1)
START = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
"""10:00 in India on 1 October 2026."""
ANALYST = UserId(UUID(int=11))
REVIEWER = UserId(UUID(int=12))
SECOND_REVIEWER = UserId(UUID(int=13))
SPECIFICATION = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
CHANGES = "/v1/changes"


class Clock:
    """Moves one minute on every reading, so every step has its own time."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


class Flow:
    """The publish flow on one store and one clock; synthetic approvals allowed."""

    def __init__(self, store: MemoryKnowledgeStore, clock: Clock) -> None:
        self.store = store
        self.cite = AddCitations(store, clock)
        self.submit = SubmitForReview(store, clock)
        self.approve = ApproveVersion(store, clock, synthetic_allowed=True)
        self.publish = PublishVersion(store, enabled=True, clock=clock)
        self.withdraw = WithdrawVersion(store, enabled=True, clock=clock)

    def published(
        self, version: RuleVersionId, clause: ClauseId, *, synthetic: bool = False
    ) -> None:
        self.cite.run(version, [CitationInput(clause, QUOTE)])
        self.submit.run(version, actor_id=ANALYST, high_impact=synthetic)
        self.approve.run(version, actor_id=REVIEWER, synthetic=synthetic)
        if synthetic:
            self.approve.run(version, actor_id=SECOND_REVIEWER, synthetic=True)
        self.publish.run(version, actor_id=ANALYST)

    def relate(
        self,
        x: RuleVersionId,
        kind: RelationKind,
        y: RuleVersionId,
        clause: ClauseId,
        candidate_id: UUID | None = None,
    ) -> UUID:
        relation_id = uuid4()
        with self.store() as uow:
            uow.relations.add(
                RuleRelation(x, kind, y, clause), relation_id=relation_id, candidate_id=candidate_id
            )
        return relation_id


@pytest.fixture
def store() -> MemoryKnowledgeStore:
    return MemoryKnowledgeStore()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def flow(store: MemoryKnowledgeStore, clock: Clock) -> Flow:
    return Flow(store, clock)


@pytest.fixture
def clause(store: MemoryKnowledgeStore) -> ClauseId:
    digest = hashlib.sha256(b"changes feed").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/changes.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=START,
            published_at=date(2026, 9, 30),
        ),
        [Clause("en.p1", TEXT)],
    )
    return clause_id_for(document_id, "en.p1")


def draft(store: MemoryKnowledgeStore, key: str, *, regulator: str = "CBIC") -> RuleVersionId:
    _, version = store.add_rule(
        key,
        title=f"{key} (example)",
        regulator=regulator,
        specification=SPECIFICATION,
        effective_from=JULY,
    )
    return version


def feed(store: MemoryKnowledgeStore, **query: Any) -> list[Any]:
    return list(ListChanges(store).run(ChangeQuery(**{"limit": 100, **query})))


# ---------------------------------------------------------------- what the feed lists


def test_a_publication_is_one_change_with_its_review_and_citations(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store, "gstr9_annual")
    assert feed(store) == [], "a draft is not a change"
    flow.cite.run(version, [CitationInput(clause, QUOTE)])
    flow.submit.run(version, actor_id=ANALYST)
    flow.approve.run(version, actor_id=REVIEWER)
    assert feed(store) == [], "neither a submission nor an approval is a change"
    flow.publish.run(version, actor_id=ANALYST)

    (change,) = feed(store)
    published = next(d for d in store.decisions(version) if d.action.value == "published")
    assert change.entry == ChangeEntry(
        change_id=published.decision_id,
        kind=RuleChangeKind.PUBLISHED,
        changed_at=published.decided_at,
        rule_version_id=version,
    )
    assert (change.version.rule_key, change.version.status) == (
        "gstr9_annual",
        RuleVersionStatus.PUBLISHED,
    )
    assert change.version.seed_status is SeedStatus.REVIEWED
    assert change.approved_by == (REVIEWER,)
    (citation,) = change.citations
    assert (citation.clause_id, citation.quote, citation.verified) == (clause, QUOTE, True)
    assert change.relations == ()


def test_a_synthetic_publication_names_its_approvers_and_still_needs_review(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store, "gstr9_annual")
    flow.published(version, clause, synthetic=True)
    (change,) = feed(store)
    assert change.version.seed_status is SeedStatus.NEEDS_REVIEW
    assert set(change.approved_by) == {REVIEWER, SECOND_REVIEWER}


def test_a_supersession_and_a_withdrawal_are_changes_of_the_version_they_end(
    store: MemoryKnowledgeStore, flow: Flow, clock: Clock, clause: ClauseId
) -> None:
    _, old = store.add_rule(
        "gstr1_monthly",
        title="GSTR-1 monthly (example)",
        status=RuleVersionStatus.PUBLISHED,
        effective_from=APRIL,
        published_at=START,
    )
    new = store.add_version("gstr1_monthly", title="GSTR-1 monthly, v2", effective_from=JULY)
    flow.relate(new, RelationKind.SUPERSEDES, old, clause)
    flow.published(new, clause)
    flow.withdraw.run(new, actor_id=ANALYST, note="rescinded")

    withdrawn, *publication = feed(store)
    assert [c.entry.change_id for c in publication] == sorted(
        (c.entry.change_id for c in publication), reverse=True
    ), "one moment: by change id"
    by_kind = {change.entry.kind: change for change in publication}
    superseded = by_kind[RuleChangeKind.SUPERSEDED]
    published = by_kind[RuleChangeKind.PUBLISHED]
    assert (withdrawn.entry.kind, withdrawn.entry.rule_version_id) == (
        RuleChangeKind.WITHDRAWN,
        new,
    )
    assert withdrawn.entry.caused_by is None, "an analyst withdrew it"
    assert (superseded.entry.kind, superseded.entry.rule_version_id) == (
        RuleChangeKind.SUPERSEDED,
        old,
    )
    assert superseded.entry.caused_by == new
    assert superseded.entry.changed_at == published.entry.changed_at
    assert superseded.version.status is RuleVersionStatus.SUPERSEDED
    assert superseded.approved_by == (), "a version set as published never had a review round"
    assert published.entry.kind is RuleChangeKind.PUBLISHED
    assert [(r.relation, r.to_rule_version_id) for r in published.relations] == [
        (RelationKind.SUPERSEDES, old)
    ]
    assert published.version.status is RuleVersionStatus.WITHDRAWN, "the version as it stands"


def test_a_deadline_extension_is_a_change_of_the_version_whose_date_moves(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    _, monthly = store.add_rule(
        "gstr3b_monthly",
        title="GSTR-3B monthly (example)",
        status=RuleVersionStatus.PUBLISHED,
        effective_from=APRIL,
        recurrence={"frequency": "monthly", "due_day": 20, "due_month_offset": 0},
    )
    extension = draft(store, "gstr3b_extension")
    candidate_id = uuid4()
    with store() as uow:
        detail = uow.documents.clause(clause)
        assert detail is not None
        uow.candidates.add(
            RelationCandidate(
                candidate_id=candidate_id,
                document_id=detail.clause.document_id,
                relation=RelationKind.EXTENDS_DEADLINE,
                target_type=EntityType.FORM,
                target_name="GSTR-3B",
                target_clause_id=clause,
                target_span_start=TEXT.index("FORM"),
                target_span_end=TEXT.index("FORM") + 12,
                evidence_clause_id=clause,
                evidence_quote=QUOTE,
                quote_score=1.0,
                prompt_version="extraction.rule_relations@1",
                confidence=0.9,
                needs_review=False,
                period_label="2026-09",
                new_due_on=date(2026, 10, 27),
            )
        )
    relation_id = flow.relate(
        extension, RelationKind.EXTENDS_DEADLINE, monthly, clause, candidate_id
    )
    flow.published(extension, clause)

    changes = feed(store)
    (moved,) = [c for c in changes if c.entry.kind is RuleChangeKind.DEADLINE_CHANGED]
    (published,) = [c for c in changes if c.entry.kind is RuleChangeKind.PUBLISHED]
    assert moved.entry == ChangeEntry(
        change_id=deadline_change_id(published.entry.change_id, relation_id),
        kind=RuleChangeKind.DEADLINE_CHANGED,
        changed_at=published.entry.changed_at,
        rule_version_id=monthly,
        caused_by=extension,
        period_label="2026-09",
        new_due_on=date(2026, 10, 27),
        evidence_clause_id=clause,
    )
    assert moved.version.rule_key == "gstr3b_monthly"
    (extends,) = published.relations
    assert (extends.relation, extends.to_rule_version_id, extends.new_due_on) == (
        RelationKind.EXTENDS_DEADLINE,
        monthly,
        date(2026, 10, 27),
    )


def test_a_deadline_change_id_is_the_same_on_every_read() -> None:
    decision, relation = UUID(int=1), UUID(int=2)
    assert deadline_change_id(decision, relation) == deadline_change_id(decision, relation)
    assert deadline_change_id(decision, relation) != deadline_change_id(relation, decision)
    expected = hashlib.sha256(f"{decision}:{relation}".encode()).hexdigest()[:32]
    assert deadline_change_id(decision, relation).hex == expected


def test_a_deadline_change_names_the_version_that_made_it() -> None:
    with pytest.raises(InvariantViolationError, match="names the version"):
        ChangeEntry(
            change_id=uuid4(),
            kind=RuleChangeKind.DEADLINE_CHANGED,
            changed_at=START,
            rule_version_id=RuleVersionId.new(),
        )


# ---------------------------------------------------------------- filters and pages


def published_many(store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId) -> list[Any]:
    for number in range(5):
        regulator = "CBIC" if number % 2 == 0 else "GSTN"
        flow.published(draft(store, f"rule_{number}", regulator=regulator), clause)
    return feed(store)


def test_the_feed_is_newest_first_and_pages_by_its_key(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    every = published_many(store, flow, clause)
    assert [c.version.rule_key for c in every] == [f"rule_{n}" for n in range(4, -1, -1)]
    assert [c.entry for c in every] == newest_first([c.entry for c in every])
    first = feed(store, limit=2)
    rest = feed(store, limit=10, after=first[-1].entry.key)
    assert [c.entry for c in first + rest] == [c.entry for c in every]


def test_the_feed_filters_by_time_and_regulator(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    every = published_many(store, flow, clause)
    since = every[1].entry.changed_at
    assert [c.entry for c in feed(store, since=since)] == [c.entry for c in every[:2]]
    gstn = feed(store, regulator="GSTN")
    assert [c.version.rule_key for c in gstn] == ["rule_3", "rule_1"]
    assert feed(store, regulator="FSSAI") == []


def test_a_query_takes_an_aware_since_and_a_positive_limit() -> None:
    with pytest.raises(InvariantViolationError):
        ChangeQuery(limit=0)
    with pytest.raises(InvariantViolationError):
        ChangeQuery(limit=1, since=datetime(2026, 10, 1))
    with pytest.raises(InvariantViolationError):
        ChangeKey(datetime(2026, 10, 1), uuid4())


# ---------------------------------------------------------------- over HTTP


@pytest.fixture
def served(clock: Clock) -> Iterator[tuple[TestClient, MemoryKnowledgeStore]]:
    app = build_app(rulebook_settings(rulebook_publish_enabled=True))
    with TestClient(app) as client:
        memory = app.state.wiring.unit_of_work
        assert isinstance(memory, MemoryKnowledgeStore)
        yield client, memory


def test_the_route_answers_a_page_of_changes(
    served: tuple[TestClient, MemoryKnowledgeStore], clock: Clock
) -> None:
    client, store = served
    flow = Flow(store, clock)
    digest = hashlib.sha256(b"changes route").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/route.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=START,
        ),
        [Clause("en.p1", TEXT)],
    )
    clause = clause_id_for(document_id, "en.p1")
    versions = [draft(store, f"rule_{n}") for n in range(3)]
    for version in versions:
        flow.published(version, clause, synthetic=True)

    first = client.get(CHANGES, params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    item = body["items"][0]
    assert item["kind"] == "published"
    assert item["rule_version_id"] == str(versions[-1])
    assert (item["rule_key"], item["regulator"], item["level"]) == (
        "rule_2",
        "CBIC",
        "registration",
    )
    assert (item["status"], item["seed_status"]) == ("published", "needs_review")
    assert sorted(item["approved_by"]) == sorted([str(REVIEWER), str(SECOND_REVIEWER)])
    assert item["citations"] == [
        {
            "clause_id": str(clause),
            "document_id": str(document_id),
            "clause_ref": "en.p1",
            "quote": QUOTE,
        }
    ]
    assert item["relations"] == {
        "supersedes": [],
        "corrects": [],
        "withdraws": [],
        "extends_deadline": [],
    }
    assert (item["caused_by_rule_version_id"], item["deadline"]) == (None, None)
    assert item["published_at"] is not None
    rest = client.get(CHANGES, params={"limit": 2, "cursor": body["next_cursor"]}).json()
    assert [i["rule_key"] for i in body["items"] + rest["items"]] == ["rule_2", "rule_1", "rule_0"]
    assert rest["next_cursor"] is None

    later = (START + timedelta(days=1)).date().isoformat()
    assert client.get(CHANGES, params={"since": later}).json()["items"] == []
    assert len(client.get(CHANGES, params={"since": "2026-10-01"}).json()["items"]) == 3
    moment = body["items"][1]["changed_at"].replace("Z", "+00:00")
    assert len(client.get(CHANGES, params={"since": moment}).json()["items"]) == 2
    assert client.get(CHANGES, params={"regulator": "GSTN"}).json()["items"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 101},
        {"limit": 0},
        {"since": "yesterday"},
        {"since": "2026-02-30"},
        {"since": "2026-10-01T10:00:00"},
        {"cursor": "not-a-cursor"},
        {"regulator": ""},
    ],
)
def test_the_route_refuses_what_it_cannot_read(
    served: tuple[TestClient, MemoryKnowledgeStore], params: dict[str, str | int]
) -> None:
    client, _ = served
    refused = client.get(CHANGES, params=params)
    assert refused.status_code == 422, (params, refused.text)
    assert refused.headers["content-type"].startswith("application/problem+json")


def test_the_route_is_public_for_members_and_the_regulatory_team(
    served: tuple[TestClient, MemoryKnowledgeStore],
) -> None:
    client, _ = served
    operation = client.app.openapi()["paths"][CHANGES]["get"]  # type: ignore[attr-defined]
    assert "public" in operation["tags"]
    assert operation["x-roles"] == [
        "owner",
        "staff",
        "ca_admin",
        "ca_staff",
        "compliance_lead",
        "analyst",
        "reviewer",
        "admin",
    ]
    assert client.get(CHANGES).json() == {"items": [], "next_cursor": None}
