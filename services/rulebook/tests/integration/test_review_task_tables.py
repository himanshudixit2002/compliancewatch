"""Review tasks on Postgres: migration 0009 refusing to go down over a recorded edit (an empty
database goes down and up in test_knowledge_schema.py), the review_task checks, its partial unique
index and its guard trigger, and the use cases on the Postgres unit of work, where a decision
and its version transition commit together (or not at all) and the seed command leaves a draft
an analyst edited. Needs Docker."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import ClauseId, SourceId, UserId
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
from rulebook.domain.errors import DuplicateApproverError, ReviewTaskClosedError
from rulebook.domain.publication import DecisionAction
from rulebook.domain.review_tasks import (
    DraftEdit,
    ReviewDecision,
    ReviewTaskStatus,
    TaskKey,
    queue_position,
)
from rulebook.domain.seed import SeedStatus
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.seed_repository import SqlAlchemySeedRepository

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
START = datetime(2000, 1, 3, 4, 30, tzinfo=UTC)
ANALYST = UserId(UUID(int=41))
REVIEWER = UserId(UUID(int=42))
OTHER_REVIEWER = UserId(UUID(int=43))
TEXT = (
    "Example section 1. Every example person shall furnish the example statement of outward "
    "supplies by the eleventh day of the following month."
)
QUOTE = "shall furnish the example statement of outward supplies by the eleventh day"
MONTHLY = "gstr1_monthly"
QUARTERLY = "gstr1_quarterly"


class Clock:
    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def alembic_config(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        config = Config(str(SERVICE_DIR / "alembic.ini"))
        command.upgrade(config, "head")
        yield config


@pytest.fixture(scope="module")
def factory(
    database_url: str, alembic_config: Config
) -> Iterator[PostgresKnowledgeUnitOfWorkFactory]:
    factory = PostgresKnowledgeUnitOfWorkFactory.from_url(database_url)
    SqlAlchemySeedRepository(factory.engine).apply(load_calendar(ontology_package.load()))
    yield factory
    factory.engine.dispose()


@pytest.fixture(scope="module")
def clause(factory: PostgresKnowledgeUnitOfWorkFactory) -> ClauseId:
    """A synthetic statute an analyst uploaded, registered with one clause."""
    digest = hashlib.sha256(b"example statute on postgres").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(factory).run(
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
        [Clause("en.p1", TEXT)],
    )
    return clause_id_for(document_id, "en.p1")


class Review:
    def __init__(self, factory: PostgresKnowledgeUnitOfWorkFactory, clock: Clock) -> None:
        self.seed = OpenSeedReviewTasks(factory, clock)
        self.list = ListReviewTasks(factory)
        self.claim = ClaimReviewTask(factory, clock)
        self.read = ReadReviewTask(factory)
        self.edit = EditReviewDraft(factory, ontology_package.load, clock)
        self.decide = DecideReviewTask(factory, clock)
        self.stats = ReadReviewStats(factory)
        self.publish = PublishVersion(factory, enabled=True, clock=clock)

    def task_id_of(self, rule_key: str) -> UUID:
        (task_id,) = [
            queued.task.task_id
            for queued in self.list.run(limit=201)
            if queued.rule_key == rule_key and queued.task.undecided
        ]
        return task_id


@pytest.fixture(scope="module")
def review(factory: PostgresKnowledgeUnitOfWorkFactory, clause: ClauseId) -> Review:
    review = Review(factory, Clock())
    assert len(review.seed.run().opened) == 13
    return review


def scalar(engine: Engine, statement: str, **params: object) -> object:
    with engine.connect() as connection:
        return connection.execute(text(statement), params).scalar_one()


def execute(engine: Engine, statement: str, **params: object) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement), params)


def test_seed_tasks_open_once_and_the_queue_pages_in_order(review: Review) -> None:
    assert review.seed.run().opened == (), "a second run opens nothing"
    every = review.list.run(limit=201)
    assert len(every) == 13
    assert [queued.task for queued in every] == sorted(
        (queued.task for queued in every), key=queue_position
    )
    first = review.list.run(limit=4)
    rest = review.list.run(after=TaskKey.of(first[-1].task), limit=201)
    assert [q.task.task_id for q in [*first, *rest]] == [q.task.task_id for q in every]
    assert review.list.run(regulator="gstn") == []
    assert {q.task.regulator for q in every} == {"cbic"}
    assert {(q.version_status, q.approvals) for q in every} == {(RuleVersionStatus.DRAFT, 0)}


def test_one_waiting_task_per_version_and_a_decided_task_never_changes(
    factory: PostgresKnowledgeUnitOfWorkFactory, review: Review
) -> None:
    engine = factory.engine
    task_id = review.task_id_of(QUARTERLY)
    version = scalar(engine, "SELECT rule_version_id FROM review_task WHERE id = :id", id=task_id)
    with pytest.raises(IntegrityError, match="uq_review_task_undecided_version"):
        execute(
            engine,
            "INSERT INTO review_task (id, rule_version_id, kind, priority, regulator)"
            " VALUES (:id, :version, 'seed', 50, 'cbic')",
            id=uuid4(),
            version=version,
        )
    with factory() as uow:
        task = uow.review_tasks.get(task_id)
        assert task is not None
        assert not uow.review_tasks.add(task.next_round(at=START)), "ON CONFLICT DO NOTHING"
    for assignment, constraint in (
        ("status = 'claimed'", "ck_review_task_state"),
        ("decision = 'approve'", "ck_review_task_state"),
        ("claimed_by = gen_random_uuid()", "ck_review_task_claim|ck_review_task_state"),
        ("priority = 1001", "ck_review_task_priority"),
        ("status = 'closed'", "ck_review_task_state|ck_review_task_status"),
    ):
        with pytest.raises(IntegrityError, match=constraint):
            execute(engine, f"UPDATE review_task SET {assignment} WHERE id = :id", id=task_id)
    with pytest.raises(IntegrityError, match="keeps its version, kind, regulator"):
        execute(engine, "UPDATE review_task SET regulator = 'gstn' WHERE id = :id", id=task_id)
    with pytest.raises(IntegrityError, match="never deleted"):
        execute(engine, "DELETE FROM review_task WHERE id = :id", id=task_id)

    rejected = review.decide.run(task_id, ReviewDecision.REJECT, by=REVIEWER, note="example")
    assert rejected.task.status is ReviewTaskStatus.DECIDED
    for statement in (
        "UPDATE review_task SET note = 'changed' WHERE id = :id",
        "UPDATE review_task SET status = 'open', decision = NULL, decided_by = NULL,"
        " decided_at = NULL WHERE id = :id",
        "DELETE FROM review_task WHERE id = :id",
    ):
        with pytest.raises(IntegrityError, match=r"decided task never changes|never deleted"):
            execute(engine, statement, id=task_id)
    with pytest.raises(ReviewTaskClosedError):
        review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER)
    (reopened,) = review.seed.run().opened
    assert str(reopened.rule_version_id) == str(version), "the rejected draft is queued again"


def test_a_claimed_draft_is_edited_cited_and_approved_by_two_people(
    factory: PostgresKnowledgeUnitOfWorkFactory, review: Review, clause: ClauseId
) -> None:
    engine = factory.engine
    task_id = review.task_id_of(MONTHLY)
    review.claim.run(task_id, by=ANALYST)
    detail = review.edit.run(
        task_id,
        by=ANALYST,
        edit=DraftEdit({"title": "File the example statement every month"}),
        citations=[CitationInput(clause, QUOTE)],
        note="the analyst read the example statute",
    )
    assert detail.version.title == "File the example statement every month"
    assert [(c.verified, c.quote) for c in detail.citations] == [(True, QUOTE)]
    assert [d.title for d in detail.documents] == ["Example Act (synthetic)"]
    assert [entry.action for entry in detail.decisions] == [DecisionAction.EDITED]

    first = review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER, high_impact=True)
    assert (first.task.status, first.version.record.status) == (
        ReviewTaskStatus.OPEN,
        RuleVersionStatus.IN_REVIEW,
    )
    (queued,) = [q for q in review.list.run(limit=201) if q.task.task_id == task_id]
    assert (queued.approvals, queued.high_impact) == (1, True)
    with pytest.raises(DuplicateApproverError):
        review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER)
    assert review.read.run(task_id).task == first.task, "the refused approval wrote nothing"
    second = review.decide.run(task_id, ReviewDecision.APPROVE, by=OTHER_REVIEWER)
    assert second.task.status is ReviewTaskStatus.DECIDED
    record = second.version.record
    assert (record.status, record.seed_status) == (RuleVersionStatus.APPROVED, SeedStatus.REVIEWED)
    assert set(second.version.approvers) == {REVIEWER, OTHER_REVIEWER}
    assert scalar(engine, "SELECT count(*) FROM outbox_event") == 0, "approving never publishes"

    published = review.publish.run(record.rule_version_id, actor_id=REVIEWER)
    assert published.plan.published.status is RuleVersionStatus.PUBLISHED, (
        "the guard trigger counts both approvers of the round"
    )
    read = review.read.run(task_id)
    assert [entry.action for entry in read.decisions] == [
        DecisionAction.EDITED,
        DecisionAction.SUBMITTED,
        DecisionAction.APPROVED,
        DecisionAction.APPROVED,
        DecisionAction.PUBLISHED,
    ]


def test_a_return_commits_with_its_version_and_opens_the_next_task(review: Review) -> None:
    task_id = review.task_id_of("cmp08_quarterly")
    first = review.decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER, high_impact=True)
    assert first.version.record.status is RuleVersionStatus.IN_REVIEW
    returned = review.decide.run(task_id, ReviewDecision.RETURN, by=OTHER_REVIEWER, note="rework")
    assert returned.version.record.status is RuleVersionStatus.DRAFT
    assert returned.next_task is not None
    detail = review.read.run(returned.next_task.task_id)
    assert [task.status for task in detail.tasks] == [
        ReviewTaskStatus.DECIDED,
        ReviewTaskStatus.OPEN,
    ]
    assert [entry.action for entry in detail.decisions] == [
        DecisionAction.SUBMITTED,
        DecisionAction.APPROVED,
        DecisionAction.RETURNED,
    ]
    assert detail.approvers == ()


def test_the_stats_are_read_in_sql(review: Review) -> None:
    stats = review.stats.run()
    counts = stats.counts()
    assert counts[ReviewTaskStatus.DECIDED] >= 1
    assert counts[ReviewTaskStatus.OPEN] + counts[ReviewTaskStatus.CLAIMED] >= 1
    assert stats.median_seconds_to_decide is not None
    assert stats.median_seconds_to_decide > 0
    assert stats.oldest_open_at is not None
    assert stats.oldest_open_at.tzinfo is not None
    assert [row.regulator for row in stats.by_regulator] == ["cbic"]


def test_the_seed_leaves_a_draft_an_analyst_edited(
    factory: PostgresKnowledgeUnitOfWorkFactory, review: Review
) -> None:
    task_id = review.task_id_of("gstr4_annual")
    review.claim.run(task_id, by=ANALYST)
    review.edit.run(task_id, by=ANALYST, edit=DraftEdit({"title": "Edited in review"}))
    outcome = SqlAlchemySeedRepository(factory.engine).apply(load_calendar(ontology_package.load()))
    assert "gstr4_annual" in outcome.kept_edited
    assert MONTHLY in outcome.kept_edited, "an edited version that was published is kept too"
    assert review.read.run(task_id).version.title == "Edited in review"


def test_migration_0009_goes_down_only_while_no_edit_is_recorded(
    alembic_config: Config, database_url: str
) -> None:
    """Last in this module: it takes the tables away and back."""
    engine = create_engine(database_url)
    try:
        with pytest.raises(IntegrityError, match="ck_rule_version_decision_action"):
            command.downgrade(alembic_config, "0008")
        assert scalar(engine, "SELECT version_num FROM alembic_version") == "0009"
        assert scalar(engine, "SELECT count(*) > 0 FROM review_task") is True, "nothing dropped"
    finally:
        engine.dispose()
