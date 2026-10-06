"""Rule candidates through review on the memory store: the intake of a rule.candidate.created
payload into a candidate and its task, a version drafted from the candidate (into an existing
rule or a new one, cited, with a relation candidate approved onto it, the analyst's changes in
the audit), the decisions on a candidate task with rule.rejected, a rejection after drafting that
closes the draft and reopens its relations, the queue, the detail, the stats, and the seed tasks
and seed command, which leave candidate drafts alone and skip closed ones."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from jsonschema import Draft202012Validator

import ontology as ontology_package
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import SourceId, UserId
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.ontology import AttributeLevel, Ontology
from domain_kernel.status import RuleVersionStatus
from py_common.events import to_message
from rulebook.application.documents import RegisterDocument
from rulebook.application.intake import IngestRuleCandidate
from rulebook.application.publication import (
    AddCitations,
    ApproveVersion,
    CitationInput,
    PublishVersion,
    SubmitForReview,
)
from rulebook.application.relations import ApproveRelationCandidate, RejectRelationCandidate
from rulebook.application.review_tasks import (
    ClaimReviewTask,
    DecideReviewTask,
    DraftFromCandidate,
    EditReviewDraft,
    ListReviewTasks,
    NewRule,
    OpenSeedReviewTasks,
    ReadReviewStats,
    ReadReviewTask,
    RelationChoice,
)
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.documents import StoredDocument
from rulebook.domain.drafting import DraftEdit
from rulebook.domain.errors import (
    CandidateAlreadyDraftedError,
    CandidateNotDraftedError,
    CandidatePayloadInvalidError,
    CitationNotVerifiedError,
    DraftIncompleteError,
    ReviewTaskNotClaimedError,
    RuleKeyTakenError,
    RuleKeyUnknownError,
    RuleVersionClosedError,
    UnknownDocumentError,
)
from rulebook.domain.events import RuleRejected
from rulebook.domain.intake import (
    HIGH_IMPACT_PRIORITY,
    ROUTINE_PRIORITY,
    RuleCandidateStatus,
    RuleRejectReason,
)
from rulebook.domain.publication import DecisionAction
from rulebook.domain.relations import CandidateRejectReason, CandidateStatus, RelationCandidate
from rulebook.domain.review_tasks import ReviewDecision, ReviewTaskKind, ReviewTaskStatus
from rulebook.domain.seed import SeedCalendar
from rulebook.infrastructure.memory import MemoryEventSink, MemoryKnowledgeStore

SCHEMAS = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "schemas"
START = datetime(2000, 1, 3, 4, 30, tzinfo=UTC)
ANALYST = UserId(UUID(int=61))
REVIEWER = UserId(UUID(int=62))
OTHER_REVIEWER = UserId(UUID(int=63))
MONTHLY = "example_monthly"
EXTENSION = "example_extension_2000_01"
CLAUSES = (
    Clause("en.p1", "Example notification No. 01/2000 of the example board."),
    Clause(
        "en.p2",
        "The example board extends the due date for furnishing the example return for the "
        "month of January, 2000 till the twenty-fifth day of February, 2000.",
    ),
    Clause("en.p3", "This example notification shall come into effect from 1st February, 2000."),
)
QUOTE_EXTENDS = "extends the due date for furnishing the example return for the month of January"
QUOTE_EFFECT = "shall come into effect from 1st February, 2000"
DIGEST = hashlib.sha256(b"example notification for candidate review").hexdigest()
DOC = document_id_for(DIGEST)
SPECIFICATION = {
    "all_of": [
        {"attribute": "registration_type", "operator": "eq", "value": "regular"},
        {"attribute": "filing_scheme", "operator": "eq", "value": "regular_monthly"},
    ]
}
FIELDS: dict[str, Any] = {
    "title": "Example: the due date of the example return is extended",
    "summary": "An example notification extends the due date of the example return.",
    "doc_kind": "notification",
    "change_kind": "extension",
    "effective_from": "2000-02-01",
    "effective_to": None,
    "references": [],
    "applies_to": [
        {
            "attribute": "registration_type",
            "operator": "eq",
            "value": "regular",
            "clause_ref": "en.p2",
        },
        {
            "attribute": "filing_scheme",
            "operator": "eq",
            "value": "regular_monthly",
            "clause_ref": "en.p2",
        },
    ],
    "obligation": {
        "title": "File the example return for January 2000",
        "steps": ["Furnish the example return"],
        "evidence_type": "filing_acknowledgement",
        "due_in_days": 25,
        "clause_ref": "en.p2",
    },
    "recurrence": None,
    "amounts": [],
    "citations": [
        {"clause_ref": "en.p2", "quote": QUOTE_EXTENDS},
        {"clause_ref": "en.p3", "quote": QUOTE_EFFECT},
    ],
    "confidence": 0.9,
}


class Clock:
    """Moves one minute on every reading, so every step has its own time."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def payload(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "candidate_id": str(uuid4()),
        "document_id": str(DOC),
        "regulator": "CBIC",
        "model": "fake/echo",
        "prompt_version": "extraction.rule_candidate@1",
        "confidence": 0.9,
        "citation_count": 2,
        "needs_review": False,
        "outcome": "extracted",
        "candidate": FIELDS,
        "issues": [],
        "suggested_rule_key": MONTHLY,
        "clause_ids": [str(clause_id_for(DOC, ref)) for ref in ("en.p2", "en.p3")],
        "doc_type": "notification",
        "source_id": str(UUID(int=11)),
        "source_key": "cbic_notifications",
        "ontology_version": "0.2.0",
    }
    values.update(overrides)
    return values


class Review:
    """The use cases on one memory store, with the example notification registered and the
    published monthly rule its extension targets."""

    def __init__(self, clock: Clock, ontology: Ontology) -> None:
        self.clock = clock
        self.store = MemoryKnowledgeStore(clock)
        self.ingest = IngestRuleCandidate(self.store, clock)
        self.list = ListReviewTasks(self.store)
        self.claim = ClaimReviewTask(self.store, clock)
        self.read = ReadReviewTask(self.store)
        self.draft = DraftFromCandidate(self.store, lambda: ontology, clock)
        self.edit = EditReviewDraft(self.store, lambda: ontology, clock)
        self.decide = DecideReviewTask(self.store, clock)
        self.stats = ReadReviewStats(self.store)
        self.seed = OpenSeedReviewTasks(self.store, clock)
        self.publish = PublishVersion(self.store, enabled=True, clock=clock)
        RegisterDocument(self.store).run(
            StoredDocument(
                document_id=DOC,
                source_id=SourceId(UUID(int=11)),
                sha256=DIGEST,
                regulator="CBIC",
                doc_type=DocumentType.NOTIFICATION,
                url="https://example.invalid/notification-01-2000.pdf",
                language="en",
                media_type="application/pdf",
                parser_version="pdf@1",
                fetched_at=START,
                external_ref="01/2000-Example",
                title="Example notification 01/2000",
                published_at=date(2000, 1, 2),
            ),
            list(CLAUSES),
        )
        _, self.monthly = self.store.add_rule(
            MONTHLY,
            title="Example monthly return",
            regulator="cbic",
            status=RuleVersionStatus.PUBLISHED,
            effective_from=date(2000, 1, 1),
            specification=SPECIFICATION,
            obligation_template={"title": "File the example return", "steps": []},
            recurrence={"frequency": "monthly", "due_day": 20, "due_month_offset": 0},
            published_at=START,
        )

    def received(self, **overrides: Any) -> UUID:
        """The task the intake opens for a payload."""
        intake = self.ingest.run(payload(**overrides), uuid4())
        assert intake.task is not None
        return intake.task.task_id

    def relation(self, rule_key: str = MONTHLY) -> UUID:
        """The extension the knowledge child staged for the notification, as staging does, of
        the rule ``rule_key``."""
        clause = clause_id_for(DOC, "en.p2")
        text = CLAUSES[1].text
        candidate = RelationCandidate(
            candidate_id=uuid4(),
            document_id=DOC,
            relation=RelationKind.EXTENDS_DEADLINE,
            target_type=EntityType.FORM,
            target_name="example return",
            target_clause_id=clause,
            target_span_start=text.index("example return"),
            target_span_end=text.index("example return") + len("example return"),
            evidence_clause_id=clause,
            evidence_quote=QUOTE_EXTENDS,
            quote_score=1.0,
            prompt_version="extraction.rule_relations@1",
            confidence=0.9,
            needs_review=False,
            target_rule_key=rule_key,
            period_label="2000-01",
            new_due_on=date(2000, 2, 25),
        )
        with self.store() as uow:
            uow.candidates.add(candidate)
        return candidate.candidate_id

    def draft_new_rule(self, task_id: UUID, **overrides: Any) -> Any:
        values: dict[str, Any] = {
            "by": ANALYST,
            "rule_key": EXTENSION,
            "new_rule": NewRule("cbic", AttributeLevel.REGISTRATION),
        }
        values.update(overrides)
        return self.draft.run(task_id, **values)


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


@pytest.fixture
def review(ontology: Ontology) -> Review:
    return Review(Clock(), ontology)


# ---------------------------------------------------------------- the intake


def test_an_event_becomes_one_candidate_and_one_task(review: Review) -> None:
    body = payload(needs_review=False, candidate={**FIELDS, "change_kind": "none"})
    first = review.ingest.run(body, uuid4())
    assert first.created
    assert first.task is not None
    task = first.task
    assert (task.kind, task.regulator, task.priority, task.rule_version_id) == (
        ReviewTaskKind.CANDIDATE,
        "cbic",
        ROUTINE_PRIORITY,
        None,
    )
    assert first.candidate.suggested_rule_key == MONTHLY, "a rule has the payload's key"
    again = review.ingest.run(body, uuid4())
    assert (again.created, again.task) == (False, None), "one candidate per candidate id"
    assert len(review.store.rule_candidates()) == 1
    assert len(review.store.review_tasks()) == 1


def test_an_unknown_document_or_a_refused_payload_stores_nothing(review: Review) -> None:
    with pytest.raises(UnknownDocumentError):
        review.ingest.run(payload(document_id=str(uuid4())), uuid4())
    with pytest.raises(CandidatePayloadInvalidError):
        review.ingest.run(payload(confidence=2), uuid4())
    assert review.store.rule_candidates() == []
    assert review.store.review_tasks() == []


def test_the_suggestion_is_a_real_rule_key_when_one_is_known(review: Review) -> None:
    unknown = payload(suggested_rule_key="example_quarterly")
    stored = review.ingest.run(unknown, uuid4()).candidate
    assert stored.suggested_rule_key == "example_quarterly", "a key for a new rule"
    review.relation()
    from_relations = review.ingest.run(payload(suggested_rule_key=None), uuid4()).candidate
    assert from_relations.suggested_rule_key == MONTHLY, "the one key its relations name"
    named = review.ingest.run(payload(suggested_rule_key="example_quarterly"), uuid4()).candidate
    assert named.suggested_rule_key == MONTHLY, "a known key wins over an unknown one"


def test_the_suggestion_leaves_a_rejected_relation_candidate_out(review: Review) -> None:
    wrong = review.relation()
    RejectRelationCandidate(review.store, review.clock).run(
        wrong, CandidateRejectReason.WRONG_TARGET, decided_by=str(ANALYST)
    )
    alone = review.ingest.run(payload(suggested_rule_key=None), uuid4()).candidate
    assert alone.suggested_rule_key is None, "only a rejected relation candidate names a key"
    review.relation("example_quarterly")
    named = review.ingest.run(payload(suggested_rule_key=None), uuid4()).candidate
    assert named.suggested_rule_key == "example_quarterly", "the one key the others name"


def test_an_extension_is_suggested_high_impact_and_queued_first(review: Review) -> None:
    review.received(candidate={**FIELDS, "change_kind": "none"})
    extension = review.received()
    queued = review.list.run()
    assert queued[0].task.task_id == extension
    first = queued[0]
    assert (first.task.priority, first.high_impact, first.version, first.rule_key) == (
        HIGH_IMPACT_PRIORITY,
        True,
        None,
        MONTHLY,
    )
    assert first.title == FIELDS["title"]
    assert first.candidate is not None
    assert first.candidate.outcome.value == "extracted"
    assert [q.task.kind for q in review.list.run(kind=ReviewTaskKind.SEED)] == []
    assert len(review.list.run(regulator="CBIC", kind=ReviewTaskKind.CANDIDATE)) == 2


# ---------------------------------------------------------------- drafting


def test_drafting_a_new_rule_cites_it_and_approves_the_relation_onto_it(review: Review) -> None:
    relation = review.relation()
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    detail = review.draft_new_rule(
        task_id, relations=[RelationChoice(relation, review.monthly)], note="as extracted"
    )
    version = detail.version
    assert version is not None
    assert (version.rule_key, version.version, version.status, version.level) == (
        EXTENSION,
        1,
        RuleVersionStatus.DRAFT,
        AttributeLevel.REGISTRATION,
    )
    assert version.candidate_id is not None
    assert version.high_impact, "the candidate suggests it"
    assert version.specification == SPECIFICATION
    assert version.source["reference"] == "01/2000-Example"
    assert [(c.clause_ref, c.verified) for c in detail.citations] == [
        ("en.p2", True),
        ("en.p3", True),
    ]
    assert detail.decisions == (), "taken as it was: no edit recorded"
    assert detail.task.rule_version_id == version.rule_version_id
    assert detail.candidate is not None
    assert detail.candidate.candidate.status is RuleCandidateStatus.DRAFTED
    ((rule_relation, candidate_id),) = review.store.rule_relations()
    assert (rule_relation.from_rule_version_id, rule_relation.target) == (
        version.rule_version_id,
        review.monthly,
    )
    assert candidate_id == relation
    with review.store() as uow:
        staged = uow.candidates.lock(relation)
    assert staged is not None
    assert staged.status is CandidateStatus.APPROVED


def test_drafting_into_an_existing_rule_takes_its_next_version(review: Review) -> None:
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    detail = review.draft.run(task_id, by=ANALYST, rule_key=MONTHLY)
    assert detail.version is not None
    assert (detail.version.version, detail.version.regulator) == (2, "cbic")
    other = review.received()
    review.claim.run(other, by=ANALYST)
    with pytest.raises(RuleKeyTakenError):
        review.draft_new_rule(other, rule_key=MONTHLY)


def test_a_draft_names_a_known_key_or_a_new_rule_of_the_candidates_regulator(
    review: Review,
) -> None:
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    with pytest.raises(RuleKeyUnknownError):
        review.draft.run(task_id, by=ANALYST, rule_key="example_unknown")
    with pytest.raises(InvariantViolationError, match="of its own regulator"):
        review.draft_new_rule(task_id, new_rule=NewRule("example_state", AttributeLevel.ENTITY))
    with pytest.raises(InvariantViolationError, match="snake_case"):
        review.draft.run(task_id, by=ANALYST, rule_key="Not A Key")
    assert review.read.run(task_id).version is None, "nothing was stored"


def test_edits_are_recorded_with_what_they_changed(review: Review) -> None:
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    detail = review.draft_new_rule(
        task_id,
        edit=DraftEdit({"title": "Example: January's example return is extended"}),
        citations=[CitationInput(clause_id_for(DOC, "en.p2"), QUOTE_EXTENDS)],
        note="one quote is enough",
    )
    (edited,) = detail.decisions
    assert (edited.action, edited.actor_id) == (DecisionAction.EDITED, ANALYST)
    assert edited.note == (
        f"drafted from rule candidate {detail.task.candidate_id}, changed title, citations: "
        "one quote is enough"
    )
    assert [c.clause_ref for c in detail.citations] == ["en.p2"]


def test_an_incomplete_draft_lists_every_problem_and_stores_nothing(review: Review) -> None:
    fields = {
        **FIELDS,
        "effective_from": None,
        "obligation": {**FIELDS["obligation"], "due_in_days": None},
    }
    task_id = review.received(candidate=fields)
    review.claim.run(task_id, by=ANALYST)
    with pytest.raises(DraftIncompleteError) as incomplete:
        review.draft_new_rule(task_id)
    assert incomplete.value.problems == ("effective_from: the candidate gives none",)
    with pytest.raises(DraftIncompleteError, match="needs obligation_template"):
        review.draft_new_rule(task_id, edit=DraftEdit({"effective_from": date(2000, 2, 1)}))
    with review.store() as uow:
        assert uow.rule_versions.lock_rule(EXTENSION) is None
    detail = review.draft_new_rule(
        task_id,
        edit=DraftEdit(
            {
                "effective_from": date(2000, 2, 1),
                "recurrence": {"frequency": "monthly", "due_day": 25, "due_month_offset": 0},
            }
        ),
    )
    assert detail.version is not None
    assert detail.decisions[0].note.endswith("changed recurrence, effective_from")


def test_an_unparseable_candidate_is_drafted_by_hand(review: Review) -> None:
    task_id = review.received(outcome="unparseable", candidate=None, needs_review=True)
    review.claim.run(task_id, by=ANALYST)
    with pytest.raises(DraftIncompleteError, match="the candidate gives none; send it"):
        review.draft_new_rule(task_id)
    detail = review.draft_new_rule(
        task_id,
        edit=DraftEdit(
            {
                "title": "Example rule drafted by hand",
                "specification": SPECIFICATION,
                "obligation_template": {"title": "File the example return", "due_in_days": 5},
                "effective_from": date(2000, 2, 1),
            }
        ),
        citations=[CitationInput(clause_id_for(DOC, "en.p3"), QUOTE_EFFECT)],
    )
    assert detail.version is not None
    assert not detail.version.high_impact
    assert "changed title, specification, obligation_template" in detail.decisions[0].note


def test_only_the_claimant_drafts_once_from_a_candidate_task(review: Review) -> None:
    task_id = review.received()
    with pytest.raises(ReviewTaskNotClaimedError):
        review.draft_new_rule(task_id)
    review.claim.run(task_id, by=ANALYST)
    with pytest.raises(ReviewTaskNotClaimedError):
        review.draft_new_rule(task_id, by=REVIEWER)
    review.draft_new_rule(task_id)
    with pytest.raises(CandidateAlreadyDraftedError):
        review.draft_new_rule(task_id, rule_key="example_other")


def test_a_quote_not_in_its_clause_or_a_relation_of_another_document_stores_nothing(
    review: Review,
) -> None:
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    with pytest.raises(CitationNotVerifiedError):
        review.draft_new_rule(
            task_id, citations=[CitationInput(clause_id_for(DOC, "en.p2"), "Example text absent")]
        )
    with pytest.raises(InvariantViolationError, match="another document"):
        review.draft_new_rule(task_id, relations=[RelationChoice(_other_relation(review))])
    detail = review.read.run(task_id)
    assert detail.version is None
    assert detail.candidate is not None
    assert detail.candidate.candidate.status is RuleCandidateStatus.OPEN
    with review.store() as uow:
        assert uow.rule_versions.lock_rule(EXTENSION) is None


def _other_relation(review: Review) -> UUID:
    digest = hashlib.sha256(b"another example document").hexdigest()
    other = document_id_for(digest)
    text = "Example circular about another example return."
    RegisterDocument(review.store).run(
        StoredDocument(
            document_id=other,
            source_id=SourceId(UUID(int=11)),
            sha256=digest,
            regulator="CBIC",
            doc_type=DocumentType.CIRCULAR,
            url="https://example.invalid/circular.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=START,
        ),
        [Clause("en.p1", text)],
    )
    clause = clause_id_for(other, "en.p1")
    candidate = RelationCandidate(
        candidate_id=uuid4(),
        document_id=other,
        relation=RelationKind.REFERS_TO,
        target_type=EntityType.FORM,
        target_name="example return",
        target_clause_id=clause,
        target_span_start=text.index("example return"),
        target_span_end=text.index("example return") + len("example return"),
        evidence_clause_id=clause,
        evidence_quote=text,
        quote_score=1.0,
        prompt_version="extraction.rule_relations@1",
        confidence=0.9,
        needs_review=False,
    )
    with review.store() as uow:
        uow.candidates.add(candidate)
    return candidate.candidate_id


def test_a_seed_task_is_not_drafted_from_a_candidate(review: Review) -> None:
    review.store.add_rule("example_seed", regulator="cbic", title="Example seed draft")
    (seed,) = review.seed.run().opened
    review.claim.run(seed.task_id, by=ANALYST)
    with pytest.raises(InvariantViolationError, match="is a seed task"):
        review.draft_new_rule(seed.task_id)


# ---------------------------------------------------------------- deciding


def test_a_candidate_task_not_drafted_yet_can_only_be_rejected(review: Review) -> None:
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    for decision in (ReviewDecision.APPROVE, ReviewDecision.RETURN):
        with pytest.raises(CandidateNotDraftedError):
            review.decide.run(task_id, decision, by=REVIEWER, note="example")
    with pytest.raises(CandidateNotDraftedError):
        review.edit.run(task_id, by=ANALYST, edit=DraftEdit({"title": "Example"}))
    with pytest.raises(InvariantViolationError, match="names its reason"):
        review.decide.run(task_id, ReviewDecision.REJECT, by=REVIEWER, note="example")
    decided = review.decide.run(
        task_id,
        ReviewDecision.REJECT,
        by=REVIEWER,
        note="The example notification states no rule",
        reason=RuleRejectReason.NOT_A_RULE,
    )
    assert decided.version is None
    assert decided.task.status is ReviewTaskStatus.DECIDED
    assert decided.candidate is not None
    assert (decided.candidate.status, decided.candidate.reject_reason) == (
        RuleCandidateStatus.REJECTED,
        RuleRejectReason.NOT_A_RULE,
    )
    (event,) = decided.events
    assert review.store.events() == [event]
    assert event.rule_version_id is None
    _matches_its_schema(event)


def test_a_reason_belongs_to_a_candidate_tasks_rejection(review: Review) -> None:
    review.store.add_rule("example_seed", regulator="cbic", title="Example seed draft")
    (seed,) = review.seed.run().opened
    with pytest.raises(InvariantViolationError, match="only a candidate task"):
        review.decide.run(
            seed.task_id,
            ReviewDecision.REJECT,
            by=REVIEWER,
            note="example",
            reason=RuleRejectReason.DUPLICATE,
        )
    with pytest.raises(InvariantViolationError, match="with a rejection"):
        review.decide.run(
            seed.task_id, ReviewDecision.APPROVE, by=REVIEWER, reason=RuleRejectReason.DUPLICATE
        )


def test_a_high_impact_draft_needs_two_approvers_then_the_candidate_is_approved(
    review: Review,
) -> None:
    relation = review.relation()
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    review.draft_new_rule(task_id, relations=[RelationChoice(relation, review.monthly)])
    first = review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER)
    assert first.task.status is ReviewTaskStatus.OPEN, "a second, different reviewer"
    assert first.candidate is not None
    assert first.candidate.status is RuleCandidateStatus.DRAFTED
    second = review.decide.run(task_id, ReviewDecision.APPROVE, by=OTHER_REVIEWER)
    assert second.version is not None
    assert second.version.record.status is RuleVersionStatus.APPROVED
    assert second.candidate is not None
    assert (second.candidate.status, second.candidate.decided_by) == (
        RuleCandidateStatus.APPROVED,
        OTHER_REVIEWER,
    )
    published = review.publish.run(second.version.record.rule_version_id, actor_id=REVIEWER)
    topics = [type(event).topic for event in published.events]
    assert topics == ["rule.published", "rule.deadline_changed"]
    changed = published.events[1]
    assert changed.rule_version_id == review.monthly  # type: ignore[attr-defined]
    stats = review.stats.run().candidates
    assert (stats.approved, stats.approved_without_edits, stats.acceptance_rate) == (1, 1, 1.0)


def test_rejecting_after_drafting_keeps_the_draft_and_names_it(review: Review) -> None:
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    detail = review.draft_new_rule(task_id, edit=DraftEdit({"title": "Example: edited"}))
    assert detail.version is not None
    review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER)
    rejected = review.decide.run(
        task_id,
        ReviewDecision.REJECT,
        by=OTHER_REVIEWER,
        note="The model read the date wrongly",
        reason=RuleRejectReason.WRONG_EXTRACTION,
    )
    assert rejected.version is not None
    assert rejected.version.record.status is RuleVersionStatus.DRAFT, "back from review"
    (event,) = rejected.events
    assert event.rule_version_id == detail.version.rule_version_id
    assert event.reason is RuleRejectReason.WRONG_EXTRACTION
    _matches_its_schema(event)
    stats = review.stats.run()
    assert (stats.candidates.rejected, stats.candidates.acceptance_rate) == (1, 0.0)
    assert review.seed.run().opened == (), "a candidate's draft never gets a seed task"


def test_rejecting_after_drafting_reopens_the_relations_for_a_corrected_draft(
    review: Review,
) -> None:
    relation = review.relation()
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    detail = review.draft_new_rule(task_id, relations=[RelationChoice(relation, review.monthly)])
    assert detail.version is not None
    rejected = review.decide.run(
        task_id,
        ReviewDecision.REJECT,
        by=REVIEWER,
        note="The model read the date wrongly",
        reason=RuleRejectReason.WRONG_EXTRACTION,
    )
    assert rejected.reopened_relations == (relation,)
    assert review.store.rule_relations() == [], "the closed draft carries no relation"
    with review.store() as uow:
        staged = uow.candidates.lock(relation)
    assert staged is not None
    assert (staged.status, staged.decided_by, staged.decided_at) == (CandidateStatus.OPEN, "", None)
    assert staged.note == (
        f"reopened: rule candidate {detail.task.candidate_id} was rejected (wrong_extraction) "
        f"by {REVIEWER}, so its draft {detail.version.rule_version_id} no longer carries this "
        "relation; approve it onto another draft"
    )

    corrected = review.received()
    review.claim.run(corrected, by=ANALYST)
    again = review.draft_new_rule(
        corrected,
        rule_key="example_extension_2000_01_corrected",
        relations=[RelationChoice(relation, review.monthly)],
    )
    assert again.version is not None
    ((rule_relation, candidate_id),) = review.store.rule_relations()
    assert (rule_relation.from_rule_version_id, candidate_id) == (
        again.version.rule_version_id,
        relation,
    )
    review.decide.run(corrected, ReviewDecision.APPROVE, by=REVIEWER)
    approved = review.decide.run(corrected, ReviewDecision.APPROVE, by=OTHER_REVIEWER)
    assert approved.version is not None
    published = review.publish.run(approved.version.record.rule_version_id, actor_id=REVIEWER)
    assert [type(event).topic for event in published.events] == [
        "rule.published",
        "rule.deadline_changed",
    ], "the extension reaches the publication through the corrected draft"


def test_a_rejection_before_drafting_reopens_nothing(review: Review) -> None:
    relation = review.relation()
    task_id = review.received()
    rejected = review.decide.run(
        task_id,
        ReviewDecision.REJECT,
        by=REVIEWER,
        note="The example notification states no rule",
        reason=RuleRejectReason.NOT_A_RULE,
    )
    assert rejected.reopened_relations == ()
    with review.store() as uow:
        staged = uow.candidates.lock(relation)
    assert staged is not None
    assert (staged.status, staged.note) == (CandidateStatus.OPEN, "")


def test_a_rejection_that_fails_leaves_the_relations_approved(
    review: Review, monkeypatch: pytest.MonkeyPatch
) -> None:
    relation = review.relation()
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    review.draft_new_rule(task_id, relations=[RelationChoice(relation, review.monthly)])

    def refused(sink: MemoryEventSink, event: object) -> None:
        raise RuntimeError("the outbox refused the event")

    monkeypatch.setattr(MemoryEventSink, "publish", refused)
    with pytest.raises(RuntimeError, match="outbox refused"):
        review.decide.run(
            task_id,
            ReviewDecision.REJECT,
            by=REVIEWER,
            note="The model read the date wrongly",
            reason=RuleRejectReason.WRONG_EXTRACTION,
        )
    ((_, candidate_id),) = review.store.rule_relations()
    assert candidate_id == relation, "the rejection and the reopening commit together, or neither"
    with review.store() as uow:
        staged = uow.candidates.lock(relation)
    assert staged is not None
    assert staged.status is CandidateStatus.APPROVED


def test_a_published_versions_relations_stand_when_its_candidate_is_rejected(
    review: Review,
) -> None:
    relation = review.relation()
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    detail = review.draft_new_rule(task_id, relations=[RelationChoice(relation, review.monthly)])
    assert detail.version is not None
    version_id = detail.version.rule_version_id
    review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER)
    ApproveVersion(review.store, review.clock).run(version_id, actor_id=OTHER_REVIEWER)
    review.publish.run(version_id, actor_id=REVIEWER)
    rejected = review.decide.run(
        task_id,
        ReviewDecision.REJECT,
        by=REVIEWER,
        note="Published outside the task before this rejection",
        reason=RuleRejectReason.DUPLICATE,
    )
    assert rejected.version is not None
    assert rejected.version.record.status is RuleVersionStatus.PUBLISHED
    assert rejected.reopened_relations == ()
    assert [candidate for _, candidate in review.store.rule_relations()] == [relation]


def test_a_return_opens_the_next_round_for_the_same_candidate(review: Review) -> None:
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    detail = review.draft_new_rule(task_id)
    returned = review.decide.run(
        task_id, ReviewDecision.RETURN, by=REVIEWER, note="Cite the example board's clause"
    )
    assert returned.next_task is not None
    following = returned.next_task
    assert (following.candidate_id, following.rule_version_id, following.kind) == (
        detail.task.candidate_id,
        detail.task.rule_version_id,
        ReviewTaskKind.CANDIDATE,
    )
    review.claim.run(following.task_id, by=ANALYST)
    edited = review.edit.run(following.task_id, by=ANALYST, edit=DraftEdit({"summary": "x"}))
    assert edited.decisions[-1].action is DecisionAction.EDITED
    assert [t.task_id for t in edited.tasks] == [task_id, following.task_id]
    stats = review.stats.run().candidates
    assert (stats.decided, stats.acceptance_rate) == (0, None)


# ---------------------------------------------------------------- reading


def test_the_detail_carries_the_candidate_and_the_draft_it_proposes(review: Review) -> None:
    task_id = review.received(suggested_rule_key="example_quarterly")
    detail = review.read.run(task_id)
    assert detail.version is None
    assert detail.required_approvals == 2, "as the candidate suggests"
    assert [t.task_id for t in detail.tasks] == [task_id]
    candidate = detail.candidate
    assert candidate is not None
    assert candidate.document is not None
    assert candidate.document.document_id == DOC
    assert candidate.proposed.values["specification"] == SPECIFICATION
    assert candidate.high_impact_reasons == ("change_kind is extension",)
    assert not candidate.suggested_rule_known


# ---------------------------------------------------------------- closed drafts


def rejected_after_drafting(review: Review, rule_key: str = EXTENSION, **draft: Any) -> Any:
    """A candidate drafted into ``rule_key`` and then rejected; its draft, now closed."""
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    detail = review.draft.run(task_id, by=ANALYST, rule_key=rule_key, **draft)
    assert detail.version is not None
    review.decide.run(
        task_id,
        ReviewDecision.REJECT,
        by=REVIEWER,
        note="The model read the date wrongly",
        reason=RuleRejectReason.WRONG_EXTRACTION,
    )
    return detail.version


def test_a_rejected_candidates_draft_is_closed_to_every_step(review: Review) -> None:
    relation = review.relation()
    closed = rejected_after_drafting(
        review, new_rule=NewRule("cbic", AttributeLevel.REGISTRATION)
    ).rule_version_id
    steps: dict[str, Callable[[], object]] = {
        "cite": lambda: AddCitations(review.store, review.clock).run(
            closed, [CitationInput(clause_id_for(DOC, "en.p3"), QUOTE_EFFECT)]
        ),
        "submit": lambda: SubmitForReview(review.store, review.clock).run(closed, actor_id=ANALYST),
        "approve": lambda: ApproveVersion(review.store, review.clock).run(
            closed, actor_id=REVIEWER
        ),
        "publish": lambda: review.publish.run(closed, actor_id=REVIEWER),
        "relate": lambda: ApproveRelationCandidate(review.store, review.clock).run(
            relation, closed, review.monthly, decided_by=str(ANALYST)
        ),
    }
    for step, run in steps.items():
        with pytest.raises(RuleVersionClosedError, match=r"was rejected \(wrong_extraction\)"):
            run()
        with review.store() as uow:
            record = uow.rule_versions.get(closed)
        assert record is not None
        assert record.status is RuleVersionStatus.DRAFT, step
    assert review.store.rule_relations() == []


def test_a_closed_draft_is_never_its_rules_latest_version(review: Review) -> None:
    closed = rejected_after_drafting(review, rule_key=MONTHLY)
    assert closed.version == 2
    with review.store() as uow:
        listed = {rule.rule_key: rule.title for rule in uow.rules.list_rules()}
        head = uow.rule_versions.lock_rule(MONTHLY)
    assert listed[MONTHLY] == "Example monthly return", "not the rejected candidate's title"
    assert head is not None
    assert head.last_version == 2, "the closed draft keeps its number"
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    again = review.draft.run(task_id, by=ANALYST, rule_key=MONTHLY)
    assert again.version is not None
    assert again.version.version == 3
    with review.store() as uow:
        listed = {rule.rule_key: rule.title for rule in uow.rules.list_rules()}
    assert listed[MONTHLY] == FIELDS["title"], "an open draft is the latest version"


def test_a_rule_that_only_closed_drafts_hold_is_not_listed(review: Review) -> None:
    rejected_after_drafting(review, new_rule=NewRule("cbic", AttributeLevel.REGISTRATION))
    with review.store() as uow:
        assert EXTENSION not in {rule.rule_key for rule in uow.rules.list_rules()}
        head = uow.rule_versions.lock_rule(EXTENSION)
    assert head is not None, "the rule stays, and its key can be drafted into again"
    task_id = review.received()
    review.claim.run(task_id, by=ANALYST)
    again = review.draft.run(task_id, by=ANALYST, rule_key=EXTENSION)
    assert again.version is not None
    assert again.version.version == 2
    with review.store() as uow:
        assert EXTENSION in {rule.rule_key for rule in uow.rules.list_rules()}


# ---------------------------------------------------------------- seed scoping


def _seed_versions(review: Review, rule_key: str) -> list[tuple[int, str, str, bool]]:
    """(number, status, title, drafted from a candidate) for every version of the rule."""
    with review.store() as uow:
        head = uow.rule_versions.lock_rule(rule_key)
        assert head is not None
        return [
            (record.version, record.status.value, record.title, record.candidate_id is not None)
            for record in uow.rule_versions.of_rule(head.rule_id)
        ]


def _retitled(calendar: SeedCalendar, rule_key: str, title: str) -> SeedCalendar:
    rules = tuple(
        replace(rule, title=title) if rule.rule_key == rule_key else rule for rule in calendar.rules
    )
    return replace(calendar, rules=rules)


def test_the_seed_updates_its_own_draft_beside_a_candidates_draft(review: Review) -> None:
    calendar = load_calendar(ontology_package.load())
    review.store.apply_seed(calendar)
    seeded = calendar.get("gstr1_quarterly")
    task_id = review.received(suggested_rule_key=None)
    review.claim.run(task_id, by=ANALYST)
    drafted = review.draft.run(task_id, by=ANALYST, rule_key=seeded.rule_key)
    assert drafted.version is not None
    assert seeded.rule_key in review.store.apply_seed(calendar).unchanged
    outcome = review.store.apply_seed(_retitled(calendar, seeded.rule_key, "Example: edited"))
    assert outcome.updated_drafts == (f"{seeded.rule_key}@1",)
    assert outcome.kept_edited == ()
    assert _seed_versions(review, seeded.rule_key) == [
        (1, "draft", "Example: edited", False),
        (2, "draft", FIELDS["title"], True),
    ], "the candidate's draft is left as it is"
    opened = review.seed.run().opened
    assert drafted.version.rule_version_id not in {task.rule_version_id for task in opened}


def test_the_seed_leaves_a_candidates_version_after_its_own_alone(review: Review) -> None:
    calendar = load_calendar(ontology_package.load())
    review.store.apply_seed(calendar)
    seeded = "gstr3b_monthly"
    with review.store() as uow:
        head = uow.rule_versions.lock_rule(seeded)
        assert head is not None
        (seed_version,) = uow.rule_versions.of_rule(head.rule_id)
    SubmitForReview(review.store, review.clock).run(seed_version.rule_version_id, actor_id=ANALYST)
    task_id = review.received(suggested_rule_key=None)
    review.claim.run(task_id, by=ANALYST)
    review.draft.run(task_id, by=ANALYST, rule_key=seeded)
    outcome = review.store.apply_seed(_retitled(calendar, seeded, "Example: edited"))
    assert seeded in outcome.kept_edited, "the analyst's draft is the rule's latest version"
    assert [version[:2] for version in _seed_versions(review, seeded)] == [
        (1, "in_review"),
        (2, "draft"),
    ]


def test_a_closed_draft_never_freezes_the_seed(review: Review) -> None:
    calendar = load_calendar(ontology_package.load())
    review.store.apply_seed(calendar)
    seeded = "gstr3b_monthly"
    rejected_after_drafting(review, rule_key=seeded)
    again = review.store.apply_seed(calendar)
    assert seeded in again.unchanged
    assert again.kept_edited == ()
    updated = review.store.apply_seed(_retitled(calendar, seeded, "Example: edited"))
    assert updated.updated_drafts == (f"{seeded}@1",)
    with review.store() as uow:
        head = uow.rule_versions.lock_rule(seeded)
        assert head is not None
        seed_version = uow.rule_versions.of_rule(head.rule_id)[0]
    SubmitForReview(review.store, review.clock).run(seed_version.rule_version_id, actor_id=ANALYST)
    moved = review.store.apply_seed(_retitled(calendar, seeded, "Example: edited again"))
    assert moved.created_versions == (f"{seeded}@3",), "numbered past the closed draft"
    assert [version[:3] for version in _seed_versions(review, seeded)] == [
        (1, "in_review", "Example: edited"),
        (2, "draft", FIELDS["title"]),
        (3, "draft", "Example: edited again"),
    ]


def test_the_seed_numbers_a_rule_past_the_closed_drafts_it_only_has(review: Review) -> None:
    seeded = "gstr3b_monthly"
    rejected_after_drafting(
        review, rule_key=seeded, new_rule=NewRule("cbic", AttributeLevel.REGISTRATION)
    )
    calendar = load_calendar(ontology_package.load())
    outcome = review.store.apply_seed(calendar)
    assert seeded not in outcome.created_rules
    assert f"{seeded}@2" in outcome.created_versions
    with review.store() as uow:
        listed = {rule.rule_key: rule.title for rule in uow.rules.list_rules()}
    assert listed[seeded] == calendar.get(seeded).title


def _matches_its_schema(event: RuleRejected) -> None:
    message = to_message(event)
    schema = json.loads((SCHEMAS / "rule.rejected.v1.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        message.payload
    )
    assert message.tenant_id is None
    assert message.causation_id is not None
