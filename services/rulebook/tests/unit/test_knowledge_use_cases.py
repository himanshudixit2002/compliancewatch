"""Alignment, the entity review queue and relation candidates on the memory store."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvalidRelationError, InvariantViolationError
from domain_kernel.ids import CanonicalEntityId, DocumentId, RuleVersionId, SourceId
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.status import RuleVersionStatus
from rulebook.application.alignment import AlignMentions, SubmittedMention
from rulebook.application.documents import RegisterDocument
from rulebook.application.relations import (
    ApproveRelationCandidate,
    ListRelationCandidates,
    ListRules,
    RejectRelationCandidate,
    RelationSubmission,
    StageRelationCandidates,
    SubmittedCandidate,
)
from rulebook.application.review import DecideMentionGroup, ListMentionGroups
from rulebook.domain.alignment import MatchKind, Resolved, ReviewReason, Unresolved, resolve
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import (
    CandidateClosedError,
    CandidateNotFoundError,
    EntityTypeMismatchError,
    MentionSpanMismatchError,
    NonCanonicalNameError,
    ReviewGroupClosedError,
    ReviewGroupNotFoundError,
    RuleVersionNotEditableError,
    SupersessionCycleError,
    TargetUnresolvedError,
    TargetVersionRequiredError,
    UnknownClauseError,
    UnknownDocumentError,
    UnknownEntityError,
    UnknownRuleVersionError,
)
from rulebook.domain.relations import (
    CandidateIssue,
    CandidateRejectReason,
    CandidateStatus,
    RelationCandidate,
    find_supersedes_cycle,
)
from rulebook.domain.review import EntityRejectReason, MentionDecision, Resolution, ReviewStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore

DIGEST = "51f5dbee1615f0ec47256abddb11061a348e81b883051e89733a06b062bcebed"
DOC = document_id_for(DIGEST)
P2 = "NOTIFICATION No. 01/2026 \u2013 Central Tax"
P3 = (
    "sub -section (6) of section 39 of the Central Goods and Services Tax Act, 2017 hereby "
    "extends the due date for furnishing the return in FORM GSTR-3B for March, 2026"
)
NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
GRAMMAR = "grammar@1"
PROMPT = "extraction.rule_relations@1"


def clock() -> datetime:
    return NOW


@pytest.fixture
def store() -> MemoryKnowledgeStore:
    store = MemoryKnowledgeStore()
    RegisterDocument(store).run(
        StoredDocument(
            document_id=DOC,
            source_id=SourceId(UUID(int=7)),
            sha256=DIGEST,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/n.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=NOW,
        ),
        (Clause("en.p2", P2), Clause("en.p3", P3)),
    )
    return store


def mention(ref: str, kind: EntityType, text: str, name: str) -> SubmittedMention:
    source = P2 if ref == "en.p2" else P3
    start = source.index(text)
    return SubmittedMention(ref, kind, text, start, start + len(text), name)


FORM_MENTION = mention("en.p3", EntityType.FORM, "FORM GSTR-3B", "GSTR-3B")
SECTION_MENTION = mention(
    "en.p3", EntityType.SECTION, "sub -section (6) of section 39", "39(6)@cgst-act"
)
BARE_SECTION = mention("en.p3", EntityType.SECTION, "section 39", "39")
SELF_MENTION = mention(
    "en.p2",
    EntityType.NOTIFICATION,
    "NOTIFICATION No. 01/2026 \u2013 Central Tax",
    "01/2026-central tax",
)


def entity(store: MemoryKnowledgeStore, kind: EntityType, name: str) -> CanonicalEntityId:
    with store() as uow:
        entity_id, _ = uow.entities.create_or_get(kind, name)
    return entity_id


# ---------------------------------------------------------------- alignment rules


class Lookup:
    def __init__(self, names: dict[str, str], aliases: dict[str, list[str]]) -> None:
        self.names = {name: CanonicalEntityId(UUID(value)) for name, value in names.items()}
        self.aliases = {
            alias: [CanonicalEntityId(UUID(value)) for value in values]
            for alias, values in aliases.items()
        }

    def by_name(self, entity_type: EntityType, name: str) -> CanonicalEntityId | None:
        return self.names.get(name)

    def by_alias(self, entity_type: EntityType, alias: str) -> list[CanonicalEntityId]:
        return self.aliases.get(alias, [])


ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"


@pytest.mark.parametrize(
    ("kind", "name", "expected"),
    [
        (EntityType.FORM, "GSTR-3B", Resolved(CanonicalEntityId(UUID(ONE)), MatchKind.EXACT)),
        (EntityType.FORM, "GSTR3", Resolved(CanonicalEntityId(UUID(TWO)), MatchKind.ALIAS)),
        (EntityType.FORM, "GSTR-X", Unresolved(ReviewReason.AMBIGUOUS_ALIAS)),
        (EntityType.FORM, "GSTR-9", Unresolved(ReviewReason.NO_MATCH)),
        (EntityType.FORM, "", Unresolved(ReviewReason.EMPTY_NAME)),
        (EntityType.SECTION, "39(1)", Unresolved(ReviewReason.UNQUALIFIED)),
        (EntityType.RULE, "61(1)", Unresolved(ReviewReason.UNQUALIFIED)),
    ],
)
def test_resolution_order(kind: EntityType, name: str, expected: object) -> None:
    lookup = Lookup({"GSTR-3B": ONE}, {"GSTR3": [TWO, TWO], "GSTR-X": [ONE, TWO]})
    assert resolve(kind, name, lookup) == expected


# ---------------------------------------------------------------- AlignMentions


def test_known_entities_are_indexed_and_the_rest_queued(store: MemoryKnowledgeStore) -> None:
    entity(store, EntityType.FORM, "GSTR-3B")
    report = AlignMentions(store).run(
        DOC, GRAMMAR, [FORM_MENTION, SECTION_MENTION, BARE_SECTION, SELF_MENTION]
    )
    assert (report.aligned, report.queued, report.unchanged) == (1, 3, 0)
    assert store.mention_count() == 1
    groups = ListMentionGroups(store).run()
    assert [(g.entity_type, g.proposed_name, g.open_count) for g in groups] == [
        (EntityType.NOTIFICATION, "01/2026-central tax", 1),
        (EntityType.SECTION, "39", 1),
        (EntityType.SECTION, "39(6)@cgst-act", 1),
    ]
    assert groups[1].examples[0].reason is ReviewReason.UNQUALIFIED
    (run,) = store.runs()
    assert (run.stage, run.outcome, dict(run.counts)) == (
        "mentions",
        "needs_review",
        {"aligned": 1, "queued": 3, "unchanged": 0},
    )


def test_submitting_the_same_mentions_again_changes_nothing(store: MemoryKnowledgeStore) -> None:
    entity(store, EntityType.FORM, "GSTR-3B")
    AlignMentions(store).run(DOC, GRAMMAR, [FORM_MENTION, SECTION_MENTION])
    again = AlignMentions(store).run(DOC, GRAMMAR, [FORM_MENTION, SECTION_MENTION])
    assert (again.aligned, again.queued, again.unchanged) == (0, 0, 2)
    assert len(store.runs()) == 1


def test_an_alias_resolves_a_mention(store: MemoryKnowledgeStore) -> None:
    form = entity(store, EntityType.FORM, "GSTR-3B")
    with store() as uow:
        uow.entities.add_alias(form, "GSTR-3")
    report = AlignMentions(store).run(
        DOC, GRAMMAR, [mention("en.p3", EntityType.FORM, "FORM GSTR-3B", "GSTR-3")]
    )
    assert report.aligned == 1


@pytest.mark.parametrize(
    ("bad", "error"),
    [
        (SubmittedMention("en.p9", EntityType.FORM, "x", 0, 1, "X"), UnknownClauseError),
        (
            SubmittedMention("en.p3", EntityType.FORM, "FORM GSTR-3B", 0, 12, "GSTR-3B"),
            MentionSpanMismatchError,
        ),
        (
            mention("en.p3", EntityType.FORM, "FORM GSTR-3B", "gstr 3b"),
            NonCanonicalNameError,
        ),
    ],
)
def test_a_bad_mention_refuses_the_whole_submission(
    store: MemoryKnowledgeStore, bad: SubmittedMention, error: type[Exception]
) -> None:
    with pytest.raises(error):
        AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION, bad])
    assert ListMentionGroups(store).run() == []


def test_mentions_need_a_stored_document(store: MemoryKnowledgeStore) -> None:
    with pytest.raises(UnknownDocumentError):
        AlignMentions(store).run(DocumentId(UUID(int=1)), GRAMMAR, [FORM_MENTION])


# ---------------------------------------------------------------- review decisions


def stage(store: MemoryKnowledgeStore, *candidates: SubmittedCandidate) -> list[UUID]:
    report = StageRelationCandidates(store).run(
        DOC, RelationSubmission(PROMPT, "scripted/golden", "ok", tuple(candidates))
    )
    return list(report.candidate_ids)


EXTENDS = SubmittedCandidate(
    relation=RelationKind.EXTENDS_DEADLINE,
    target_type=EntityType.FORM,
    target_name="GSTR-3B",
    target_clause_ref="en.p3",
    target_span_start=P3.index("FORM GSTR-3B"),
    target_span_end=P3.index("FORM GSTR-3B") + 12,
    evidence_clause_ref="en.p3",
    evidence_quote="hereby extends the due date for furnishing the return",
    quote_score=1.0,
    confidence=0.9,
    needs_review=False,
    rule_key="gstr3b_monthly",
    period_label="2026-03",
    new_due_on=date(2026, 4, 21),
)
REFERS = SubmittedCandidate(
    relation=RelationKind.REFERS_TO,
    target_type=EntityType.SECTION,
    target_name="39(6)@cgst-act",
    target_clause_ref="en.p3",
    target_span_start=0,
    target_span_end=30,
    evidence_clause_ref="en.p3",
    evidence_quote="sub -section (6) of section 39",
    quote_score=1.0,
    confidence=0.95,
    needs_review=False,
)


def test_creating_the_entity_resolves_the_group_and_its_candidates(
    store: MemoryKnowledgeStore,
) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION])
    (candidate_id,) = stage(store, REFERS)
    decided = DecideMentionGroup(store, clock).run(
        EntityType.SECTION,
        "39(6)@cgst-act",
        MentionDecision.CREATE_ENTITY,
        decided_by="analyst@example.invalid",
    )
    assert (decided.status, decided.resolution, decided.items_closed) == (
        ReviewStatus.RESOLVED,
        Resolution.CREATED,
        1,
    )
    assert decided.relation_targets_updated == 1
    assert store.mention_count() == 1
    assert ListMentionGroups(store).run() == []
    (candidate,) = ListRelationCandidates(store).run()
    assert candidate.candidate_id == candidate_id
    assert candidate.target_entity_id == decided.entity_id
    with pytest.raises(ReviewGroupClosedError):
        DecideMentionGroup(store, clock).run(
            EntityType.SECTION, "39(6)@cgst-act", MentionDecision.CREATE_ENTITY, decided_by="a"
        )


def test_creating_an_entity_that_appeared_meanwhile_matches_it(
    store: MemoryKnowledgeStore,
) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION])
    existing = entity(store, EntityType.SECTION, "39(6)@cgst-act")
    decided = DecideMentionGroup(store, clock).run(
        EntityType.SECTION, "39(6)@cgst-act", MentionDecision.CREATE_ENTITY, decided_by="a"
    )
    assert (decided.resolution, decided.entity_id) == (Resolution.MATCHED, existing)


def test_an_unqualified_name_cannot_become_an_entity_but_can_be_linked(
    store: MemoryKnowledgeStore,
) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [BARE_SECTION])
    with pytest.raises(NonCanonicalNameError):
        DecideMentionGroup(store, clock).run(
            EntityType.SECTION, "39", MentionDecision.CREATE_ENTITY, decided_by="a"
        )
    target = entity(store, EntityType.SECTION, "39@cgst-act")
    decided = DecideMentionGroup(store, clock).run(
        EntityType.SECTION, "39", MentionDecision.ADD_ALIAS, decided_by="a", entity_id=target
    )
    assert decided.resolution is Resolution.MATCHED
    names = store.entity_names()
    assert names[target] == (EntityType.SECTION, "39@cgst-act", ())


def test_adding_an_alias_records_it(store: MemoryKnowledgeStore) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [SELF_MENTION])
    target = entity(store, EntityType.NOTIFICATION, "01/2026-ct")
    decided = DecideMentionGroup(store, clock).run(
        EntityType.NOTIFICATION,
        "01/2026-central tax",
        MentionDecision.ADD_ALIAS,
        decided_by="a",
        entity_id=target,
    )
    assert decided.resolution is Resolution.ALIASED
    assert store.entity_names()[target][2] == ("01/2026-central tax",)
    assert AlignMentions(store).run(DOC, GRAMMAR, [SELF_MENTION]).unchanged == 1


@pytest.mark.parametrize(
    ("entity_id", "error"),
    [(CanonicalEntityId(UUID(int=9)), UnknownEntityError), (None, EntityTypeMismatchError)],
)
def test_an_alias_needs_an_entity_of_the_same_type(
    store: MemoryKnowledgeStore, entity_id: CanonicalEntityId | None, error: type[Exception]
) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION])
    target = entity_id or entity(store, EntityType.FORM, "GSTR-1")
    with pytest.raises(error):
        DecideMentionGroup(store, clock).run(
            EntityType.SECTION,
            "39(6)@cgst-act",
            MentionDecision.ADD_ALIAS,
            decided_by="a",
            entity_id=target,
        )


def test_a_rejection_closes_the_group(store: MemoryKnowledgeStore) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [BARE_SECTION])
    decided = DecideMentionGroup(store, clock).run(
        EntityType.SECTION,
        "39",
        MentionDecision.REJECT,
        decided_by="a",
        reject_reason=EntityRejectReason.TEXT_ARTIFACT,
    )
    assert (decided.status, decided.items_closed) == (ReviewStatus.REJECTED, 1)
    assert store.mention_count() == 0


def test_decisions_need_their_arguments(store: MemoryKnowledgeStore) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [BARE_SECTION])
    decide = DecideMentionGroup(store, clock)
    with pytest.raises(InvariantViolationError, match="needs a reason"):
        decide.run(EntityType.SECTION, "39", MentionDecision.REJECT, decided_by="a")
    with pytest.raises(InvariantViolationError, match="needs the entity"):
        decide.run(EntityType.SECTION, "39", MentionDecision.ADD_ALIAS, decided_by="a")
    with pytest.raises(ReviewGroupNotFoundError):
        decide.run(EntityType.FORM, "GSTR-9", MentionDecision.CREATE_ENTITY, decided_by="a")


def test_groups_page_by_type_and_name(store: MemoryKnowledgeStore) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION, BARE_SECTION, SELF_MENTION])
    first = ListMentionGroups(store).run(limit=1)
    assert [g.proposed_name for g in first] == ["01/2026-central tax"]
    rest = ListMentionGroups(store).run(after=("notification", "01/2026-central tax"))
    assert [g.proposed_name for g in rest] == ["39", "39(6)@cgst-act"]
    only = ListMentionGroups(store).run(entity_type=EntityType.NOTIFICATION)
    assert len(only) == 1


# ---------------------------------------------------------------- staging and approval


def test_staging_aligns_targets_and_checks_rule_hints(store: MemoryKnowledgeStore) -> None:
    store.add_rule("gstr3b_monthly", title="GSTR-3B monthly return")
    form = entity(store, EntityType.FORM, "GSTR-3B")
    ids = stage(store, EXTENDS, REFERS)
    found = {c.candidate_id: c for c in ListRelationCandidates(store).run()}
    extends = found[ids[0]]
    assert extends.target_entity_id == form
    assert extends.target_rule_key == "gstr3b_monthly"
    assert extends.target_rule_id is not None
    assert (extends.period_label, extends.new_due_on) == ("2026-03", date(2026, 4, 21))
    assert extends.needs_review is False
    refers = found[ids[1]]
    assert refers.target_entity_id is None
    assert refers.issues == (CandidateIssue("target_unaligned", "no_match"),)
    assert refers.needs_review is True
    runs = [run for run in store.runs() if run.stage == "relations"]
    assert len(runs) == 1


def test_an_unknown_rule_hint_is_dropped_with_an_issue(store: MemoryKnowledgeStore) -> None:
    stage(store, replace(EXTENDS, rule_key="no_such_rule"))
    (candidate,) = ListRelationCandidates(store).run()
    assert (candidate.target_rule_key, candidate.target_rule_id) == (None, None)
    assert CandidateIssue("rule_key_unknown", "no_such_rule") in candidate.issues
    assert candidate.needs_review is True


def test_the_first_proposal_wins_over_a_later_one_with_another_hint(
    store: MemoryKnowledgeStore,
) -> None:
    store.add_rule("gstr3b_monthly")
    stage(store, EXTENDS)
    report = StageRelationCandidates(store).run(
        DOC, RelationSubmission(PROMPT, "m", "ok", (replace(EXTENDS, rule_key="other"),))
    )
    assert (report.created, report.unchanged) == (0, 1)
    (candidate,) = ListRelationCandidates(store).run()
    assert candidate.target_rule_key == "gstr3b_monthly"


def test_staging_is_idempotent(store: MemoryKnowledgeStore) -> None:
    stage(store, REFERS)
    report = StageRelationCandidates(store).run(
        DOC, RelationSubmission(PROMPT, "m", "ok", (REFERS,))
    )
    assert (report.created, report.unchanged) == (0, 1)


def test_staging_needs_the_documents_clauses(store: MemoryKnowledgeStore) -> None:
    bad = replace(REFERS, evidence_clause_ref="en.p7")
    with pytest.raises(UnknownClauseError):
        stage(store, bad)
    with pytest.raises(UnknownDocumentError):
        StageRelationCandidates(store).run(
            DocumentId(UUID(int=1)), RelationSubmission(PROMPT, "m", "ok", (REFERS,))
        )


def test_approving_a_deadline_extension_needs_the_affected_version(
    store: MemoryKnowledgeStore,
) -> None:
    store.add_rule("gstr3b_monthly")
    _, new_version = store.add_rule("gstr3b_extension_2026_03", status=RuleVersionStatus.DRAFT)
    _, affected = store.add_rule("gstr3b_monthly_v1", status=RuleVersionStatus.PUBLISHED)
    (candidate_id,) = stage(store, EXTENDS)
    approve = ApproveRelationCandidate(store, clock)
    with pytest.raises(TargetVersionRequiredError):
        approve.run(candidate_id, new_version, None, decided_by="a")
    approval = approve.run(candidate_id, new_version, affected, decided_by="a", note="checked")
    ((relation, linked),) = store.rule_relations()
    assert linked == candidate_id
    assert relation.relation is RelationKind.EXTENDS_DEADLINE
    assert relation.target == affected
    assert relation.from_rule_version_id == new_version
    assert relation.evidence_clause_id == clause_id_for(DOC, "en.p3")
    (candidate,) = ListRelationCandidates(store).run(status=CandidateStatus.APPROVED)
    assert (candidate.decided_by, candidate.note) == ("a", "checked")
    assert approval.rule_relation_id
    with pytest.raises(CandidateClosedError):
        approve.run(candidate_id, new_version, affected, decided_by="a")


def test_an_entity_target_must_be_aligned_first(store: MemoryKnowledgeStore) -> None:
    _, version = store.add_rule("gstr3b_extension")
    (candidate_id,) = stage(store, REFERS)
    with pytest.raises(TargetUnresolvedError):
        ApproveRelationCandidate(store, clock).run(candidate_id, version, None, decided_by="a")
    AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION])
    DecideMentionGroup(store, clock).run(
        EntityType.SECTION, "39(6)@cgst-act", MentionDecision.CREATE_ENTITY, decided_by="a"
    )
    ApproveRelationCandidate(store, clock).run(candidate_id, version, None, decided_by="a")
    ((relation, _),) = store.rule_relations()
    assert relation.to_kind == "section"
    assert relation.to_ref == "39(6)@cgst-act"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (RuleVersionStatus.PUBLISHED, RuleVersionNotEditableError),
        (RuleVersionStatus.WITHDRAWN, RuleVersionNotEditableError),
    ],
)
def test_the_from_version_must_be_before_publication(
    store: MemoryKnowledgeStore, status: RuleVersionStatus, error: type[Exception]
) -> None:
    _, version = store.add_rule("r", status=status)
    (candidate_id,) = stage(store, REFERS)
    with pytest.raises(error):
        ApproveRelationCandidate(store, clock).run(candidate_id, version, None, decided_by="a")


def test_unknown_versions_and_candidates(store: MemoryKnowledgeStore) -> None:
    _, version = store.add_rule("r")
    (candidate_id,) = stage(store, EXTENDS)
    approve = ApproveRelationCandidate(store, clock)
    with pytest.raises(UnknownRuleVersionError):
        approve.run(candidate_id, RuleVersionId.new(), version, decided_by="a")
    with pytest.raises(UnknownRuleVersionError):
        approve.run(candidate_id, version, RuleVersionId.new(), decided_by="a")
    with pytest.raises(CandidateNotFoundError):
        approve.run(UUID(int=5), version, None, decided_by="a")
    with pytest.raises(CandidateNotFoundError):
        RejectRelationCandidate(store, clock).run(
            UUID(int=5), CandidateRejectReason.DUPLICATE, decided_by="a"
        )


def test_a_version_cannot_relate_to_itself(store: MemoryKnowledgeStore) -> None:
    _, version = store.add_rule("r")
    (candidate_id,) = stage(store, EXTENDS)
    with pytest.raises(InvalidRelationError):
        ApproveRelationCandidate(store, clock).run(candidate_id, version, version, decided_by="a")


def test_a_supersession_cycle_is_refused(store: MemoryKnowledgeStore) -> None:
    _, first = store.add_rule("a")
    _, second = store.add_rule("b")
    supersedes = replace(
        REFERS,
        relation=RelationKind.SUPERSEDES,
        target_type=EntityType.NOTIFICATION,
        target_name="01/2026-central tax",
    )
    other = replace(supersedes, evidence_clause_ref="en.p2")
    one, two = stage(store, supersedes, other)
    ApproveRelationCandidate(store, clock).run(one, first, second, decided_by="a")
    with pytest.raises(SupersessionCycleError):
        ApproveRelationCandidate(store, clock).run(two, second, first, decided_by="a")


def test_a_rejection_keeps_the_reason(store: MemoryKnowledgeStore) -> None:
    (candidate_id,) = stage(store, REFERS)
    rejected = RejectRelationCandidate(store, clock).run(
        candidate_id, CandidateRejectReason.WRONG_TARGET, decided_by="a", note="cites only"
    )
    assert (rejected.status, rejected.reject_reason, rejected.decided_at) == (
        CandidateStatus.REJECTED,
        CandidateRejectReason.WRONG_TARGET,
        NOW,
    )
    with pytest.raises(CandidateClosedError):
        RejectRelationCandidate(store, clock).run(
            candidate_id, CandidateRejectReason.WRONG_TARGET, decided_by="a"
        )
    assert ListRelationCandidates(store).run() == []
    assert len(ListRelationCandidates(store).run(status=None)) == 1


def test_candidates_page_by_id_and_filter_by_document(store: MemoryKnowledgeStore) -> None:
    ids = sorted(stage(store, REFERS, EXTENDS), key=str)
    first = ListRelationCandidates(store).run(limit=1)
    assert [c.candidate_id for c in first] == ids[:1]
    rest = ListRelationCandidates(store).run(after=ids[0])
    assert [c.candidate_id for c in rest] == ids[1:]
    assert ListRelationCandidates(store).run(document_id=DocumentId(UUID(int=1))) == []


def test_rules_are_listed_by_key(store: MemoryKnowledgeStore) -> None:
    store.add_rule("gstr1_monthly", title="GSTR-1")
    store.add_rule("cmp08_quarterly", title="CMP-08")
    assert [(r.rule_key, r.title) for r in ListRules(store).run()] == [
        ("cmp08_quarterly", "CMP-08"),
        ("gstr1_monthly", "GSTR-1"),
    ]


# ---------------------------------------------------------------- domain rules


def test_candidates_hold_their_invariants() -> None:
    base = {
        "candidate_id": UUID(int=1),
        "document_id": DOC,
        "relation": RelationKind.REFERS_TO,
        "target_type": EntityType.FORM,
        "target_name": "GSTR-3B",
        "target_clause_id": clause_id_for(DOC, "en.p3"),
        "target_span_start": 0,
        "target_span_end": 4,
        "evidence_clause_id": clause_id_for(DOC, "en.p3"),
        "evidence_quote": "a quote of the clause",
        "quote_score": 1.0,
        "prompt_version": PROMPT,
        "confidence": 0.9,
        "needs_review": False,
    }
    with pytest.raises(InvariantViolationError, match="extends_deadline"):
        RelationCandidate(**{**base, "period_label": "2026-03"})  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="8 to 400"):
        RelationCandidate(**{**base, "evidence_quote": "short"})  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="confidence"):
        RelationCandidate(**{**base, "confidence": 1.5})  # type: ignore[arg-type]
    candidate = RelationCandidate(**base)  # type: ignore[arg-type]
    rejected = candidate.reject(CandidateRejectReason.DUPLICATE, decided_by="a", at=NOW)
    with pytest.raises(InvariantViolationError, match="is rejected"):
        rejected.approve(decided_by="a", at=NOW)


def test_supersession_cycles_are_found_along_any_path() -> None:
    a, b, c = RuleVersionId.new(), RuleVersionId.new(), RuleVersionId.new()
    edges = {a: frozenset({b}), b: frozenset({c})}
    assert find_supersedes_cycle(edges, c, a) == (a, b, c)
    assert find_supersedes_cycle(edges, a, c) is None
    assert find_supersedes_cycle({}, a, b) is None
