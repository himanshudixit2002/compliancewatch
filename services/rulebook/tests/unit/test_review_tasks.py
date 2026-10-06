"""Review tasks on the memory store: the task's own rules, the queue, seed tasks opened once per
draft, a claim, a draft edited and cited, and the decisions with the two-person rule, each in one
transaction with the version's transition."""

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

import ontology as ontology_package
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvalidTransitionError, InvariantViolationError
from domain_kernel.ids import ClauseId, RuleVersionId, SourceId, UserId
from domain_kernel.ontology import Ontology
from domain_kernel.status import RuleVersionStatus
from rulebook.application.documents import RegisterDocument
from rulebook.application.publication import CitationInput, PublishVersion
from rulebook.application.review_tasks import (
    ClaimReviewTask,
    DecideReviewTask,
    EditReviewDraft,
    ListReviewTasks,
    OpenSeedReviewTasks,
    ReadReviewStats,
    ReadReviewTask,
)
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import (
    CitationNotVerifiedError,
    DuplicateApproverError,
    ReviewTaskClaimedError,
    ReviewTaskClosedError,
    ReviewTaskNotClaimedError,
    ReviewTaskNotFoundError,
    RuleVersionNotEditableError,
)
from rulebook.domain.publication import DecisionAction
from rulebook.domain.review_tasks import (
    SEED_PRIORITY,
    DraftEdit,
    ReviewDecision,
    ReviewTask,
    ReviewTaskKind,
    ReviewTaskStatus,
    TaskKey,
    TaskQuery,
    describe_specification,
    edited_record,
    queue_position,
    task_stats,
)
from rulebook.domain.seed import SeedStatus
from rulebook.infrastructure.memory import MemoryKnowledgeStore

START = datetime(2000, 1, 3, 4, 30, tzinfo=UTC)
ANALYST = UserId(UUID(int=21))
REVIEWER = UserId(UUID(int=22))
OTHER_REVIEWER = UserId(UUID(int=23))
CLAUSE_TEXT = (
    "Example section 1. Every example person shall furnish the example statement of outward "
    "supplies by the eleventh day of the following month."
)
QUOTE = "shall furnish the example statement of outward supplies by the eleventh day"
MONTHLY = "gstr1_monthly"
SPECIFICATION = {
    "all_of": [
        {"attribute": "registration_type", "operator": "eq", "value": "regular"},
        {"attribute": "filing_scheme", "operator": "eq", "value": "regular_monthly"},
    ]
}


class Clock:
    """Moves one minute on every reading, so every step has its own time."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> MemoryKnowledgeStore:
    """The seed calendar's thirteen drafts and a synthetic statute to cite."""
    memory = MemoryKnowledgeStore(clock)
    memory.apply_seed(load_calendar(ontology_package.load()))
    return memory


class Review:
    """The use cases on one store and one clock."""

    def __init__(self, store: MemoryKnowledgeStore, clock: Clock, ontology: Ontology) -> None:
        self.store = store
        self.seed = OpenSeedReviewTasks(store, clock)
        self.list = ListReviewTasks(store)
        self.claim = ClaimReviewTask(store, clock)
        self.read = ReadReviewTask(store)
        self.edit = EditReviewDraft(store, lambda: ontology, clock)
        self.decide = DecideReviewTask(store, clock)
        self.stats = ReadReviewStats(store)
        self.publish = PublishVersion(store, enabled=True, clock=clock)

    def task_of(self, rule_key: str) -> ReviewTask:
        """The rule's task that waits for a decision, claimed or not."""
        (task,) = [
            queued.task
            for queued in self.list.run(limit=201)
            if queued.rule_key == rule_key and queued.task.undecided
        ]
        return task


@pytest.fixture
def review(store: MemoryKnowledgeStore, clock: Clock, ontology: Ontology) -> Review:
    return Review(store, clock, ontology)


def statute(store: MemoryKnowledgeStore) -> ClauseId:
    """A synthetic statute an analyst uploaded, registered with one clause."""
    digest = hashlib.sha256(b"example statute for review tasks").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=9)),
            sha256=digest,
            regulator="cbic",
            doc_type=DocumentType.STATUTE,
            url="upload://cgst_act/example",
            language="en",
            media_type="text/html",
            parser_version="html@1",
            fetched_at=START,
            title="Example Act (synthetic)",
            published_at=date(2000, 1, 1),
        ),
        [Clause("en.p1", CLAUSE_TEXT)],
    )
    return clause_id_for(document_id, "en.p1")


def version_of(store: MemoryKnowledgeStore, task: ReviewTask) -> Any:
    with store() as uow:
        return uow.rule_versions.get(task.rule_version_id)


# ---------------------------------------------------------------- the task itself


def task(**overrides: Any) -> ReviewTask:
    values: dict[str, Any] = {
        "task_id": uuid4(),
        "rule_version_id": RuleVersionId.new(),
        "kind": ReviewTaskKind.SEED,
        "priority": SEED_PRIORITY,
        "regulator": "cbic",
        "opened_at": START,
    }
    return ReviewTask(**{**values, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"claimed_by": ANALYST},
        {"status": ReviewTaskStatus.OPEN, "claimed_by": ANALYST, "claimed_at": START},
        {"status": ReviewTaskStatus.CLAIMED},
        {"status": ReviewTaskStatus.DECIDED},
        {"decision": ReviewDecision.APPROVE},
        {"priority": -1},
        {"priority": 1_001},
        {"regulator": " "},
        {"opened_at": datetime(2000, 1, 1)},
    ],
)
def test_a_task_keeps_its_state_consistent(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvariantViolationError):
        task(**overrides)


def test_a_task_is_claimed_once_released_and_decided_once() -> None:
    opened = task()
    claimed = opened.claim(ANALYST, START)
    assert (claimed.status, claimed.claimed_by, claimed.claimed_at) == (
        ReviewTaskStatus.CLAIMED,
        ANALYST,
        START,
    )
    assert claimed.claim(ANALYST, START + timedelta(hours=1)) is claimed, "the claimant again"
    with pytest.raises(ReviewTaskClaimedError):
        claimed.claim(REVIEWER, START)
    claimed.require_claimant(ANALYST)
    with pytest.raises(ReviewTaskNotClaimedError):
        claimed.require_claimant(REVIEWER)
    with pytest.raises(ReviewTaskNotClaimedError):
        opened.require_claimant(ANALYST)
    released = claimed.release()
    assert (released.status, released.claimed_by) == (ReviewTaskStatus.OPEN, None)
    decided = claimed.decide(ReviewDecision.REJECT, by=REVIEWER, at=START, note="not a rule")
    assert (decided.status, decided.decision, decided.decided_by, decided.claimed_by) == (
        ReviewTaskStatus.DECIDED,
        ReviewDecision.REJECT,
        REVIEWER,
        ANALYST,
    )
    for change in (
        lambda: decided.decide(ReviewDecision.APPROVE, by=REVIEWER, at=START),
        lambda: decided.claim(ANALYST, START),
        decided.release,
        lambda: decided.require_claimant(ANALYST),
    ):
        with pytest.raises(ReviewTaskClosedError):
            change()
    following = decided.next_round(at=START + timedelta(days=1))
    assert (following.rule_version_id, following.kind, following.status) == (
        decided.rule_version_id,
        ReviewTaskKind.SEED,
        ReviewTaskStatus.OPEN,
    )
    assert following.task_id != decided.task_id


def test_the_queue_orders_by_regulator_then_priority_then_age() -> None:
    later = START + timedelta(hours=1)
    first, second, third, fourth = (
        task(regulator="cbic", priority=80, opened_at=later),
        task(regulator="cbic", priority=50, opened_at=START),
        task(regulator="cbic", priority=50, opened_at=later),
        task(regulator="gstn", priority=100, opened_at=START),
    )
    assert sorted([fourth, third, first, second], key=queue_position) == [
        first,
        second,
        third,
        fourth,
    ]
    after = TaskQuery(after=TaskKey.of(second))
    assert [t for t in (first, second, third, fourth) if after.admits(t)] == [third, fourth]
    assert TaskQuery(regulator="gstn").admits(fourth)
    assert not TaskQuery(status=ReviewTaskStatus.DECIDED).admits(first)
    with pytest.raises(InvariantViolationError):
        TaskQuery(limit=0)


def test_stats_count_decisions_the_median_wait_and_the_oldest_waiting() -> None:
    decided = [
        task(opened_at=START).decide(
            ReviewDecision.APPROVE, by=REVIEWER, at=START + timedelta(minutes=minutes)
        )
        for minutes in (10, 30)
    ]
    waiting = [
        task(opened_at=START + timedelta(hours=2)),
        task(regulator="gstn", opened_at=START + timedelta(hours=1)).claim(ANALYST, START),
    ]
    stats = task_stats([*decided, *waiting])
    assert stats.counts() == {
        ReviewTaskStatus.OPEN: 1,
        ReviewTaskStatus.CLAIMED: 1,
        ReviewTaskStatus.DECIDED: 2,
    }
    assert stats.decision_counts() == {
        ReviewDecision.APPROVE: 2,
        ReviewDecision.RETURN: 0,
        ReviewDecision.REJECT: 0,
    }
    assert stats.median_seconds_to_decide == 1_200.0
    assert stats.oldest_open_at == START + timedelta(hours=1)
    assert stats.open_by_regulator() == {"cbic": 1, "gstn": 1}
    assert stats.oldest_open_age_seconds(START + timedelta(hours=2)) == 3_600.0
    empty = task_stats([])
    assert (empty.median_seconds_to_decide, empty.oldest_open_age_seconds(START)) == (None, 0.0)


def test_a_specification_is_described_line_by_line() -> None:
    described = describe_specification(
        {
            "all_of": [
                {"attribute": "registration_type", "operator": "eq", "value": "regular"},
                {
                    "any_of": [
                        {"attribute": "state_codes", "operator": "contains", "value": "29"},
                        {"not": {"attribute": "makes_inter_state_supplies", "free_text": "x"}},
                    ]
                },
            ]
        }
    )
    assert described == (
        "all of:",
        "  registration_type = regular",
        "  any of:",
        "    state_codes contains 29",
        "    not:",
        '      free text: "x"',
    )
    assert describe_specification({"all_of": []}) == ("all of: nothing (always applies)",)
    assert describe_specification({"nonsense": 1})[0].startswith("unreadable specification")


def test_a_draft_edit_is_checked_like_the_seed_calendar(
    store: MemoryKnowledgeStore, review: Review, ontology: Ontology
) -> None:
    review.seed.run()
    record = version_of(store, review.task_of(MONTHLY))
    edited, changed = edited_record(
        record, DraftEdit({"title": "File the example return", "summary": record.summary}), ontology
    )
    assert (edited.title, changed) == ("File the example return", ("title",))
    unknown = {"attribute": "no_such_attribute", "operator": "eq", "value": "x"}
    with pytest.raises(InvariantViolationError, match="no_such_attribute"):
        edited_record(record, DraftEdit({"specification": unknown}), ontology)
    free_text = {"attribute": "no_such_attribute", "free_text": "Example judgement"}
    with pytest.raises(InvariantViolationError, match="needs an open question"):
        edited_record(record, DraftEdit({"specification": free_text, "todo": []}), ontology)
    kept, _ = edited_record(record, DraftEdit({"specification": free_text}), ontology)
    assert kept.todo == record.todo, "an open question lets a free-text predicate name it"
    with pytest.raises(InvariantViolationError, match="due_in_days"):
        edited_record(record, DraftEdit({"recurrence": None}), ontology)
    with pytest.raises(InvariantViolationError, match="effective_to"):
        edited_record(record, DraftEdit({"effective_to": record.effective_from}), ontology)
    with pytest.raises(InvariantViolationError, match="cannot be null"):
        DraftEdit({"title": None})
    with pytest.raises(InvariantViolationError, match="cannot change"):
        DraftEdit({"rule_key": "x"})
    problems = "title: title must not be blank; obligation_template"
    with pytest.raises(InvariantViolationError, match=problems):
        edited_record(record, DraftEdit({"title": " ", "obligation_template": {}}), ontology)


# ---------------------------------------------------------------- the memory table


def test_one_waiting_task_per_version_and_a_decided_task_never_changes(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    review.seed.run()
    first = review.task_of(MONTHLY)
    with store() as uow:
        assert not uow.review_tasks.add(first.next_round(at=START)), "one waiting per version"
        decided = first.decide(ReviewDecision.REJECT, by=REVIEWER, at=START, note="example")
        uow.review_tasks.save(decided)
        assert uow.review_tasks.add(first.next_round(at=START)), "the next once it is decided"
        with pytest.raises(ReviewTaskClosedError):
            uow.review_tasks.save(decided)
        with pytest.raises(ReviewTaskClosedError):
            uow.review_tasks.save(first.claim(ANALYST, START))
    with store() as uow:
        waiting = [t for t in uow.review_tasks.of_version(first.rule_version_id) if t.undecided]
        (following,) = waiting
        with pytest.raises(InvariantViolationError, match="keeps its version"):
            uow.review_tasks.save(replace(following, regulator="other"))


# ---------------------------------------------------------------- seed tasks


def test_seed_tasks_open_once_per_draft_that_needs_review(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    opened = review.seed.run().opened
    assert len(opened) == 13
    assert {t.kind for t in opened} == {ReviewTaskKind.SEED}
    assert {t.priority for t in opened} == {SEED_PRIORITY}
    assert {t.regulator for t in opened} == {"cbic"}
    assert review.seed.run().opened == (), "a second run opens nothing"
    claimed = review.claim.run(review.task_of(MONTHLY).task_id, by=ANALYST)
    assert review.seed.run().opened == (), "a claimed task still waits"
    assert len(store.review_tasks()) == 13
    assert claimed.status is ReviewTaskStatus.CLAIMED


def test_the_queue_pages_by_regulator_priority_and_age(review: Review) -> None:
    review.seed.run()
    every = review.list.run(limit=201)
    assert len(every) == 13
    assert [queued.task for queued in every] == sorted(
        (queued.task for queued in every), key=queue_position
    )
    first = review.list.run(limit=5)
    rest = review.list.run(after=TaskKey.of(first[-1].task), limit=201)
    assert [q.task.task_id for q in [*first, *rest]] == [q.task.task_id for q in every]
    assert review.list.run(regulator="gstn") == []
    assert review.list.run(status=ReviewTaskStatus.CLAIMED) == []
    queued = every[0]
    assert (queued.version_status, queued.approvals, queued.high_impact) == (
        RuleVersionStatus.DRAFT,
        0,
        False,
    )


# ---------------------------------------------------------------- claim and edit


def test_the_claimant_edits_the_draft_and_cites_a_statute(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    clause = statute(store)
    review.seed.run()
    task_id = review.task_of(MONTHLY).task_id
    with pytest.raises(ReviewTaskNotClaimedError):
        review.edit.run(task_id, by=ANALYST, citations=[CitationInput(clause, QUOTE)])
    review.claim.run(task_id, by=ANALYST)
    with pytest.raises(ReviewTaskClaimedError):
        review.claim.run(task_id, by=REVIEWER)
    with pytest.raises(ReviewTaskNotClaimedError):
        review.edit.run(task_id, by=REVIEWER, edit=DraftEdit({"title": "x"}))
    with pytest.raises(CitationNotVerifiedError):
        review.edit.run(
            task_id,
            by=ANALYST,
            edit=DraftEdit({"title": "File the example statement"}),
            citations=[CitationInput(clause, "a quote the example clause does not hold at all")],
        )
    assert version_of(store, review.task_of(MONTHLY)).title != "File the example statement", (
        "a refused citation stores nothing of the edit"
    )
    with pytest.raises(InvariantViolationError, match="changes the content or cites"):
        review.edit.run(task_id, by=ANALYST)

    detail = review.edit.run(
        task_id,
        by=ANALYST,
        edit=DraftEdit(
            {"title": "File the example statement every month", "specification": SPECIFICATION}
        ),
        citations=[CitationInput(clause, QUOTE)],
        note="the analyst read the example statute",
    )
    assert detail.version.title == "File the example statement every month"
    assert detail.version.status is RuleVersionStatus.DRAFT
    (citation,) = detail.citations
    assert (citation.verified, citation.match_score, citation.quote) == (True, 1.0, QUOTE)
    assert [d.title for d in detail.documents] == ["Example Act (synthetic)"]
    assert detail.specification_described == (
        "all of:",
        "  registration_type = regular",
        "  filing_scheme = regular_monthly",
    )
    (edited,) = detail.decisions
    assert (edited.action, edited.actor_id, edited.from_status, edited.to_status) == (
        DecisionAction.EDITED,
        ANALYST,
        RuleVersionStatus.DRAFT,
        RuleVersionStatus.DRAFT,
    )
    assert edited.note == "changed title; cited 1 clause: the analyst read the example statute"
    again = review.edit.run(task_id, by=ANALYST, citations=[CitationInput(clause, QUOTE)])
    assert len(again.decisions) == 1, "citing the same quote again changes nothing"


def test_the_seed_leaves_a_draft_an_analyst_edited(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    review.seed.run()
    task_id = review.task_of(MONTHLY).task_id
    review.claim.run(task_id, by=ANALYST)
    review.edit.run(task_id, by=ANALYST, edit=DraftEdit({"title": "Edited in review"}))
    outcome = store.apply_seed(load_calendar(ontology_package.load()))
    assert outcome.kept_edited == (MONTHLY,)
    assert outcome.summary.endswith(", 1 kept as analysts edited them")
    assert version_of(store, review.task_of(MONTHLY)).title == "Edited in review"


# ---------------------------------------------------------------- decisions


def cited(store: MemoryKnowledgeStore, review: Review, rule_key: str = MONTHLY) -> UUID:
    clause = statute(store)
    review.seed.run()
    task_id = review.task_of(rule_key).task_id
    review.claim.run(task_id, by=ANALYST)
    review.edit.run(task_id, by=ANALYST, citations=[CitationInput(clause, QUOTE)])
    return task_id


def test_one_approval_approves_a_version_and_decides_its_task(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    task_id = cited(store, review)
    decided = review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER, note="checked")
    assert decided.task.status is ReviewTaskStatus.DECIDED
    assert (decided.task.decision, decided.task.decided_by) == (ReviewDecision.APPROVE, REVIEWER)
    record = decided.version.record
    assert (record.status, record.seed_status) == (RuleVersionStatus.APPROVED, SeedStatus.REVIEWED)
    assert decided.version.approvers == (REVIEWER,)
    actions = [d.action for d in store.decisions(record.rule_version_id)]
    assert actions == [DecisionAction.EDITED, DecisionAction.SUBMITTED, DecisionAction.APPROVED]
    assert store.events() == [], "approving never publishes"
    with pytest.raises(ReviewTaskClosedError):
        review.decide.run(task_id, ReviewDecision.APPROVE, by=OTHER_REVIEWER)
    assert review.seed.run().opened == (), "an approved version is no draft"


def test_a_high_impact_version_needs_two_distinct_approvers(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    task_id = cited(store, review)
    first = review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER, high_impact=True)
    assert first.version.record.status is RuleVersionStatus.IN_REVIEW
    assert first.version.record.high_impact
    assert (first.task.status, first.task.claimed_by) == (ReviewTaskStatus.OPEN, None), (
        "open again for a second reviewer"
    )
    (queued,) = [q for q in review.list.run(limit=201) if q.task.task_id == task_id]
    assert (queued.approvals, queued.version_status) == (1, RuleVersionStatus.IN_REVIEW)

    with pytest.raises(DuplicateApproverError):
        review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER)
    assert len(store.decisions(first.version.record.rule_version_id)) == 3, (
        "the refused approval wrote nothing"
    )
    assert review.read.run(task_id).task == first.task
    second = review.decide.run(task_id, ReviewDecision.APPROVE, by=OTHER_REVIEWER)
    assert second.task.status is ReviewTaskStatus.DECIDED
    assert second.version.record.status is RuleVersionStatus.APPROVED
    assert set(second.version.approvers) == {REVIEWER, OTHER_REVIEWER}

    published = review.publish.run(second.version.record.rule_version_id, actor_id=REVIEWER)
    assert published.plan.published.status is RuleVersionStatus.PUBLISHED
    assert set(published.plan.approved_by) == {REVIEWER, OTHER_REVIEWER}


def test_a_return_sends_the_version_back_and_opens_the_next_task(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    task_id = cited(store, review)
    review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER, high_impact=True)
    with pytest.raises(InvariantViolationError, match="says why"):
        review.decide.run(task_id, ReviewDecision.RETURN, by=OTHER_REVIEWER)
    with pytest.raises(InvariantViolationError, match="with an approval"):
        review.decide.run(
            task_id, ReviewDecision.REJECT, by=OTHER_REVIEWER, note="x", high_impact=True
        )
    returned = review.decide.run(
        task_id, ReviewDecision.RETURN, by=OTHER_REVIEWER, note="the quote is too short"
    )
    record = returned.version.record
    assert (record.status, record.submitted_at, record.seed_status) == (
        RuleVersionStatus.DRAFT,
        None,
        SeedStatus.NEEDS_REVIEW,
    )
    assert returned.task.decision is ReviewDecision.RETURN
    assert returned.next_task is not None
    assert returned.next_task.status is ReviewTaskStatus.OPEN
    detail = review.read.run(returned.next_task.task_id)
    assert [t.status for t in detail.tasks] == [ReviewTaskStatus.DECIDED, ReviewTaskStatus.OPEN]
    assert detail.approvers == ()
    assert [d.action for d in detail.decisions][-1] is DecisionAction.RETURNED
    again = review.decide.run(
        returned.next_task.task_id, ReviewDecision.RETURN, by=REVIEWER, note="still a draft"
    )
    assert again.version.record.status is RuleVersionStatus.DRAFT, "a draft stays a draft"
    assert again.next_task is not None


def test_a_rejection_closes_the_task_and_leaves_the_draft(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    review.seed.run()
    task_id = review.task_of(MONTHLY).task_id
    rejected = review.decide.run(task_id, ReviewDecision.REJECT, by=REVIEWER, note="not yet")
    assert (rejected.task.decision, rejected.next_task) == (ReviewDecision.REJECT, None)
    assert rejected.version.record.status is RuleVersionStatus.DRAFT
    assert store.decisions(rejected.version.record.rule_version_id) == []
    (reopened,) = review.seed.run().opened
    assert reopened.rule_version_id == rejected.task.rule_version_id, (
        "the next seed request opens a new task for the rejected draft"
    )


def test_a_task_whose_version_moved_on_is_closed_by_a_rejection(
    store: MemoryKnowledgeStore, review: Review
) -> None:
    """The publish routes approved the version outside the task: an approval is refused and
    changes nothing, a rejection closes the task and sends the version back to draft."""
    task_id = cited(store, review)
    claimed = review.read.run(task_id).task
    record = version_of(store, claimed)
    with store() as uow:
        submitted = replace(record, status=RuleVersionStatus.IN_REVIEW, submitted_at=START)
        uow.rule_versions.save_lifecycle(submitted)
        uow.rule_versions.save_lifecycle(replace(submitted, status=RuleVersionStatus.APPROVED))
    with pytest.raises(InvalidTransitionError):
        review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER)
    assert review.read.run(task_id).task == claimed, "a refused decision leaves the task"
    assert version_of(store, claimed).status is RuleVersionStatus.APPROVED
    rejected = review.decide.run(task_id, ReviewDecision.REJECT, by=REVIEWER, note="moved on")
    assert rejected.version.record.status is RuleVersionStatus.DRAFT
    assert rejected.task.status is ReviewTaskStatus.DECIDED


def test_editing_needs_a_draft(store: MemoryKnowledgeStore, review: Review) -> None:
    task_id = cited(store, review)
    review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER, high_impact=True)
    review.claim.run(task_id, by=ANALYST)
    with pytest.raises(RuleVersionNotEditableError):
        review.edit.run(task_id, by=ANALYST, edit=DraftEdit({"title": "Too late"}))


def test_unknown_tasks_are_not_found(review: Review) -> None:
    unknown = uuid4()
    for call in (
        lambda: review.read.run(unknown),
        lambda: review.claim.run(unknown, by=ANALYST),
        lambda: review.edit.run(unknown, by=ANALYST, edit=DraftEdit({"title": "x"})),
        lambda: review.decide.run(unknown, ReviewDecision.APPROVE, by=REVIEWER),
    ):
        with pytest.raises(ReviewTaskNotFoundError):
            call()


def test_the_stats_follow_the_queue(store: MemoryKnowledgeStore, review: Review) -> None:
    task_id = cited(store, review)
    review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER, note="checked")
    stats = review.stats.run()
    assert stats.counts() == {
        ReviewTaskStatus.OPEN: 12,
        ReviewTaskStatus.CLAIMED: 0,
        ReviewTaskStatus.DECIDED: 1,
    }
    assert stats.decision_counts()[ReviewDecision.APPROVE] == 1
    assert stats.median_seconds_to_decide is not None
    assert stats.median_seconds_to_decide > 0
    assert stats.oldest_open_at is not None
    assert stats.open_by_regulator() == {"cbic": 12}
