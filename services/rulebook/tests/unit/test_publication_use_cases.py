"""The citation, review and publish use cases end to end on the memory store: one approver or
two, a returned version starting a new round, replacements dated before and after today, the
daily sweep, and the events with their causation."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from domain_kernel.audit import AuditActor
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvalidTransitionError, InvariantViolationError
from domain_kernel.ids import ClauseId, DocumentId, RuleVersionId, SourceId, UserId
from domain_kernel.knowledge import EntityType, RelationKind, RuleRelation
from domain_kernel.status import RuleVersionStatus
from rulebook.application.documents import RegisterDocument
from rulebook.application.publication import (
    AddCitations,
    ApplyDueTransitions,
    ApproveVersion,
    CitationInput,
    PublishVersion,
    ReturnToDraft,
    SubmitForReview,
    WithdrawVersion,
    today_in_india,
)
from rulebook.application.rule_versions import ListRulesInForce
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import (
    CitationNotVerifiedError,
    CitationsMissingError,
    DuplicateApproverError,
    OverlappingVersionError,
    PublishingDisabledError,
    ReplacementsPendingError,
    RuleVersionNotEditableError,
    SyntheticApprovalRefusedError,
    UnknownClauseError,
    UnknownRuleVersionError,
)
from rulebook.domain.events import (
    RuleDeadlineChanged,
    RulePublished,
    RuleSuperseded,
    RuleWithdrawn,
)
from rulebook.domain.ids import citation_id_for
from rulebook.domain.publication import DecisionAction
from rulebook.domain.relations import RelationCandidate
from rulebook.domain.seed import SeedStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore

TEXT = (
    "The due date for furnishing the return in FORM GSTR-3B for the month of September, 2026 "
    "is extended till the 27th day of October, 2026."
)
QUOTE = "furnishing the return in FORM GSTR-3B for the month of September, 2026"
APRIL = date(2026, 4, 1)
JULY = date(2026, 7, 1)
NOVEMBER = date(2026, 11, 1)
START = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
"""10:00 in India on 1 October 2026."""
ANALYST = UserId(UUID(int=11))
REVIEWER = UserId(UUID(int=12))
SPECIFICATION = {"attribute": "registration_type", "operator": "eq", "value": "regular"}


class Clock:
    """Moves one minute on every reading, so every step of a flow has its own time."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


class Flow:
    """The use cases on one store and one clock, publishing turned on."""

    def __init__(self, store: MemoryKnowledgeStore, clock: Clock) -> None:
        self.cite = AddCitations(store, clock)
        self.submit = SubmitForReview(store, clock)
        self.return_to_draft = ReturnToDraft(store, clock)
        self.approve = ApproveVersion(store, clock)
        self.publish = PublishVersion(store, enabled=True, clock=clock)
        self.withdraw = WithdrawVersion(store, enabled=True, clock=clock)
        self.sweep = ApplyDueTransitions(store, enabled=True, clock=clock)

    def through_review(self, version: RuleVersionId, clause: ClauseId) -> None:
        self.cite.run(version, [CitationInput(clause, QUOTE)])
        self.submit.run(version, actor_id=ANALYST)
        self.approve.run(version, actor_id=REVIEWER)


def register(store: MemoryKnowledgeStore, name: str = "n1") -> DocumentId:
    digest = hashlib.sha256(name.encode()).hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url=f"https://example.invalid/{name}.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=START,
            published_at=date(2026, 9, 30),
        ),
        [Clause("en.p1", TEXT)],
    )
    return document_id


def relate(
    store: MemoryKnowledgeStore,
    x: RuleVersionId,
    kind: RelationKind,
    y: RuleVersionId,
    evidence: ClauseId,
    candidate_id: UUID | None = None,
) -> None:
    with store() as uow:
        uow.relations.add(
            RuleRelation(x, kind, y, evidence), relation_id=uuid4(), candidate_id=candidate_id
        )


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
    return clause_id_for(register(store), "en.p1")


def draft(store: MemoryKnowledgeStore, key: str = "gstr3b_extension") -> RuleVersionId:
    _, version = store.add_rule(
        key, title="Extension", specification=SPECIFICATION, effective_from=JULY
    )
    return version


# ---------------------------------------------------------------- citations


def test_citations_are_verified_and_stored_once(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    first = flow.cite.run(version, [CitationInput(clause, QUOTE), CitationInput(clause, QUOTE)])
    assert (first.added, first.unchanged) == (1, 0)
    (stored,) = first.citations
    assert stored.citation_id == citation_id_for(version, clause, QUOTE)
    assert (stored.verified, stored.match_score, stored.clause_ref) == (True, 1.0, "en.p1")
    assert stored.verified_at is not None
    again = flow.cite.run(version, [CitationInput(clause, QUOTE)])
    assert (again.added, again.unchanged, len(again.citations)) == (0, 1, 1)


def test_citations_are_all_or_nothing(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    wrong_month = QUOTE.replace("September", "August")
    with pytest.raises(CitationNotVerifiedError, match="missing august"):
        flow.cite.run(version, [CitationInput(clause, QUOTE), CitationInput(clause, wrong_month)])
    with pytest.raises(CitationNotVerifiedError, match="score"):
        flow.cite.run(version, [CitationInput(clause, "an unrelated sentence entirely")])
    with pytest.raises(UnknownClauseError):
        flow.cite.run(version, [CitationInput(ClauseId(UUID(int=99)), QUOTE)])
    with pytest.raises(InvariantViolationError):
        flow.cite.run(version, [])
    with pytest.raises(UnknownRuleVersionError):
        flow.cite.run(RuleVersionId(UUID(int=98)), [CitationInput(clause, QUOTE)])
    with store() as uow:
        assert uow.citations.for_version(version) == ()


@pytest.mark.parametrize(
    "status",
    [RuleVersionStatus.IN_REVIEW, RuleVersionStatus.APPROVED, RuleVersionStatus.PUBLISHED],
)
def test_only_a_draft_takes_new_citations(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId, status: RuleVersionStatus
) -> None:
    _, version = store.add_rule("gstr1_monthly", status=status)
    with pytest.raises(RuleVersionNotEditableError, match=status.value):
        flow.cite.run(version, [CitationInput(clause, QUOTE)])
    with store() as uow:
        assert uow.citations.for_version(version) == ()


# ---------------------------------------------------------------- review


def test_one_approver_publishes_a_version(
    store: MemoryKnowledgeStore, flow: Flow, clock: Clock, clause: ClauseId
) -> None:
    version = draft(store)
    flow.cite.run(version, [CitationInput(clause, QUOTE)])
    submitted = flow.submit.run(version, actor_id=ANALYST, note="ready")
    assert submitted.record.status is RuleVersionStatus.IN_REVIEW
    assert submitted.record.submitted_at is not None
    approved = flow.approve.run(version, actor_id=REVIEWER)
    assert approved.record.status is RuleVersionStatus.APPROVED
    assert approved.record.seed_status is SeedStatus.REVIEWED
    assert (approved.approvers, approved.required_approvals) == ((REVIEWER,), 1)

    publication = flow.publish.run(version, actor_id=ANALYST)
    assert publication.plan.published.status is RuleVersionStatus.PUBLISHED
    assert publication.plan.published.published_at == clock.now
    (event,) = store.events()
    assert isinstance(event, RulePublished)
    assert event == publication.events[0]
    assert (event.rule_version_id, event.approved_by, event.supersedes) == (
        version,
        (REVIEWER,),
        (),
    )
    assert (event.title, event.effective_from, event.high_impact) == ("Extension", JULY, False)
    assert event.attribute_keys == ("registration_type",)
    assert event.correlation_id == publication.correlation_id
    assert [d.action for d in store.decisions(version)] == [
        DecisionAction.SUBMITTED,
        DecisionAction.APPROVED,
        DecisionAction.PUBLISHED,
    ]
    assert store.decisions(version)[0].note == "ready"
    in_force = ListRulesInForce(store).run(date(2026, 10, 1))
    assert [record.rule_version_id for record in in_force] == [version]


def test_a_high_impact_version_needs_two_different_approvers(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    flow.cite.run(version, [CitationInput(clause, QUOTE)])
    flow.submit.run(version, actor_id=ANALYST, high_impact=True)
    first = flow.approve.run(version, actor_id=REVIEWER)
    assert first.record.status is RuleVersionStatus.IN_REVIEW
    assert (first.approvers, first.required_approvals) == ((REVIEWER,), 2)
    with pytest.raises(DuplicateApproverError):
        flow.approve.run(version, actor_id=REVIEWER)
    second = flow.approve.run(version, actor_id=ANALYST)
    assert second.record.status is RuleVersionStatus.APPROVED
    assert second.approvers == tuple(sorted((ANALYST, REVIEWER), key=str))
    with pytest.raises(InvalidTransitionError):
        flow.approve.run(version, actor_id=UserId(UUID(int=13)))
    event = flow.publish.run(version, actor_id=ANALYST).events[0]
    assert isinstance(event, RulePublished)
    assert event.high_impact
    assert event.approved_by == second.approvers


def test_returning_a_version_starts_a_new_round(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    flow.cite.run(version, [CitationInput(clause, QUOTE)])
    flow.submit.run(version, actor_id=ANALYST, high_impact=True)
    flow.approve.run(version, actor_id=REVIEWER)
    returned = flow.return_to_draft.run(version, actor_id=REVIEWER, note="fix the dates")
    assert (returned.record.status, returned.record.submitted_at) == (
        RuleVersionStatus.DRAFT,
        None,
    )
    resubmitted = flow.submit.run(version, actor_id=ANALYST, high_impact=False)
    assert resubmitted.record.high_impact, "a high-impact tag is never cleared"
    again = flow.approve.run(version, actor_id=ANALYST)
    assert again.approvers == (ANALYST,), "the earlier round's approval does not count"
    assert again.record.status is RuleVersionStatus.IN_REVIEW
    assert flow.approve.run(version, actor_id=REVIEWER).record.status is RuleVersionStatus.APPROVED
    assert [d.action for d in store.decisions(version)] == [
        DecisionAction.SUBMITTED,
        DecisionAction.APPROVED,
        DecisionAction.RETURNED,
        DecisionAction.SUBMITTED,
        DecisionAction.APPROVED,
        DecisionAction.APPROVED,
    ]


def test_an_approved_version_is_returned_to_draft_to_change_it(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    flow.through_review(version, clause)
    other = "The due date for furnishing the return in FORM GSTR-3B for the month of September"
    with pytest.raises(RuleVersionNotEditableError, match="approved"):
        flow.cite.run(version, [CitationInput(clause, other)])
    returned = flow.return_to_draft.run(version, actor_id=ANALYST, note="one more citation")
    assert (returned.record.status, returned.record.submitted_at) == (RuleVersionStatus.DRAFT, None)
    assert returned.record.seed_status is SeedStatus.NEEDS_REVIEW
    assert flow.cite.run(version, [CitationInput(clause, other)]).added == 1
    flow.submit.run(version, actor_id=ANALYST)
    with pytest.raises(InvalidTransitionError):
        flow.publish.run(version, actor_id=ANALYST)
    again = flow.approve.run(version, actor_id=REVIEWER)
    assert (again.record.status, again.record.seed_status) == (
        RuleVersionStatus.APPROVED,
        SeedStatus.REVIEWED,
    )
    assert flow.publish.run(version, actor_id=ANALYST).plan.published.status is (
        RuleVersionStatus.PUBLISHED
    )
    assert [d.action for d in store.decisions(version)] == [
        DecisionAction.SUBMITTED,
        DecisionAction.APPROVED,
        DecisionAction.RETURNED,
        DecisionAction.SUBMITTED,
        DecisionAction.APPROVED,
        DecisionAction.PUBLISHED,
    ]


def test_a_synthetic_round_publishes_and_leaves_the_version_needs_review(
    store: MemoryKnowledgeStore, clock: Clock, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    synthetic = ApproveVersion(store, clock, synthetic_allowed=True)
    flow.cite.run(version, [CitationInput(clause, QUOTE)])
    flow.submit.run(version, actor_id=ANALYST, high_impact=True, note="synthetic")
    first = synthetic.run(version, actor_id=REVIEWER, synthetic=True)
    assert first.record.status is RuleVersionStatus.IN_REVIEW
    with pytest.raises(DuplicateApproverError):
        synthetic.run(version, actor_id=REVIEWER, synthetic=True)
    second = synthetic.run(version, actor_id=UserId(UUID(int=13)), synthetic=True)
    assert (second.record.status, second.record.seed_status) == (
        RuleVersionStatus.APPROVED,
        SeedStatus.NEEDS_REVIEW,
    )
    published = flow.publish.run(version, actor_id=REVIEWER).plan.published
    assert (published.status, published.seed_status) == (
        RuleVersionStatus.PUBLISHED,
        SeedStatus.NEEDS_REVIEW,
    )


def test_a_real_approval_that_completes_the_round_marks_the_version_reviewed(
    store: MemoryKnowledgeStore, clock: Clock, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    flow.cite.run(version, [CitationInput(clause, QUOTE)])
    flow.submit.run(version, actor_id=ANALYST, high_impact=True)
    ApproveVersion(store, clock, synthetic_allowed=True).run(
        version, actor_id=REVIEWER, synthetic=True
    )
    assert flow.approve.run(version, actor_id=ANALYST).record.seed_status is SeedStatus.REVIEWED


def test_a_synthetic_approval_is_refused_unless_allowed(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    flow.cite.run(version, [CitationInput(clause, QUOTE)])
    flow.submit.run(version, actor_id=ANALYST)
    with pytest.raises(SyntheticApprovalRefusedError, match="local or test"):
        flow.approve.run(version, actor_id=REVIEWER, synthetic=True)
    with store() as uow:
        record = uow.rule_versions.get(version)
    assert record is not None
    assert (record.status, record.seed_status) == (
        RuleVersionStatus.IN_REVIEW,
        SeedStatus.NEEDS_REVIEW,
    )
    assert [d.action for d in store.decisions(version)] == [DecisionAction.SUBMITTED]


def test_review_steps_follow_the_transition_table(store: MemoryKnowledgeStore, flow: Flow) -> None:
    version = draft(store)
    with pytest.raises(InvalidTransitionError):
        flow.approve.run(version, actor_id=REVIEWER)
    with pytest.raises(InvalidTransitionError):
        flow.return_to_draft.run(version, actor_id=REVIEWER)
    with pytest.raises(UnknownRuleVersionError):
        flow.submit.run(RuleVersionId(UUID(int=97)), actor_id=ANALYST)
    _, legacy = store.add_rule("legacy", status=RuleVersionStatus.IN_REVIEW)
    with pytest.raises(InvariantViolationError, match="no review round"):
        flow.approve.run(legacy, actor_id=REVIEWER)


def test_publishing_needs_citations_and_changes_nothing_when_refused(
    store: MemoryKnowledgeStore, flow: Flow
) -> None:
    version = draft(store)
    flow.submit.run(version, actor_id=ANALYST)
    flow.approve.run(version, actor_id=REVIEWER)
    with pytest.raises(CitationsMissingError):
        flow.publish.run(version, actor_id=ANALYST)
    with store() as uow:
        record = uow.rule_versions.get(version)
    assert record is not None
    assert record.status is RuleVersionStatus.APPROVED
    assert store.events() == []
    assert DecisionAction.PUBLISHED not in [d.action for d in store.decisions(version)]


def test_the_flag_turns_publishing_off(
    store: MemoryKnowledgeStore, clock: Clock, flow: Flow, clause: ClauseId
) -> None:
    version = draft(store)
    flow.through_review(version, clause)
    with pytest.raises(PublishingDisabledError):
        PublishVersion(store, enabled=False, clock=clock).run(version, actor_id=ANALYST)
    with pytest.raises(PublishingDisabledError):
        WithdrawVersion(store, enabled=False, clock=clock).run(version, actor_id=ANALYST)
    with pytest.raises(PublishingDisabledError):
        ApplyDueTransitions(store, enabled=False, clock=clock).run()
    assert store.events() == []


# ---------------------------------------------------------------- relations


def test_a_replacement_in_effect_moves_its_target_at_publication(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    _, old = store.add_rule(
        "gstr3b_monthly", title="Monthly", status=RuleVersionStatus.PUBLISHED, effective_from=APRIL
    )
    new = store.add_version("gstr3b_monthly", title="Monthly, amended", effective_from=JULY)
    relate(store, new, RelationKind.SUPERSEDES, old, clause)
    flow.through_review(new, clause)
    publication = flow.publish.run(new, actor_id=ANALYST)

    published, superseded = store.events()
    assert isinstance(published, RulePublished)
    assert isinstance(superseded, RuleSuperseded)
    assert published.supersedes == (old,)
    assert (superseded.rule_version_id, superseded.superseded_by_rule_version_id) == (old, new)
    assert superseded.effective_from == JULY
    assert superseded.causation_id == published.event_id
    assert superseded.correlation_id == published.correlation_id == publication.correlation_id
    with store() as uow:
        replaced = uow.rule_versions.get(old)
    assert replaced is not None
    assert (replaced.status, replaced.effective_to) == (RuleVersionStatus.SUPERSEDED, JULY)
    (moved,) = store.decisions(old)
    assert (moved.action, moved.caused_by, moved.actor_id) == (
        DecisionAction.SUPERSEDED,
        new,
        None,
    )
    june = ListRulesInForce(store).run(date(2026, 6, 30))
    assert [record.rule_version_id for record in june] == [old]


def test_a_future_replacement_waits_for_the_sweep(
    store: MemoryKnowledgeStore, flow: Flow, clock: Clock, clause: ClauseId
) -> None:
    _, old = store.add_rule(
        "gstr3b_monthly", title="Monthly", status=RuleVersionStatus.PUBLISHED, effective_from=APRIL
    )
    new = store.add_version("gstr3b_monthly", title="Monthly, amended", effective_from=NOVEMBER)
    relate(store, new, RelationKind.WITHDRAWS, old, clause)
    flow.through_review(new, clause)
    (replacement,) = flow.publish.run(new, actor_id=ANALYST).plan.replacements
    assert not replacement.due
    assert [type(event) for event in store.events()] == [RulePublished]
    with store() as uow:
        waiting = uow.rule_versions.get(old)
    assert waiting is not None
    assert (waiting.status, waiting.effective_to) == (RuleVersionStatus.PUBLISHED, NOVEMBER)
    in_force = ListRulesInForce(store)
    assert [r.rule_version_id for r in in_force.run(date(2026, 10, 31))] == [old]
    assert [r.rule_version_id for r in in_force.run(NOVEMBER)] == [new]

    assert flow.sweep.run().transitions == ()
    with pytest.raises(InvariantViolationError, match="after today"):
        flow.sweep.run(NOVEMBER)
    clock.now = datetime(2026, 10, 31, 18, 28, tzinfo=UTC)
    assert flow.sweep.run().transitions == (), "23:59 in India is still 31 October"
    assert today_in_india(clock.now) == date(2026, 10, 31)
    report = flow.sweep.run()
    assert report.as_of == NOVEMBER
    (moved,) = report.transitions
    assert (moved.target_id, moved.replacing_id, moved.moves_to) == (
        old,
        new,
        RuleVersionStatus.WITHDRAWN,
    )
    (withdrawn,) = report.events
    assert isinstance(withdrawn, RuleWithdrawn)
    assert (withdrawn.withdrawn_by_rule_version_id, withdrawn.effective_from) == (new, NOVEMBER)
    assert withdrawn.causation_id is None
    assert store.events()[-1] == withdrawn
    assert flow.sweep.run().transitions == (), "a second run moves nothing"
    assert [d.action for d in store.decisions(old)] == [DecisionAction.WITHDRAWN]


@pytest.mark.parametrize(
    ("effective_to", "cut"), [(None, JULY), (date(2026, 6, 1), date(2026, 6, 1))]
)
def test_the_sweep_cuts_a_moved_version_at_its_replacement(
    store: MemoryKnowledgeStore,
    flow: Flow,
    clause: ClauseId,
    effective_to: date | None,
    cut: date,
) -> None:
    _, old = store.add_rule(
        "gstr3b_monthly",
        status=RuleVersionStatus.PUBLISHED,
        effective_from=APRIL,
        effective_to=effective_to,
    )
    new = store.add_version(
        "gstr3b_monthly", status=RuleVersionStatus.PUBLISHED, effective_from=JULY
    )
    relate(store, new, RelationKind.SUPERSEDES, old, clause)
    (moved,) = flow.sweep.run().transitions
    assert moved.target_id == old
    with store() as uow:
        superseded = uow.rule_versions.get(old)
    assert superseded is not None
    assert (superseded.status, superseded.effective_to) == (RuleVersionStatus.SUPERSEDED, cut)


def test_extends_deadline_announces_the_new_date(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    _, monthly = store.add_rule(
        "gstr3b_monthly",
        title="Monthly",
        status=RuleVersionStatus.PUBLISHED,
        effective_from=APRIL,
        recurrence={"frequency": "monthly", "due_day": 20, "due_month_offset": 0},
    )
    extension = draft(store)
    candidate_id = uuid4()
    document_id = store_document(store, clause)
    with store() as uow:
        uow.candidates.add(
            RelationCandidate(
                candidate_id=candidate_id,
                document_id=document_id,
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
    relate(store, extension, RelationKind.EXTENDS_DEADLINE, monthly, clause, candidate_id)
    flow.through_review(extension, clause)
    published, changed = flow.publish.run(extension, actor_id=ANALYST).events
    assert isinstance(changed, RuleDeadlineChanged)
    assert (changed.rule_version_id, changed.caused_by_rule_version_id) == (monthly, extension)
    assert (changed.period_label, changed.new_due_on) == ("2026-09", date(2026, 10, 27))
    assert changed.causation_id == published.event_id
    with store() as uow:
        unchanged = uow.rule_versions.get(monthly)
    assert unchanged is not None
    assert unchanged.status is RuleVersionStatus.PUBLISHED


def store_document(store: MemoryKnowledgeStore, clause: ClauseId) -> DocumentId:
    with store() as uow:
        detail = uow.documents.clause(clause)
    assert detail is not None
    return detail.clause.document_id


def test_an_overlapping_version_is_refused(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    store.add_rule("gstr3b_monthly", status=RuleVersionStatus.PUBLISHED, effective_from=APRIL)
    new = store.add_version("gstr3b_monthly", title="Monthly, again", effective_from=JULY)
    flow.through_review(new, clause)
    with pytest.raises(OverlappingVersionError):
        flow.publish.run(new, actor_id=ANALYST)
    assert store.events() == []


# ---------------------------------------------------------------- withdrawal


def test_a_published_version_is_withdrawn_today(
    store: MemoryKnowledgeStore, flow: Flow, clock: Clock
) -> None:
    rule_id, version = store.add_rule("gstr1_monthly", status=RuleVersionStatus.PUBLISHED)
    state = flow.withdraw.run(version, actor_id=ANALYST, note="rescinded")
    assert state.record.status is RuleVersionStatus.WITHDRAWN
    (event,) = state.events
    assert isinstance(event, RuleWithdrawn)
    assert (event.rule_id, event.withdrawn_by_rule_version_id) == (rule_id, None)
    assert event.effective_from == today_in_india(clock.now)
    assert store.events() == [event]
    (decision,) = store.decisions(version)
    assert (decision.action, decision.actor_id, decision.note) == (
        DecisionAction.WITHDRAWN,
        ANALYST,
        "rescinded",
    )
    with pytest.raises(InvalidTransitionError):
        flow.withdraw.run(version, actor_id=ANALYST)
    assert ListRulesInForce(store).run(date(2026, 10, 1)) == []


def test_a_version_is_not_withdrawn_before_its_replacements_take_effect(
    store: MemoryKnowledgeStore, flow: Flow, clock: Clock, clause: ClauseId
) -> None:
    _, old = store.add_rule(
        "gstr3b_monthly", title="Monthly", status=RuleVersionStatus.PUBLISHED, effective_from=APRIL
    )
    new = store.add_version("gstr3b_monthly", title="Monthly, amended", effective_from=NOVEMBER)
    relate(store, new, RelationKind.SUPERSEDES, old, clause)
    flow.through_review(new, clause)
    flow.publish.run(new, actor_id=ANALYST)
    events = store.events()
    with pytest.raises(ReplacementsPendingError, match=str(old)):
        flow.withdraw.run(new, actor_id=ANALYST)
    with store() as uow:
        waiting, still = uow.rule_versions.get(old), uow.rule_versions.get(new)
    assert waiting is not None
    assert still is not None
    assert (waiting.status, waiting.effective_to) == (RuleVersionStatus.PUBLISHED, NOVEMBER)
    assert still.status is RuleVersionStatus.PUBLISHED
    assert store.events() == events

    clock.now = datetime(2026, 10, 31, 18, 30, tzinfo=UTC)
    assert [moved.target_id for moved in flow.sweep.run().transitions] == [old]
    withdrawn = flow.withdraw.run(new, actor_id=ANALYST, note="rescinded after it took effect")
    assert withdrawn.record.status is RuleVersionStatus.WITHDRAWN


def test_every_event_is_regulatory_and_keyed_by_its_rule(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    rule_id, old = store.add_rule(
        "gstr3b_monthly", title="Monthly", status=RuleVersionStatus.PUBLISHED, effective_from=APRIL
    )
    new = store.add_version("gstr3b_monthly", title="Monthly, amended", effective_from=JULY)
    relate(store, new, RelationKind.CORRECTS, old, clause)
    flow.through_review(new, clause)
    events = flow.publish.run(new, actor_id=ANALYST).events
    assert [type(event) for event in events] == [RulePublished, RuleSuperseded]
    assert {event.tenant_id for event in events} == {None}
    assert {event.partition_key for event in events} == {str(rule_id)}
    published = events[0]
    assert isinstance(published, RulePublished)
    assert published.supersedes == (), "only supersedes relations are listed"


def test_the_clock_reads_days_in_india() -> None:
    assert today_in_india(datetime(2026, 10, 31, 18, 30, tzinfo=UTC)) == NOVEMBER


def test_withdrawal_needs_the_version(flow: Flow) -> None:
    with pytest.raises(UnknownRuleVersionError):
        flow.withdraw.run(RuleVersionId(UUID(int=96)), actor_id=ANALYST)


def test_publishing_an_unknown_version_is_refused(flow: Flow) -> None:
    with pytest.raises(UnknownRuleVersionError):
        flow.publish.run(RuleVersionId(UUID(int=95)), actor_id=ANALYST)


def test_sweep_helper_types(flow: Flow) -> None:
    report = flow.sweep.run(date(2026, 9, 1))
    assert (report.as_of, report.transitions, report.events) == (date(2026, 9, 1), (), ())


# ---------------------------------------------------------------- the audit log


def test_each_step_writes_one_platform_entry(
    store: MemoryKnowledgeStore, flow: Flow, clock: Clock, clause: ClauseId
) -> None:
    version = draft(store)
    flow.cite.run(version, [CitationInput(clause, QUOTE)])
    assert store.audit_entries() == [], "citing is content: no entry"
    flow.submit.run(version, actor_id=ANALYST, note="ready", high_impact=True)
    flow.approve.run(version, actor_id=REVIEWER)
    flow.return_to_draft.run(version, actor_id=REVIEWER, note="Example: fix the dates")
    flow.submit.run(version, actor_id=ANALYST)
    flow.approve.run(version, actor_id=REVIEWER)
    flow.approve.run(version, actor_id=ANALYST, note="checked")
    flow.publish.run(version, actor_id=ANALYST, note="Example: go")
    published_at = clock.now
    flow.withdraw.run(version, actor_id=REVIEWER, note="rescinded")
    entries = store.audit_entries()
    assert [entry.action for entry in entries] == [
        "rule_version.submitted",
        "rule_version.approved",
        "rule_version.returned",
        "rule_version.submitted",
        "rule_version.approved",
        "rule_version.approved",
        "rule_version.published",
        "rule_version.withdrawn",
    ]
    assert {(entry.subject_type, entry.subject_id, entry.tenant_id) for entry in entries} == {
        ("rule_version", str(version), None)
    }
    assert [entry.actor for entry in entries] == [
        AuditActor.user(user)
        for user in (ANALYST, REVIEWER, REVIEWER, ANALYST, REVIEWER, ANALYST, ANALYST, REVIEWER)
    ]
    assert [entry.reason for entry in entries] == [
        "ready",
        "",
        "Example: fix the dates",
        "",
        "",
        "checked",
        "Example: go",
        "rescinded",
    ]
    submitted, first, returned, _, second, third, published, withdrawn = entries
    assert (submitted.before, submitted.after) == (
        {"status": "draft"},
        {"status": "in_review", "high_impact": True},
    )
    assert (first.before, first.after) == (
        {"status": "in_review"},
        {"status": "in_review", "approvals": 1, "required_approvals": 2, "synthetic": False},
    )
    assert (returned.before, returned.after) == ({"status": "in_review"}, {"status": "draft"})
    assert second.after is not None
    assert second.after["approvals"] == 1, "the returned round's approval no longer counts"
    assert third.after == {
        "status": "approved",
        "approvals": 2,
        "required_approvals": 2,
        "synthetic": False,
    }
    assert (published.before, published.after, published.occurred_at) == (
        {"status": "approved"},
        {"status": "published", "replaced": ()},
        published_at,
    )
    assert (withdrawn.before, withdrawn.after) == (
        {"status": "published"},
        {"status": "withdrawn"},
    )


def test_a_publication_names_the_versions_it_replaces(
    store: MemoryKnowledgeStore, flow: Flow, clause: ClauseId
) -> None:
    _, old = store.add_rule(
        "gstr3b_monthly", title="Monthly", status=RuleVersionStatus.PUBLISHED, effective_from=APRIL
    )
    new = store.add_version("gstr3b_monthly", title="Monthly, amended", effective_from=JULY)
    relate(store, new, RelationKind.SUPERSEDES, old, clause)
    flow.through_review(new, clause)
    flow.publish.run(new, actor_id=ANALYST)
    (published,) = store.audit_entries("rule_version.published")
    assert published.after == {"status": "published", "replaced": (str(old),)}
    assert store.audit_entries("rule_version.superseded") == [], "a moved version: no entry"


def test_a_refused_step_writes_nothing(
    store: MemoryKnowledgeStore, flow: Flow, clock: Clock
) -> None:
    version = draft(store)
    with pytest.raises(InvalidTransitionError):
        flow.approve.run(version, actor_id=REVIEWER)
    flow.submit.run(version, actor_id=ANALYST)
    flow.approve.run(version, actor_id=REVIEWER)
    with pytest.raises(CitationsMissingError):
        flow.publish.run(version, actor_id=ANALYST)
    with pytest.raises(PublishingDisabledError):
        WithdrawVersion(store, enabled=False, clock=clock).run(version, actor_id=ANALYST)
    with pytest.raises(InvalidTransitionError):
        flow.withdraw.run(version, actor_id=ANALYST)
    assert [entry.action for entry in store.audit_entries()] == [
        "rule_version.submitted",
        "rule_version.approved",
    ]
