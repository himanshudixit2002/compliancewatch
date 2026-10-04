"""The read use cases on the memory store: rule versions in force, every version of a rule,
citations, entity resolution, the clauses that mention an entity, relations and clauses."""

import hashlib
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import CanonicalEntityId, ClauseId, DocumentId, RuleVersionId, SourceId
from domain_kernel.knowledge import EntityRef, EntityType, RelationKind, RuleRelation
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus
from rulebook.application.documents import RegisterDocument
from rulebook.application.graph import (
    ListEntityClauses,
    ListRelations,
    ReadClause,
    ReadEntity,
    ResolveEntity,
)
from rulebook.application.rule_versions import (
    ListCitations,
    ListRulesInForce,
    ListRuleVersions,
    ReadRuleVersion,
)
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import (
    ClauseNotStoredError,
    UnknownEntityError,
    UnknownRuleError,
    UnknownRuleVersionError,
)
from rulebook.domain.graph import RelationQuery, ResolutionStatus
from rulebook.domain.relations import RelationCandidate
from rulebook.domain.rule_versions import IN_FORCE_STATUSES, in_force, out_of_force
from rulebook.domain.seed import SeedStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
APRIL = date(2026, 4, 1)
JULY = date(2026, 7, 1)
TEXT = "hereby extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"


def register(
    store: MemoryKnowledgeStore,
    name: str,
    published_at: date | None,
    *texts: str,
    regulator: str = "CBIC",
) -> DocumentId:
    digest = hashlib.sha256(name.encode()).hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator=regulator,
            doc_type=DocumentType.NOTIFICATION,
            url=f"https://example.invalid/{name}.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=NOW,
            external_ref=name,
            published_at=published_at,
        ),
        [Clause(f"en.p{index}", text) for index, text in enumerate(texts, 1)],
    )
    return document_id


@pytest.fixture
def store() -> MemoryKnowledgeStore:
    return MemoryKnowledgeStore()


# ---------------------------------------------------------------- rule versions


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (date(2026, 3, 31), False),
        (APRIL, True),
        (date(2026, 6, 30), True),
        (JULY, False),
    ],
)
def test_the_effective_period_is_half_open(
    store: MemoryKnowledgeStore, as_of: date, expected: bool
) -> None:
    _, version = store.add_rule(
        "gstr3b_monthly",
        status=RuleVersionStatus.PUBLISHED,
        effective_from=APRIL,
        effective_to=JULY,
    )
    found = ListRulesInForce(store).run(as_of)
    assert [record.rule_version_id for record in found] == ([version] if expected else [])
    record, _ = ReadRuleVersion(store).run(version)
    assert in_force(record, as_of) is expected


@pytest.mark.parametrize("status", list(RuleVersionStatus))
def test_only_published_and_superseded_versions_are_in_force(
    store: MemoryKnowledgeStore, status: RuleVersionStatus
) -> None:
    store.add_rule("r", status=status, effective_from=APRIL)
    found = ListRulesInForce(store).run(date(2026, 5, 1))
    assert bool(found) is (status in IN_FORCE_STATUSES)


def test_a_superseded_version_answers_for_dates_before_its_replacement(
    store: MemoryKnowledgeStore,
) -> None:
    _, old = store.add_rule(
        "gstr3b_monthly",
        status=RuleVersionStatus.SUPERSEDED,
        effective_from=APRIL,
        effective_to=JULY,
    )
    new = store.add_version(
        "gstr3b_monthly", status=RuleVersionStatus.PUBLISHED, effective_from=JULY
    )
    assert [r.rule_version_id for r in ListRulesInForce(store).run(date(2026, 6, 1))] == [old]
    (current,) = ListRulesInForce(store).run(JULY)
    assert (current.rule_version_id, current.version) == (new, 2)


def test_versions_in_force_are_filtered_ordered_and_paged(store: MemoryKnowledgeStore) -> None:
    published = RuleVersionStatus.PUBLISHED
    for key in ("gstr3b_monthly", "cmp08_quarterly", "gstr1_monthly"):
        store.add_rule(key, status=published, title=key)
    store.add_rule("state_rule", status=published, regulator="KA-CTD")
    use_case = ListRulesInForce(store)
    as_of = date(2026, 5, 1)
    assert [r.rule_key for r in use_case.run(as_of)] == [
        "cmp08_quarterly",
        "gstr1_monthly",
        "gstr3b_monthly",
        "state_rule",
    ]
    assert [r.rule_key for r in use_case.run(as_of, regulator="KA-CTD")] == ["state_rule"]
    assert [r.rule_key for r in use_case.run(as_of, rule_key="gstr1_monthly")] == ["gstr1_monthly"]
    first = use_case.run(as_of, limit=2)
    assert [r.rule_key for r in first] == ["cmp08_quarterly", "gstr1_monthly"]
    rest = use_case.run(as_of, after=first[-1].rule_key, limit=0)
    assert [r.rule_key for r in rest] == ["gstr3b_monthly"]


def test_a_version_reads_in_any_status_with_its_citations(store: MemoryKnowledgeStore) -> None:
    document = register(store, "n1", date(2026, 3, 28), "first clause text", TEXT)
    _, version = store.add_rule(
        "gstr3b_monthly",
        title="GSTR-3B",
        level=AttributeLevel.REGISTRATION,
        summary="Monthly return",
        specification={"all": []},
        obligation_template={"title": "File GSTR-3B"},
        recurrence={"frequency": "monthly"},
    )
    second = store.add_citation(version, clause_id_for(document, "en.p2"), "extends the due date")
    first = store.add_citation(
        version, clause_id_for(document, "en.p1"), "first clause", verified=False, match_score=None
    )
    record, citations = ReadRuleVersion(store).run(version)
    assert record.status is RuleVersionStatus.DRAFT
    assert record.seed_status is SeedStatus.NEEDS_REVIEW
    assert (record.rule_key, record.regulator, record.level) == (
        "gstr3b_monthly",
        "CBIC",
        AttributeLevel.REGISTRATION,
    )
    assert record.specification == {"all": []}
    assert record.recurrence == {"frequency": "monthly"}
    assert [c.citation_id for c in citations] == [first, second]
    assert citations[0].verified is False
    assert citations[0].verified_at is None
    assert citations[1].clause_ref == "en.p2"
    assert citations[1].document_id == document
    assert citations[1].verified_at is not None
    assert ListCitations(store).run(version) == citations


def test_every_version_of_a_rule_reads_in_any_status(store: MemoryKnowledgeStore) -> None:
    _, first = store.add_rule("gstr3b_monthly", status=RuleVersionStatus.PUBLISHED)
    second = store.add_version("gstr3b_monthly", effective_from=JULY)
    store.add_rule("gstr1_monthly")
    versions = ListRuleVersions(store).run("gstr3b_monthly")
    assert [(v.rule_version_id, v.version, v.status) for v in versions] == [
        (first, 1, RuleVersionStatus.PUBLISHED),
        (second, 2, RuleVersionStatus.DRAFT),
    ]
    assert {v.seed_status for v in versions} == {SeedStatus.NEEDS_REVIEW}
    with pytest.raises(UnknownRuleError, match="no_such_rule"):
        ListRuleVersions(store).run("no_such_rule")


def test_unknown_versions_are_reported(store: MemoryKnowledgeStore) -> None:
    unknown = RuleVersionId(UUID(int=9))
    with pytest.raises(UnknownRuleVersionError):
        ReadRuleVersion(store).run(unknown)
    with pytest.raises(UnknownRuleVersionError):
        ListCitations(store).run(unknown)


# ---------------------------------------------------------------- entities


def test_a_name_resolves_after_normalising(store: MemoryKnowledgeStore) -> None:
    form = store.add_entity(EntityType.FORM, "GSTR-3B", aliases=["GSTR-3B-M"])
    resolve = ResolveEntity(store)
    exact = resolve.run(EntityType.FORM, "form gstr 3b")
    assert (exact.status, exact.normalised) == (ResolutionStatus.RESOLVED, "GSTR-3B")
    assert exact.entity is not None
    assert (exact.entity.entity_id, exact.entity.aliases) == (form, ("GSTR-3B-M",))
    aliased = resolve.run(EntityType.FORM, "GSTR 3B M")
    assert aliased.status is ResolutionStatus.RESOLVED
    assert aliased.entity is not None
    assert aliased.entity.entity_id == form


def test_resolve_reports_why_a_name_does_not_resolve(store: MemoryKnowledgeStore) -> None:
    first = store.add_entity(EntityType.NOTIFICATION, "01/2026-central tax", ["notfn. 1"])
    second = store.add_entity(EntityType.NOTIFICATION, "01/2025-central tax", ["notfn. 1"])
    resolve = ResolveEntity(store)
    ambiguous = resolve.run(EntityType.NOTIFICATION, "Notfn. 1")
    assert ambiguous.status is ResolutionStatus.AMBIGUOUS
    assert ambiguous.entity is None
    assert {c.entity_id for c in ambiguous.candidates} == {first, second}
    missing = resolve.run(EntityType.FORM, "GSTR-9")
    assert (missing.status, missing.candidates) == (ResolutionStatus.NOT_FOUND, ())
    assert resolve.run(EntityType.SECTION, "section 39").status is ResolutionStatus.UNQUALIFIED
    empty = resolve.run(EntityType.TAX_RATE, "nil")
    assert (empty.status, empty.normalised) == (ResolutionStatus.EMPTY, "")


def test_an_entity_reads_with_its_aliases(store: MemoryKnowledgeStore) -> None:
    form = store.add_entity(EntityType.FORM, "GSTR-3B", aliases=["GSTR-3B-M"])
    record = ReadEntity(store).run(form)
    assert (record.entity_type, record.canonical_name, record.aliases) == (
        EntityType.FORM,
        "GSTR-3B",
        ("GSTR-3B-M",),
    )
    with pytest.raises(UnknownEntityError):
        ReadEntity(store).run(CanonicalEntityId(UUID(int=3)))
    with pytest.raises(UnknownEntityError):
        ListEntityClauses(store).run(CanonicalEntityId(UUID(int=3)))


def mention(
    store: MemoryKnowledgeStore,
    document: DocumentId,
    ref: str,
    entity: CanonicalEntityId,
    text: str,
    clause_text: str,
) -> None:
    start = clause_text.index(text)
    with store() as uow:
        uow.mentions.add(
            clause_id_for(document, ref),
            entity,
            text,
            start,
            start + len(text),
            method="grammar",
            extractor="grammar@1",
        )


def test_clauses_mentioning_an_entity_are_newest_first(store: MemoryKnowledgeStore) -> None:
    other = "Every registered person shall furnish a return in FORM GSTR-3B."
    older = register(store, "older", date(2026, 1, 16), other)
    newer = register(store, "newer", date(2026, 3, 28), "Preamble", TEXT)
    undated = register(store, "undated", None, other)
    form = store.add_entity(EntityType.FORM, "GSTR-3B")
    for document, ref, clause_text in (
        (older, "en.p1", other),
        (newer, "en.p2", TEXT),
        (undated, "en.p1", other),
    ):
        mention(store, document, ref, form, "FORM GSTR-3B", clause_text)
    mention(store, older, "en.p1", form, "GSTR-3B", other)

    found = ListEntityClauses(store).run(form)
    assert [(c.detail.document.document_id, c.detail.clause.clause_ref) for c in found] == [
        (newer, "en.p2"),
        (older, "en.p1"),
        (undated, "en.p1"),
    ]
    spans = found[1].mentions
    assert [span.text for span in spans] == ["FORM GSTR-3B", "GSTR-3B"]
    assert spans[1].span_start - spans[0].span_start == len("FORM ")

    dated = ListEntityClauses(store).run(form, as_of=date(2026, 2, 1))
    assert [c.detail.document.document_id for c in dated] == [older]
    assert len(ListEntityClauses(store).run(form, limit=1)) == 1


def test_a_clause_whose_only_rule_is_superseded_is_out_of_force_later(
    store: MemoryKnowledgeStore,
) -> None:
    document = register(store, "notification", date(2026, 3, 28), TEXT)
    form = store.add_entity(EntityType.FORM, "GSTR-3B")
    mention(store, document, "en.p1", form, "FORM GSTR-3B", TEXT)
    _, old = store.add_rule(
        "gstr3b_monthly",
        status=RuleVersionStatus.SUPERSEDED,
        effective_from=APRIL,
        effective_to=JULY,
    )
    store.add_citation(old, clause_id_for(document, "en.p1"), "extends the due date")
    clauses = ListEntityClauses(store)
    assert [c.out_of_force for c in clauses.run(form, as_of=date(2026, 6, 1))] == [False]
    assert [c.out_of_force for c in clauses.run(form, as_of=date(2026, 8, 1))] == [True]
    assert [c.out_of_force for c in clauses.run(form)] == [False]


@pytest.mark.parametrize(
    ("statuses", "as_of", "expected"),
    [
        ((), date(2026, 5, 1), False),
        ((RuleVersionStatus.DRAFT, RuleVersionStatus.APPROVED), date(2026, 5, 1), False),
        ((RuleVersionStatus.PUBLISHED,), date(2026, 5, 1), False),
        ((RuleVersionStatus.PUBLISHED,), date(2026, 3, 1), True),
        ((RuleVersionStatus.PUBLISHED,), None, False),
        ((RuleVersionStatus.WITHDRAWN,), date(2026, 5, 1), True),
        ((RuleVersionStatus.WITHDRAWN, RuleVersionStatus.PUBLISHED), date(2026, 5, 1), False),
        ((RuleVersionStatus.WITHDRAWN, RuleVersionStatus.DRAFT), date(2026, 5, 1), True),
    ],
)
def test_out_of_force_needs_a_published_citation_and_none_in_force(
    store: MemoryKnowledgeStore,
    statuses: tuple[RuleVersionStatus, ...],
    as_of: date | None,
    expected: bool,
) -> None:
    records = []
    for number, status in enumerate(statuses):
        _, version = store.add_rule(f"r{number}", status=status, effective_from=APRIL)
        records.append(ReadRuleVersion(store).run(version)[0])
    assert out_of_force(records, as_of) is expected


# ---------------------------------------------------------------- relations and clauses


def relation(
    store: MemoryKnowledgeStore,
    from_version: RuleVersionId,
    kind: RelationKind,
    target: EntityRef | RuleVersionId,
    evidence: ClauseId,
    candidate_id: UUID | None = None,
) -> UUID:
    relation_id = uuid4()
    with store() as uow:
        uow.relations.add(
            RuleRelation(from_version, kind, target, evidence),
            relation_id=relation_id,
            candidate_id=candidate_id,
        )
    return relation_id


def test_relations_are_found_by_either_end(store: MemoryKnowledgeStore) -> None:
    document = register(store, "n1", date(2026, 3, 28), TEXT)
    evidence = clause_id_for(document, "en.p1")
    _, monthly = store.add_rule("gstr3b_monthly", status=RuleVersionStatus.PUBLISHED)
    _, extension = store.add_rule("gstr3b_extension", status=RuleVersionStatus.PUBLISHED)
    _, draft = store.add_rule("gstr3b_draft")
    form = store.add_entity(EntityType.FORM, "GSTR-3B")
    candidate_id = uuid4()
    with store() as uow:
        uow.candidates.add(
            RelationCandidate(
                candidate_id=candidate_id,
                document_id=document,
                relation=RelationKind.EXTENDS_DEADLINE,
                target_type=EntityType.FORM,
                target_name="GSTR-3B",
                target_clause_id=evidence,
                target_span_start=TEXT.index("FORM"),
                target_span_end=TEXT.index("FORM") + 12,
                evidence_clause_id=evidence,
                evidence_quote="hereby extends the due date",
                quote_score=1.0,
                prompt_version="extraction.rule_relations@1",
                confidence=0.9,
                needs_review=False,
                period_label="2026-03",
                new_due_on=date(2026, 4, 21),
            )
        )
    extends = relation(
        store, extension, RelationKind.EXTENDS_DEADLINE, monthly, evidence, candidate_id
    )
    refers = relation(
        store,
        extension,
        RelationKind.REFERS_TO,
        EntityRef(EntityType.FORM, "GSTR-3B", form),
        evidence,
    )
    drafted = relation(store, draft, RelationKind.SUPERSEDES, monthly, evidence)
    find = ListRelations(store)

    (to_monthly,) = find.run(RelationQuery(to_rule_version_id=monthly))
    assert to_monthly.relation_id == extends
    assert (to_monthly.period_label, to_monthly.new_due_on) == ("2026-03", date(2026, 4, 21))
    assert (to_monthly.evidence_clause_ref, to_monthly.evidence_document_id) == ("en.p1", document)
    assert to_monthly.to_entity_id is None

    everything = find.run(RelationQuery(to_rule_version_id=monthly, published_only=False))
    assert {r.relation_id for r in everything} == {extends, drafted}

    outgoing = find.run(RelationQuery(from_rule_version_id=extension))
    assert [r.relation_id for r in outgoing] == sorted([extends, refers], key=str)
    only_refers = find.run(
        RelationQuery(from_rule_version_id=extension, relation=RelationKind.REFERS_TO)
    )
    assert [r.relation_id for r in only_refers] == [refers]
    (to_form,) = find.run(RelationQuery(to_entity_id=form))
    assert (to_form.to_kind, to_form.to_ref, to_form.to_entity_id) == ("form", "GSTR-3B", form)
    assert to_form.candidate_id is None
    assert len(find.run(RelationQuery(from_rule_version_id=extension, limit=1))) == 1
    assert find.run(RelationQuery(from_rule_version_id=draft)) == []


def test_a_relation_query_names_an_end() -> None:
    with pytest.raises(InvariantViolationError):
        RelationQuery()
    with pytest.raises(InvariantViolationError):
        RelationQuery(to_entity_id=CanonicalEntityId(UUID(int=1)), limit=0)


def test_a_clause_reads_with_its_document(store: MemoryKnowledgeStore) -> None:
    document = register(store, "n1", date(2026, 3, 28), "Preamble", TEXT)
    detail = ReadClause(store).run(clause_id_for(document, "en.p2"))
    assert (detail.clause.clause_ref, detail.clause.ordinal, detail.clause.text) == (
        "en.p2",
        2,
        TEXT,
    )
    assert (detail.document.external_ref, detail.document.published_at) == (
        "n1",
        date(2026, 3, 28),
    )
    with pytest.raises(ClauseNotStoredError):
        ReadClause(store).run(clause_id_for(document, "en.p9"))
