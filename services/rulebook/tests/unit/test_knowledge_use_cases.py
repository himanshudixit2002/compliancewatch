"""Alignment, the entity review queue and relation candidates on the memory store."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from domain_kernel.audit import AuditActor
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvalidRelationError, InvariantViolationError
from domain_kernel.ids import CanonicalEntityId, DocumentId, RuleVersionId, SourceId, UserId
from domain_kernel.knowledge import EntityRef, EntityType, RelationKind, RuleRelation
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
    reopen_relations,
)
from rulebook.application.review import DecideMentionGroup, ListGroupItems, ListMentionGroups
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
from rulebook.domain.rule_versions import RuleVersionRecord
from rulebook.infrastructure.memory import MemoryKnowledgeStore, MemoryRuleVersionRepository

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
    (item,) = ListGroupItems(store).run(EntityType.SECTION, "39")
    with pytest.raises(NonCanonicalNameError):
        DecideMentionGroup(store, clock).run(
            EntityType.SECTION,
            "39",
            MentionDecision.CREATE_ENTITY,
            decided_by="a",
            review_ids=[item.review_id],
        )
    target = entity(store, EntityType.SECTION, "39@cgst-act")
    decided = DecideMentionGroup(store, clock).run(
        EntityType.SECTION,
        "39",
        MentionDecision.ADD_ALIAS,
        decided_by="a",
        entity_id=target,
        review_ids=[item.review_id],
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
    (item,) = ListGroupItems(store).run(EntityType.SECTION, "39")
    decided = DecideMentionGroup(store, clock).run(
        EntityType.SECTION,
        "39",
        MentionDecision.REJECT,
        decided_by="a",
        reject_reason=EntityRejectReason.TEXT_ARTIFACT,
        review_ids=[item.review_id],
    )
    assert (decided.status, decided.items_closed) == (ReviewStatus.REJECTED, 1)
    assert store.mention_count() == 0


def test_decisions_need_their_arguments(store: MemoryKnowledgeStore) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [BARE_SECTION, SECTION_MENTION])
    decide = DecideMentionGroup(store, clock)
    with pytest.raises(InvariantViolationError, match="decide its mentions by review_ids"):
        decide.run(EntityType.SECTION, "39", MentionDecision.REJECT, decided_by="a")
    with pytest.raises(InvariantViolationError, match="needs a reason"):
        decide.run(EntityType.SECTION, "39(6)@cgst-act", MentionDecision.REJECT, decided_by="a")
    with pytest.raises(InvariantViolationError, match="needs the entity"):
        decide.run(EntityType.SECTION, "39(6)@cgst-act", MentionDecision.ADD_ALIAS, decided_by="a")
    with pytest.raises(ReviewGroupNotFoundError):
        decide.run(EntityType.FORM, "GSTR-9", MentionDecision.CREATE_ENTITY, decided_by="a")
    with pytest.raises(ReviewGroupNotFoundError, match="not in"):
        decide.run(
            EntityType.SECTION,
            "39",
            MentionDecision.REJECT,
            decided_by="a",
            reject_reason=EntityRejectReason.TEXT_ARTIFACT,
            review_ids=[UUID(int=4)],
        )


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
    "status",
    [
        RuleVersionStatus.IN_REVIEW,
        RuleVersionStatus.APPROVED,
        RuleVersionStatus.PUBLISHED,
        RuleVersionStatus.WITHDRAWN,
    ],
)
def test_the_from_version_must_be_a_draft(
    store: MemoryKnowledgeStore, status: RuleVersionStatus
) -> None:
    _, version = store.add_rule("r", status=status)
    (candidate_id,) = stage(store, REFERS)
    with pytest.raises(RuleVersionNotEditableError, match=status.value):
        ApproveRelationCandidate(store, clock).run(candidate_id, version, None, decided_by="a")
    assert store.rule_relations() == []


def test_approval_locks_the_version_before_reading_its_status(
    store: MemoryKnowledgeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, version = store.add_rule("r")
    (candidate_id,) = stage(store, REFERS)
    AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION])
    DecideMentionGroup(store, clock).run(
        EntityType.SECTION, "39(6)@cgst-act", MentionDecision.CREATE_ENTITY, decided_by="a"
    )
    locked: list[RuleVersionId] = []
    lock = MemoryRuleVersionRepository.lock

    def recording(
        repository: MemoryRuleVersionRepository, rule_version_id: RuleVersionId
    ) -> RuleVersionRecord | None:
        locked.append(rule_version_id)
        return lock(repository, rule_version_id)

    monkeypatch.setattr(MemoryRuleVersionRepository, "lock", recording)
    ApproveRelationCandidate(store, clock).run(candidate_id, version, None, decided_by="a")
    assert locked == [version]


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


def test_reopening_a_drafts_relations_deletes_them_and_opens_their_candidates(
    store: MemoryKnowledgeStore,
) -> None:
    store.add_rule("gstr3b_monthly")
    _, draft = store.add_rule("gstr3b_extension_2026_03")
    _, other = store.add_rule("gstr3b_extension_other")
    _, affected = store.add_rule("gstr3b_monthly_v1", status=RuleVersionStatus.PUBLISHED)
    supersedes = replace(
        REFERS,
        relation=RelationKind.SUPERSEDES,
        target_type=EntityType.NOTIFICATION,
        target_name="01/2026-central tax",
    )
    extends, superseding = stage(store, EXTENDS, supersedes)
    approve = ApproveRelationCandidate(store, clock)
    approve.run(extends, draft, affected, decided_by="a", note="checked")
    approve.run(superseding, other, affected, decided_by="a")
    with store() as uow:
        uow.relations.add(
            RuleRelation(
                from_rule_version_id=draft,
                relation=RelationKind.REFERS_TO,
                target=affected,
                evidence_clause_id=clause_id_for(DOC, "en.p2"),
            ),
            relation_id=UUID(int=9),
            candidate_id=None,
        )
        reopened = reopen_relations(uow, draft, note="the draft's candidate was rejected")
    assert reopened == (extends,)
    kept = {(relation.from_rule_version_id, linked) for relation, linked in store.rule_relations()}
    assert kept == {(draft, None), (other, superseding)}, (
        "a relation with no candidate, and another version's, stay"
    )
    (candidate,) = ListRelationCandidates(store).run(status=CandidateStatus.OPEN)
    assert (candidate.candidate_id, candidate.decided_by, candidate.decided_at, candidate.note) == (
        extends,
        "",
        None,
        "the draft's candidate was rejected",
    )
    approve.run(extends, other, affected, decided_by="a", note="onto another draft")
    assert (other, extends) in {
        (relation.from_rule_version_id, linked) for relation, linked in store.rule_relations()
    }


def test_the_relations_of_a_version_past_draft_are_never_reopened(
    store: MemoryKnowledgeStore,
) -> None:
    store.add_rule("gstr3b_monthly")
    _, version = store.add_rule("gstr3b_extension_2026_03")
    _, affected = store.add_rule("gstr3b_monthly_v1", status=RuleVersionStatus.PUBLISHED)
    (extends,) = stage(store, EXTENDS)
    ApproveRelationCandidate(store, clock).run(extends, version, affected, decided_by="a")
    with store() as uow:
        record = uow.rule_versions.get(version)
        assert record is not None
        uow.rule_versions.save_lifecycle(replace(record, status=RuleVersionStatus.IN_REVIEW))
    with pytest.raises(RuleVersionNotEditableError, match="in_review"), store() as uow:
        reopen_relations(uow, version, note="example")
    with pytest.raises(UnknownRuleVersionError), store() as uow:
        reopen_relations(uow, RuleVersionId.new(), note="example")
    assert [linked for _, linked in store.rule_relations()] == [extends]
    assert ListRelationCandidates(store).run(status=CandidateStatus.OPEN) == []


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


CANDIDATE_FIELDS: dict[str, object] = {
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


def test_candidates_hold_their_invariants() -> None:
    base = CANDIDATE_FIELDS
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


def test_only_an_approved_candidate_is_reopened_and_it_says_why() -> None:
    candidate = RelationCandidate(**CANDIDATE_FIELDS)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="only an approved one"):
        candidate.reopened(note="the draft closed")
    rejected = candidate.reject(CandidateRejectReason.DUPLICATE, decided_by="a", at=NOW)
    with pytest.raises(InvariantViolationError, match="only an approved one"):
        rejected.reopened(note="the draft closed")
    approved = candidate.approve(decided_by="a", at=NOW, note="checked")
    with pytest.raises(InvariantViolationError, match="says why"):
        approved.reopened(note="  ")
    reopened = approved.reopened(note="the draft closed")
    assert (
        reopened.status,
        reopened.decided_by,
        reopened.decided_at,
        reopened.reject_reason,
        reopened.note,
    ) == (CandidateStatus.OPEN, "", None, None, "the draft closed")
    assert reopened.approve(decided_by="b", at=NOW).status is CandidateStatus.APPROVED


def test_supersession_cycles_are_found_along_any_path() -> None:
    a, b, c = RuleVersionId.new(), RuleVersionId.new(), RuleVersionId.new()
    edges = {a: frozenset({b}), b: frozenset({c})}
    assert find_supersedes_cycle(edges, c, a) == (a, b, c)
    assert find_supersedes_cycle(edges, a, c) is None
    assert find_supersedes_cycle({}, a, b) is None


# ---------------------------------------------------------------- review follow-ups

OTHER_DIGEST = "0" * 63 + "1"
OTHER = document_id_for(OTHER_DIGEST)


def register_other(store: MemoryKnowledgeStore) -> None:
    RegisterDocument(store).run(
        StoredDocument(
            document_id=OTHER,
            source_id=SourceId(UUID(int=8)),
            sha256=OTHER_DIGEST,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/other.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=NOW,
        ),
        (Clause("en.p3", P3),),
    )


BARE_TARGET = replace(
    REFERS,
    target_name="39",
    target_span_start=P3.index("section 39"),
    target_span_end=P3.index("section 39") + 10,
)


def test_an_unqualified_name_is_decided_one_document_at_a_time(
    store: MemoryKnowledgeStore,
) -> None:
    register_other(store)
    AlignMentions(store).run(DOC, GRAMMAR, [BARE_SECTION])
    AlignMentions(store).run(OTHER, GRAMMAR, [BARE_SECTION])
    (ours,) = stage(store, BARE_TARGET)
    StageRelationCandidates(store).run(OTHER, RelationSubmission(PROMPT, "m", "ok", (BARE_TARGET,)))
    items = ListGroupItems(store).run(EntityType.SECTION, "39")
    assert len(items) == 2
    mine = next(item for item in items if item.document_id == DOC)
    target = entity(store, EntityType.SECTION, "39@cgst-act")
    decided = DecideMentionGroup(store, clock).run(
        EntityType.SECTION,
        "39",
        MentionDecision.ADD_ALIAS,
        decided_by="a",
        entity_id=target,
        review_ids=[mine.review_id],
    )
    assert (decided.items_closed, decided.relation_targets_updated) == (1, 1)
    left = ListGroupItems(store).run(EntityType.SECTION, "39")
    assert [item.document_id for item in left] == [OTHER]
    aligned = {c.document_id: c.target_entity_id for c in ListRelationCandidates(store).run()}
    assert aligned == {DOC: target, OTHER: None}
    assert store.entity_names()[target][2] == ()

    _, version = store.add_rule("r")
    ApproveRelationCandidate(store, clock).run(ours, version, None, decided_by="a")
    ((relation, _),) = store.rule_relations()
    assert relation.to_ref == "39@cgst-act"


def test_a_candidate_staged_after_its_mention_was_decided_is_aligned(
    store: MemoryKnowledgeStore,
) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [BARE_SECTION])
    (item,) = ListGroupItems(store).run(EntityType.SECTION, "39")
    target = entity(store, EntityType.SECTION, "39@cgst-act")
    DecideMentionGroup(store, clock).run(
        EntityType.SECTION,
        "39",
        MentionDecision.ADD_ALIAS,
        decided_by="a",
        entity_id=target,
        review_ids=[item.review_id],
    )
    stage(store, BARE_TARGET)
    (candidate,) = ListRelationCandidates(store).run()
    assert candidate.target_entity_id == target
    assert candidate.issues == ()


def test_approval_aligns_a_target_resolved_after_staging(store: MemoryKnowledgeStore) -> None:
    (candidate_id,) = stage(store, REFERS)
    target = entity(store, EntityType.SECTION, "39(6)@cgst-act")
    _, version = store.add_rule("r")
    ApproveRelationCandidate(store, clock).run(candidate_id, version, None, decided_by="a")
    ((relation, _),) = store.rule_relations()
    assert relation.target == EntityRef(EntityType.SECTION, "39(6)@cgst-act", target)


def test_an_aliased_target_is_recorded_under_its_canonical_name(
    store: MemoryKnowledgeStore,
) -> None:
    form = entity(store, EntityType.FORM, "GSTR-3B")
    with store() as uow:
        uow.entities.add_alias(form, "GSTR-3")
    aliased = replace(REFERS, target_type=EntityType.FORM, target_name="GSTR-3")
    (candidate_id,) = stage(store, aliased)
    _, version = store.add_rule("r")
    ApproveRelationCandidate(store, clock).run(candidate_id, version, None, decided_by="a")
    ((relation, _),) = store.rule_relations()
    assert (relation.to_kind, relation.to_ref) == ("form", "GSTR-3B")


# ---------------------------------------------------------------- the audit log

ANALYST_ID = UserId(UUID(int=81))


def test_a_group_decision_writes_one_platform_entry(store: MemoryKnowledgeStore) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION])
    stage(store, REFERS)
    decided = DecideMentionGroup(store, clock).run(
        EntityType.SECTION,
        "39(6)@cgst-act",
        MentionDecision.CREATE_ENTITY,
        decided_by=str(ANALYST_ID),
        note="Example: the statute is known",
    )
    (logged,) = store.audit_entries()
    assert (logged.action, logged.subject_type, logged.subject_id) == (
        "entity_review.decided",
        "entity_review",
        "section:39(6)@cgst-act",
    )
    assert (logged.tenant_id, logged.actor, logged.occurred_at) == (
        None,
        AuditActor.user(ANALYST_ID),
        NOW,
    )
    assert logged.reason == "Example: the statute is known"
    assert logged.before == {"status": "open"}
    assert logged.after == {
        "decision": "create_entity",
        "status": "resolved",
        "resolution": "created",
        "entity_id": str(decided.entity_id),
        "items_closed": 1,
        "relation_targets_updated": 1,
    }


def test_a_group_rejection_by_mention_names_its_items(store: MemoryKnowledgeStore) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [BARE_SECTION])
    (item,) = ListGroupItems(store).run(EntityType.SECTION, "39")
    DecideMentionGroup(store, clock).run(
        EntityType.SECTION,
        "39",
        MentionDecision.REJECT,
        decided_by="analyst@example.invalid",
        reject_reason=EntityRejectReason.NOT_AN_ENTITY,
        review_ids=[item.review_id],
    )
    (logged,) = store.audit_entries("entity_review.decided")
    assert logged.actor == AuditActor.system("rulebook"), "a name sent without a token"
    assert logged.after is not None
    assert (logged.after["status"], logged.after["entity_id"], logged.after["reject_reason"]) == (
        "rejected",
        None,
        "not_an_entity",
    )
    assert logged.after["review_ids"] == (str(item.review_id),)


def test_a_refused_group_decision_writes_nothing(store: MemoryKnowledgeStore) -> None:
    AlignMentions(store).run(DOC, GRAMMAR, [SECTION_MENTION])
    with pytest.raises(InvariantViolationError):
        DecideMentionGroup(store, clock).run(
            EntityType.SECTION, "39(6)@cgst-act", MentionDecision.REJECT, decided_by="a"
        )
    with pytest.raises(UnknownEntityError):
        DecideMentionGroup(store, clock).run(
            EntityType.SECTION,
            "39(6)@cgst-act",
            MentionDecision.ADD_ALIAS,
            decided_by="a",
            entity_id=CanonicalEntityId(UUID(int=82)),
        )
    assert store.audit_entries() == []


def test_approving_and_rejecting_candidates_write_their_entries(
    store: MemoryKnowledgeStore,
) -> None:
    store.add_rule("gstr3b_monthly")
    _, new_version = store.add_rule("gstr3b_extension_2026_03", status=RuleVersionStatus.DRAFT)
    _, affected = store.add_rule("gstr3b_monthly_v1", status=RuleVersionStatus.PUBLISHED)
    extends, refers = stage(store, EXTENDS, REFERS)
    approve = ApproveRelationCandidate(store, clock)
    with pytest.raises(TargetVersionRequiredError):
        approve.run(extends, new_version, None, decided_by=str(ANALYST_ID))
    assert store.audit_entries() == [], "a refused approval writes nothing"
    approval = approve.run(
        extends, new_version, affected, decided_by=str(ANALYST_ID), note="Example: checked"
    )
    RejectRelationCandidate(store, clock).run(
        refers, CandidateRejectReason.WRONG_TARGET, decided_by=str(ANALYST_ID), note="cites only"
    )
    approved, rejected = store.audit_entries()
    assert (approved.action, approved.subject_type, approved.subject_id) == (
        "relation_candidate.approved",
        "relation_candidate",
        str(extends),
    )
    assert (approved.tenant_id, approved.actor, approved.reason) == (
        None,
        AuditActor.user(ANALYST_ID),
        "Example: checked",
    )
    assert (approved.before, approved.after) == (
        {"status": "open"},
        {
            "status": "approved",
            "from_rule_version_id": str(new_version),
            "target_rule_version_id": str(affected),
            "rule_relation_id": str(approval.rule_relation_id),
        },
    )
    assert (rejected.action, rejected.subject_id, rejected.reason) == (
        "relation_candidate.rejected",
        str(refers),
        "cites only",
    )
    assert (rejected.before, rejected.after) == (
        {"status": "open"},
        {"status": "rejected", "reject_reason": "wrong_target"},
    )
    with pytest.raises(CandidateClosedError):
        RejectRelationCandidate(store, clock).run(
            refers, CandidateRejectReason.WRONG_TARGET, decided_by="a"
        )
    assert len(store.audit_entries()) == 2
