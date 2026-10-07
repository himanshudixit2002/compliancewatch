"""Rule candidates on Postgres: migration 0010 over seed tasks stored before it (up, down and up,
and no way down once a candidate is stored), the checks of rule_candidate and of candidate review
tasks, the guard that lets a candidate task take its version once, migration 0011's keys tying a
candidate's draft to its candidate and its task, the intake, drafting and decisions on the
Postgres unit of work (with rule.rejected in the outbox, and a rejection after drafting that
reopens the draft's relations and closes it), the seed command (which updates its own draft
beside a candidate's, skips a closed one, and waits for a draft holding the rule) and seed tasks
leaving a candidate's draft alone, and the worker's consumer, whose candidate, task and inbox row
commit together or not at all. Needs Docker."""

import hashlib
import json
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import RuleVersionId, SourceId, UserId
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.ontology import AttributeLevel
from py_common.audit.testing import install_audit_table
from py_common.events import EventMessage, encode
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    sync_handler,
)
from py_common.outbox.testing import FakeProducer
from rulebook import worker
from rulebook.application.documents import RegisterDocument
from rulebook.application.golden_export import ExportDecidedCandidates
from rulebook.application.intake import IngestRuleCandidate
from rulebook.application.publication import SubmitForReview
from rulebook.application.review_tasks import (
    ClaimReviewTask,
    DecideReviewTask,
    DraftFromCandidate,
    NewRule,
    OpenSeedReviewTasks,
    ReadReviewStats,
    RelationChoice,
)
from rulebook.application.rule_versions import ListRuleVersions
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.documents import StoredDocument
from rulebook.domain.errors import RuleVersionClosedError
from rulebook.domain.events import RuleRejected
from rulebook.domain.intake import RuleCandidateStatus, RuleRejectReason
from rulebook.domain.relations import RelationCandidate
from rulebook.domain.review_tasks import ReviewDecision, ReviewTaskStatus
from rulebook.domain.seed import SeedCalendar, SeedOutcome
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.seed_repository import SqlAlchemySeedRepository

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
START = datetime(2000, 1, 3, 4, 30, tzinfo=UTC)
ANALYST = UserId(UUID(int=81))
REVIEWER = UserId(UUID(int=82))
OTHER_REVIEWER = UserId(UUID(int=83))
DIGEST = hashlib.sha256(b"example notification for candidates on postgres").hexdigest()
DOC = document_id_for(DIGEST)
TEXT_EXTENDS = (
    "The example board extends the due date for furnishing the example return for the month "
    "of January, 2000 till the twenty-fifth day of February, 2000."
)
TEXT_EFFECT = "This example notification shall come into effect from 1st February, 2000."
QUOTE_EXTENDS = "extends the due date for furnishing the example return for the month of January"
QUOTE_EFFECT = "shall come into effect from 1st February, 2000"
MONTHLY = "gstr3b_monthly"
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
        }
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
        with admin.begin() as connection:
            install_audit_table(connection)
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def alembic_config(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        yield Config(str(SERVICE_DIR / "alembic.ini"))


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


def scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar()


def execute(engine: Engine, sql: str, **params: Any) -> None:
    with engine.begin() as connection:
        connection.execute(text(sql), params)


BEFORE_0010 = UUID(int=91), UUID(int=92), UUID(int=93)
"""A rule and two of its drafts stored before 0010, each with a seed task, one claimed."""


@pytest.fixture(scope="module")
def seeded(alembic_config: Config, engine: Engine) -> PostgresKnowledgeUnitOfWorkFactory:
    """Seed tasks written at 0009, as the shared dev database holds them (one open, one
    claimed), the schema then migrated to 0010, and the seed calendar's drafts with their tasks."""
    command.upgrade(alembic_config, "0009")
    rule, open_draft, claimed_draft = BEFORE_0010
    execute(
        engine,
        "INSERT INTO rule (id, rule_key, regulator, level)"
        " VALUES (:id, 'example_before_0010', 'cbic', 'registration')",
        id=rule,
    )
    for number, version in enumerate((open_draft, claimed_draft), start=1):
        execute(
            engine,
            "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
            " obligation_template, effective_from) VALUES (:id, :rule, :number, 'draft',"
            " 'Example draft before 0010', '{}', '{}', DATE '2000-01-01')",
            id=version,
            rule=rule,
            number=number,
        )
    execute(
        engine,
        "INSERT INTO review_task (id, rule_version_id, kind, priority, regulator, opened_at)"
        " VALUES (:open_task, :open_draft, 'seed', 50, 'cbic', :at),"
        " (:claimed_task, :claimed_draft, 'seed', 50, 'cbic', :at)",
        open_task=uuid4(),
        open_draft=open_draft,
        claimed_task=uuid4(),
        claimed_draft=claimed_draft,
        at=START,
    )
    execute(
        engine,
        "UPDATE review_task SET status = 'claimed', claimed_by = :analyst, claimed_at = :at"
        " WHERE rule_version_id = :draft",
        analyst=ANALYST.value,
        at=START,
        draft=claimed_draft,
    )
    command.upgrade(alembic_config, "head")
    factory = PostgresKnowledgeUnitOfWorkFactory(engine)
    SqlAlchemySeedRepository(engine).apply(load_calendar(ontology_package.load()))
    assert len(OpenSeedReviewTasks(factory, Clock()).run().opened) == 13
    return factory


@pytest.fixture(scope="module")
def notification(seeded: PostgresKnowledgeUnitOfWorkFactory) -> PostgresKnowledgeUnitOfWorkFactory:
    RegisterDocument(seeded).run(
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
        [
            Clause("en.p1", "Example notification No. 01/2000 of the example board."),
            Clause("en.p2", TEXT_EXTENDS),
            Clause("en.p3", TEXT_EFFECT),
        ],
    )
    return seeded


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
        "suggested_rule_key": "gstr3b_monthly",
        "clause_ids": [str(clause_id_for(DOC, ref)) for ref in ("en.p2", "en.p3")],
    }
    values.update(overrides)
    return values


def test_migration_0010_keeps_the_seed_tasks_and_goes_down_and_up(
    seeded: PostgresKnowledgeUnitOfWorkFactory, alembic_config: Config, engine: Engine
) -> None:
    """First in this module: before any candidate is stored, so the way down is open."""
    statuses = (
        "SELECT rule_version_id, status, claimed_by FROM review_task"
        " WHERE rule_version_id IN (:open, :claimed) ORDER BY status"
    )
    _, open_draft, claimed_draft = BEFORE_0010

    def before_0010() -> list[tuple[Any, ...]]:
        with engine.connect() as connection:
            found = connection.execute(
                text(statuses), {"open": open_draft, "claimed": claimed_draft}
            )
            return [tuple(row) for row in found.all()]

    stored = before_0010()
    assert stored == [(claimed_draft, "claimed", ANALYST.value), (open_draft, "open", None)]
    assert scalar(engine, "SELECT count(*) FROM review_task WHERE rule_version_id IS NULL") == 0
    command.downgrade(alembic_config, "0009")
    assert scalar(engine, "SELECT version_num FROM alembic_version") == "0009"
    nullable = (
        "SELECT is_nullable FROM information_schema.columns WHERE table_schema = :schema"
        " AND table_name = 'review_task' AND column_name = 'rule_version_id'"
    )
    assert scalar(engine, nullable, schema=SCHEMA) == "NO"
    assert scalar(engine, "SELECT to_regclass('rule_candidate')") is None
    assert scalar(engine, "SELECT to_regclass('processed_event')") is None
    assert before_0010() == stored
    command.upgrade(alembic_config, "head")
    assert scalar(engine, "SELECT version_num FROM alembic_version") == "0012"
    assert scalar(engine, nullable, schema=SCHEMA) == "YES"
    assert before_0010() == stored


def test_the_checks_keep_candidates_and_their_tasks_consistent(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    columns = (
        "id, document_id, regulator, model, prompt_version, confidence, citation_count,"
        " needs_review, outcome, status, event_id"
    )

    def insert_candidate(candidate_id: UUID, **values: Any) -> None:
        row = {
            "regulator": "cbic",
            "outcome": "extracted",
            "status": "open",
            "confidence": 0.5,
            **values,
        }
        execute(
            engine,
            f"INSERT INTO rule_candidate ({columns}) VALUES (:id, :doc, :regulator, 'm', 'p@1',"
            " :confidence, 0, false, :outcome, :status, :event)",
            id=candidate_id,
            doc=DOC.value,
            event=uuid4(),
            **row,
        )

    with pytest.raises(IntegrityError, match="ck_rule_candidate_regulator"):
        insert_candidate(uuid4(), regulator="CBIC")
    with pytest.raises(IntegrityError, match="ck_rule_candidate_state"):
        insert_candidate(uuid4(), status="drafted")
    with pytest.raises(IntegrityError, match="ck_rule_candidate_outcome"):
        insert_candidate(uuid4(), outcome="failed")
    with pytest.raises(IntegrityError, match="ck_rule_candidate_confidence"):
        insert_candidate(uuid4(), confidence=1.5)
    candidate = uuid4()
    insert_candidate(candidate)
    task = (
        "INSERT INTO review_task (id, rule_version_id, kind, priority, regulator, candidate_id)"
        " VALUES (:id, NULL, :kind, 10, 'cbic', :candidate)"
    )
    with pytest.raises(IntegrityError, match="ck_review_task_subject"):
        execute(engine, task, id=uuid4(), kind="seed", candidate=candidate)
    with pytest.raises(IntegrityError, match="ck_review_task_subject"):
        execute(engine, task, id=uuid4(), kind="candidate", candidate=None)
    execute(engine, task, id=uuid4(), kind="candidate", candidate=candidate)
    with pytest.raises(IntegrityError, match="uq_review_task_undecided_candidate"):
        execute(engine, task, id=uuid4(), kind="candidate", candidate=candidate)


def test_a_candidate_task_takes_its_version_once(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    intake = IngestRuleCandidate(notification, Clock()).run(payload(), uuid4())
    assert intake.task is not None
    task_id = intake.task.task_id
    rule, first, second = uuid4(), uuid4(), uuid4()
    execute(
        engine,
        "INSERT INTO rule (id, rule_key, regulator, level) VALUES (:id, :key, 'cbic', 'entity')",
        id=rule,
        key=f"example_guard_{rule.hex[:8]}",
    )
    drafted_from = {first: intake.candidate.candidate_id, second: None}
    for number, version in enumerate((first, second), start=1):
        execute(
            engine,
            "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
            " obligation_template, effective_from, candidate_id) VALUES (:id, :rule, :number,"
            " 'draft', 'Example draft', '{}', '{}', DATE '2000-02-01', :candidate)",
            id=version,
            rule=rule,
            number=number,
            candidate=drafted_from[version],
        )
    move = "UPDATE review_task SET rule_version_id = :version WHERE id = :id"
    execute(engine, move, version=first, id=task_id)
    with pytest.raises(IntegrityError, match="keeps its version once it has one"):
        execute(engine, move, version=second, id=task_id)
    with pytest.raises(IntegrityError, match="keeps its kind, candidate, regulator"):
        execute(
            engine,
            "UPDATE review_task SET candidate_id = NULL, kind = 'seed' WHERE id = :id",
            id=task_id,
        )
    with pytest.raises(IntegrityError, match="never deleted"):
        execute(engine, "DELETE FROM review_task WHERE id = :id", id=task_id)


def _rows(engine: Engine, sql: str) -> list[Any]:
    with engine.connect() as connection:
        return list(connection.execute(text(sql)).all())


def test_a_candidate_is_drafted_approved_and_another_rejected_on_postgres(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    factory, clock = notification, Clock(START + timedelta(days=1))
    ontology = ontology_package.load()
    relation = _relation(factory)
    intake = IngestRuleCandidate(factory, clock).run(payload(suggested_rule_key=None), uuid4())
    assert intake.task is not None
    assert intake.candidate.suggested_rule_key == "gstr3b_monthly", "its relations name it"
    task_id = intake.task.task_id
    ClaimReviewTask(factory, clock).run(task_id, by=ANALYST)
    monthly = scalar(
        engine,
        "SELECT v.id FROM rule_version v JOIN rule r ON r.id = v.rule_id"
        " WHERE r.rule_key = :rule ORDER BY v.version LIMIT 1",
        rule=MONTHLY,
    )
    detail = DraftFromCandidate(factory, lambda: ontology, clock).run(
        task_id,
        by=ANALYST,
        rule_key="example_extension_2000_01",
        new_rule=NewRule("CBIC", AttributeLevel.REGISTRATION),
        relations=[RelationChoice(relation, RuleVersionId(monthly))],
    )
    assert detail.version is not None
    assert (detail.version.version, detail.version.high_impact, detail.version.regulator) == (
        1,
        True,
        "cbic",
    )
    assert len(detail.citations) == 2
    assert (
        scalar(
            engine,
            "SELECT count(*) FROM rule_relation"
            " WHERE from_rule_version_id = :v AND candidate_id = :c",
            v=detail.version.rule_version_id.value,
            c=relation,
        )
        == 1
    )
    decide = DecideReviewTask(factory, clock)
    decide.run(task_id, ReviewDecision.APPROVE, by=REVIEWER)
    approved = decide.run(task_id, ReviewDecision.APPROVE, by=OTHER_REVIEWER)
    assert approved.candidate is not None
    assert approved.candidate.status is RuleCandidateStatus.APPROVED
    assert approved.task.status is ReviewTaskStatus.DECIDED

    other = IngestRuleCandidate(factory, clock).run(payload(), uuid4())
    assert other.task is not None
    rejected = decide.run(
        other.task.task_id,
        ReviewDecision.REJECT,
        by=REVIEWER,
        note="Another candidate holds it",
        reason=RuleRejectReason.DUPLICATE,
    )
    (event,) = rejected.events
    assert isinstance(event, RuleRejected)
    stored = scalar(
        engine, "SELECT message FROM outbox_event WHERE id = :id", id=event.event_id.value
    )
    assert stored["topic"] == "rule.rejected"
    assert stored["payload"]["reason"] == "duplicate"
    assert scalar(
        engine, "SELECT partition_key FROM outbox_event WHERE id = :id", id=event.event_id.value
    ) == str(DOC)
    counts = ReadReviewStats(factory).run().candidates
    assert (counts.approved, counts.approved_without_edits, counts.rejected) == (1, 1, 1)
    assert counts.acceptance_rate == 0.5
    export = ExportDecidedCandidates(factory).run(START)
    case = {case.candidate_id: case for case in export.cases}[intake.candidate.candidate_id]
    assert (case.content["label_status"], case.content["reviewed_by"]) == ("draft", "")
    assert case.content["labelled_by"] == str(approved.candidate.decided_by)
    assert case.rule_version_id == detail.version.rule_version_id
    assert [c["clause_ref"] for c in case.content["expected"]["citations"]] == ["en.p2", "en.p3"]
    assert other.candidate.candidate_id in {r.candidate_id for r in export.rejections}


KEYS_0011 = (
    "fk_review_task_rule_version_id_candidate_id_rule_version",
    "fk_rule_candidate_rule_version_id_id_rule_version",
    "uq_rule_version_id_candidate_id",
)


def _keys_0011(engine: Engine) -> list[str]:
    names = ", ".join(f"'{name}'" for name in KEYS_0011)
    return [
        row[0]
        for row in _rows(
            engine,
            f"SELECT conname FROM pg_constraint WHERE conname IN ({names}) ORDER BY conname",
        )
    ]


def test_migration_0011_goes_down_and_up_over_drafted_candidates(
    notification: PostgresKnowledgeUnitOfWorkFactory, alembic_config: Config, engine: Engine
) -> None:
    """After the drafting above, so the keys are added over candidates and tasks that name
    their drafts."""
    drafted = "SELECT count(*) FROM rule_candidate WHERE rule_version_id IS NOT NULL"
    assert scalar(engine, drafted) > 0
    assert _keys_0011(engine) == list(KEYS_0011)
    command.downgrade(alembic_config, "0010")
    assert scalar(engine, "SELECT version_num FROM alembic_version") == "0010"
    assert _keys_0011(engine) == []
    command.upgrade(alembic_config, "head")
    assert scalar(engine, "SELECT version_num FROM alembic_version") == "0012"
    assert _keys_0011(engine) == list(KEYS_0011)


def test_a_candidate_and_its_task_name_only_the_draft_made_from_it(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    """Three drafts of one rule, written as SQL so no unique index answers first: one with no
    candidate (a seed draft), one drafted from another candidate, and the candidate's own. Only
    the candidate's own is taken, and once it is, its candidate_id never changes."""
    factory, clock = notification, Clock(START + timedelta(days=5))
    candidate, other, unused = (
        IngestRuleCandidate(factory, clock).run(payload(), uuid4()) for _ in range(3)
    )
    assert candidate.task is not None
    rule = uuid4()
    execute(
        engine,
        "INSERT INTO rule (id, rule_key, regulator, level) VALUES (:id, :key, 'cbic', 'entity')",
        id=rule,
        key=f"example_keys_{rule.hex[:8]}",
    )
    seed_draft, others_draft, own_draft = uuid4(), uuid4(), uuid4()
    drafted_from = {
        seed_draft: None,
        others_draft: other.candidate.candidate_id,
        own_draft: candidate.candidate.candidate_id,
    }
    for number, (version, drafted) in enumerate(drafted_from.items(), start=1):
        execute(
            engine,
            "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
            " obligation_template, effective_from, candidate_id) VALUES (:id, :rule, :number,"
            " 'draft', 'Example draft', '{}', '{}', DATE '2000-02-01', :candidate)",
            id=version,
            rule=rule,
            number=number,
            candidate=drafted,
        )
    point_task = "UPDATE review_task SET rule_version_id = :version WHERE id = :id"
    point_candidate = (
        "UPDATE rule_candidate SET status = 'drafted', rule_version_id = :version WHERE id = :id"
    )
    task_key, candidate_key = KEYS_0011[0], KEYS_0011[1]
    for version in (seed_draft, others_draft):
        with pytest.raises(IntegrityError, match=task_key):
            execute(engine, point_task, version=version, id=candidate.task.task_id)
        with pytest.raises(IntegrityError, match=candidate_key):
            execute(engine, point_candidate, version=version, id=candidate.candidate.candidate_id)
    execute(engine, point_task, version=own_draft, id=candidate.task.task_id)
    execute(engine, point_candidate, version=own_draft, id=candidate.candidate.candidate_id)
    with pytest.raises(IntegrityError, match=f"{task_key}|{candidate_key}"):
        execute(
            engine,
            "UPDATE rule_version SET candidate_id = :unused WHERE id = :id",
            unused=unused.candidate.candidate_id,
            id=own_draft,
        )
    assert (
        scalar(engine, "SELECT candidate_id FROM rule_version WHERE id = :id", id=own_draft)
        == candidate.candidate.candidate_id
    )


def _monthly(engine: Engine) -> RuleVersionId:
    """The seed calendar's first gstr3b_monthly version, which the extension targets."""
    return RuleVersionId(
        scalar(
            engine,
            "SELECT v.id FROM rule_version v JOIN rule r ON r.id = v.rule_id"
            " WHERE r.rule_key = :rule ORDER BY v.version LIMIT 1",
            rule=MONTHLY,
        )
    )


def test_a_rejection_after_drafting_reopens_the_relations_on_postgres(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    factory, clock = notification, Clock(START + timedelta(days=3))
    relation, monthly = _relation(factory), _monthly(engine)
    draft = DraftFromCandidate(factory, ontology_package.load, clock)
    decide = DecideReviewTask(factory, clock)
    intake = IngestRuleCandidate(factory, clock).run(payload(), uuid4())
    assert intake.task is not None
    ClaimReviewTask(factory, clock).run(intake.task.task_id, by=ANALYST)
    detail = draft.run(
        intake.task.task_id,
        by=ANALYST,
        rule_key="example_extension_reopened",
        new_rule=NewRule("cbic", AttributeLevel.REGISTRATION),
        relations=[RelationChoice(relation, monthly)],
    )
    assert detail.version is not None
    decided = decide.run(
        intake.task.task_id,
        ReviewDecision.REJECT,
        by=REVIEWER,
        note="The model read the date wrongly",
        reason=RuleRejectReason.WRONG_EXTRACTION,
    )
    assert decided.reopened_relations == (relation,)
    assert (
        scalar(engine, "SELECT count(*) FROM rule_relation WHERE candidate_id = :c", c=relation)
        == 0
    )
    with engine.connect() as connection:
        reopened = connection.execute(
            text(
                "SELECT status, decided_at, decided_by, reject_reason, note"
                " FROM relation_candidate WHERE id = :c"
            ),
            {"c": relation},
        ).one()
    assert tuple(reopened)[:4] == ("open", None, "", None)
    assert reopened.note.startswith(
        f"reopened: rule candidate {intake.candidate.candidate_id} was rejected (wrong_extraction)"
    )

    corrected = IngestRuleCandidate(factory, clock).run(payload(), uuid4())
    assert corrected.task is not None
    ClaimReviewTask(factory, clock).run(corrected.task.task_id, by=ANALYST)
    again = draft.run(
        corrected.task.task_id,
        by=ANALYST,
        rule_key="example_extension_corrected",
        new_rule=NewRule("cbic", AttributeLevel.REGISTRATION),
        relations=[RelationChoice(relation, monthly)],
    )
    assert again.version is not None
    assert (
        scalar(
            engine,
            "SELECT from_rule_version_id FROM rule_relation WHERE candidate_id = :c",
            c=relation,
        )
        == again.version.rule_version_id.value
    )
    assert (
        scalar(engine, "SELECT status FROM relation_candidate WHERE id = :c", c=relation)
        == "approved"
    )


def _relation(factory: PostgresKnowledgeUnitOfWorkFactory) -> UUID:
    clause = clause_id_for(DOC, "en.p2")
    candidate = RelationCandidate(
        candidate_id=uuid4(),
        document_id=DOC,
        relation=RelationKind.EXTENDS_DEADLINE,
        target_type=EntityType.FORM,
        target_name="example return",
        target_clause_id=clause,
        target_span_start=TEXT_EXTENDS.index("example return"),
        target_span_end=TEXT_EXTENDS.index("example return") + len("example return"),
        evidence_clause_id=clause,
        evidence_quote=QUOTE_EXTENDS,
        quote_score=1.0,
        prompt_version="extraction.rule_relations@1",
        confidence=0.9,
        needs_review=False,
        target_rule_key="gstr3b_monthly",
        period_label="2000-01",
        new_due_on=date(2000, 2, 25),
    )
    with factory() as uow:
        uow.candidates.add(candidate)
    return candidate.candidate_id


def _retitled(calendar: SeedCalendar, rule_key: str, title: str) -> SeedCalendar:
    rules = tuple(
        replace(rule, title=title) if rule.rule_key == rule_key else rule for rule in calendar.rules
    )
    return replace(calendar, rules=rules)


def test_the_seed_updates_its_own_draft_beside_a_candidates_draft(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    factory, clock = notification, Clock(START + timedelta(days=2))
    intake = IngestRuleCandidate(factory, clock).run(payload(), uuid4())
    assert intake.task is not None
    ClaimReviewTask(factory, clock).run(intake.task.task_id, by=ANALYST)
    detail = DraftFromCandidate(factory, ontology_package.load, clock).run(
        intake.task.task_id, by=ANALYST, rule_key="gstr1_quarterly"
    )
    assert detail.version is not None
    calendar, seed = load_calendar(ontology_package.load()), SqlAlchemySeedRepository(engine)
    outcome = seed.apply(calendar)
    assert "gstr1_quarterly" in outcome.unchanged, "a candidate's draft beside it freezes nothing"
    edited = seed.apply(_retitled(calendar, "gstr1_quarterly", "Example: edited"))
    assert edited.updated_drafts == ("gstr1_quarterly@1",)
    titles = (
        "SELECT v.version, v.title FROM rule_version v JOIN rule r ON r.id = v.rule_id"
        " WHERE r.rule_key = 'gstr1_quarterly' ORDER BY v.version"
    )
    assert [tuple(row) for row in _rows(engine, titles)] == [
        (1, "Example: edited"),
        (2, FIELDS["title"]),
    ], "the seed updated its own draft, and not the candidate's"
    assert seed.apply(calendar).updated_drafts == ("gstr1_quarterly@1",)
    opened = OpenSeedReviewTasks(factory, clock).run().opened
    assert detail.version.rule_version_id not in {task.rule_version_id for task in opened}


def test_a_rejected_candidates_draft_is_closed_on_postgres(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    factory, clock = notification, Clock(START + timedelta(days=4))
    seeded = "gstr3b_quarterly_group_a"
    intake = IngestRuleCandidate(factory, clock).run(payload(), uuid4())
    assert intake.task is not None
    ClaimReviewTask(factory, clock).run(intake.task.task_id, by=ANALYST)
    detail = DraftFromCandidate(factory, ontology_package.load, clock).run(
        intake.task.task_id, by=ANALYST, rule_key=seeded
    )
    assert detail.version is not None
    with factory() as uow:
        listed = {rule.rule_key: rule.title for rule in uow.rules.list_rules()}
    assert listed[seeded] == FIELDS["title"], "an open draft from a candidate is the latest version"
    DecideReviewTask(factory, clock).run(
        intake.task.task_id,
        ReviewDecision.REJECT,
        by=REVIEWER,
        note="The model read the date wrongly",
        reason=RuleRejectReason.WRONG_EXTRACTION,
    )
    calendar = load_calendar(ontology_package.load())
    with factory() as uow:
        listed = {rule.rule_key: rule.title for rule in uow.rules.list_rules()}
        head = uow.rule_versions.lock_rule(seeded)
    assert listed[seeded] == calendar.get(seeded).title, (
        "a closed draft is never the latest version"
    )
    assert head is not None
    assert head.last_version == 2
    listed_versions = ListRuleVersions(factory).run(seeded)
    assert [(v.record.version, v.closed) for v in listed_versions] == [(1, False), (2, True)]
    outcome = SqlAlchemySeedRepository(engine).apply(calendar)
    assert seeded in outcome.unchanged
    assert seeded not in outcome.kept_edited
    with pytest.raises(RuleVersionClosedError):
        SubmitForReview(factory, clock).run(detail.version.rule_version_id, actor_id=ANALYST)
    assert (
        scalar(
            engine,
            "SELECT status FROM rule_version WHERE id = :id",
            id=detail.version.rule_version_id.value,
        )
        == "draft"
    )


def _waits_for_a_lock(engine: Engine, seconds: float = 20.0) -> None:
    """Until a session of the database waits for a lock another holds."""
    deadline = time.monotonic() + seconds
    waiting = (
        "SELECT count(*) FROM pg_stat_activity"
        " WHERE wait_event_type = 'Lock' AND datname = current_database()"
    )
    while scalar(engine, waiting) == 0:
        assert time.monotonic() < deadline, "the seed never waited for the rule's lock"
        time.sleep(0.05)


def test_the_seed_waits_for_a_draft_holding_the_rule_and_numbers_after_it(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    """A draft from a candidate holds its rule's lock until it commits. A seed run meanwhile
    waits for the lock, then reads the draft, where it once read the versions without a lock
    and took the draft's number (a unique violation when the second of them committed)."""
    seeded, candidate = "cmp08_quarterly", uuid4()
    execute(
        engine,
        "UPDATE rule_version SET status = 'in_review', submitted_at = now() FROM rule"
        " WHERE rule.id = rule_version.rule_id AND rule.rule_key = :rule AND version = 1",
        rule=seeded,
    )
    execute(
        engine,
        "INSERT INTO rule_candidate (id, document_id, regulator, model, prompt_version,"
        " confidence, citation_count, needs_review, outcome, status, event_id) VALUES"
        " (:id, :doc, 'cbic', 'fake/echo', 'extraction.rule_candidate@1', 0.9, 0, false,"
        " 'extracted', 'open', :event)",
        id=candidate,
        doc=DOC.value,
        event=uuid4(),
    )
    seeds: list[SeedOutcome | BaseException] = []

    def seed() -> None:
        calendar = _retitled(load_calendar(ontology_package.load()), seeded, "Example: edited")
        try:
            seeds.append(SqlAlchemySeedRepository(engine).apply(calendar))
        except BaseException as exc:  # handed to the test below
            seeds.append(exc)

    with engine.connect() as drafting, drafting.begin():
        rule = drafting.execute(
            text("SELECT id FROM rule WHERE rule_key = :rule FOR UPDATE"), {"rule": seeded}
        ).scalar_one()
        drafting.execute(
            text(
                "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
                " obligation_template, effective_from, candidate_id) VALUES (:id, :rule, 2,"
                " 'draft', 'Example draft from a candidate', '{}', '{}', DATE '2000-02-01',"
                " :candidate)"
            ),
            {"id": uuid4(), "rule": rule, "candidate": candidate},
        )
        thread = threading.Thread(target=seed)
        thread.start()
        _waits_for_a_lock(engine)
    thread.join(timeout=60)
    assert not thread.is_alive()
    (outcome,) = seeds
    assert isinstance(outcome, SeedOutcome), outcome
    assert seeded in outcome.kept_edited, "the candidate's draft is the rule's latest version"
    versions = (
        "SELECT v.version, v.status, v.candidate_id IS NOT NULL FROM rule_version v"
        f" JOIN rule r ON r.id = v.rule_id WHERE r.rule_key = '{seeded}' ORDER BY v.version"
    )
    assert [tuple(row) for row in _rows(engine, versions)] == [
        (1, "in_review", False),
        (2, "draft", True),
    ]


# ---------------------------------------------------------------- the consumer


def message_of(body: dict[str, Any]) -> InboundRecord:
    message = EventMessage(
        event_id=uuid4(),
        topic=worker.CANDIDATE_TOPIC,
        schema_version="1.1.1",
        occurred_at=START,
        tenant_id=None,
        correlation_id=uuid4(),
        causation_id=None,
        payload=body,
    )
    return InboundRecord(
        topic=worker.CANDIDATE_TOPIC, partition=0, offset=0, key=b"k", value=encode(message)
    )


def consumer_of(engine: Engine, handler: Any) -> tuple[IdempotentConsumer, FakeProducer]:
    producer = FakeProducer()
    return (
        IdempotentConsumer(
            group_id=worker.CANDIDATES_GROUP_ID,
            store=SyncProcessedStore(engine, group_id=worker.CANDIDATES_GROUP_ID),
            handler=handler,
            producer=producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        ),
        producer,
    )


def stored(engine: Engine, record: InboundRecord, candidate_id: str) -> tuple[int, int, int]:
    """The candidate rows, the task rows and the inbox rows of one event."""
    event_id = json.loads(record.value)["event_id"]
    return (
        scalar(engine, "SELECT count(*) FROM rule_candidate WHERE id = :id", id=candidate_id),
        scalar(
            engine, "SELECT count(*) FROM review_task WHERE candidate_id = :id", id=candidate_id
        ),
        scalar(engine, "SELECT count(*) FROM processed_event WHERE event_id = :id", id=event_id),
    )


async def test_the_consumer_commits_the_candidate_its_task_and_the_inbox_together(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    body = payload()
    record = message_of(body)
    consumer, producer = consumer_of(engine, worker.candidate_handler())
    assert await consumer.process(record) is Outcome.PROCESSED
    assert stored(engine, record, body["candidate_id"]) == (1, 1, 1)
    assert await consumer.process(record) is Outcome.SKIPPED
    assert producer.sent == []


async def test_a_failing_handler_leaves_neither_candidate_task_nor_inbox_row(
    notification: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    def fails_after_its_writes(message: EventMessage, connection: Connection) -> None:
        IngestRuleCandidate(PostgresKnowledgeUnitOfWorkFactory.on_connection(connection)).run(
            message.payload, message.event_id
        )
        raise RuntimeError("the handler fails after the intake wrote")

    body = payload()
    record = message_of(body)
    consumer, producer = consumer_of(engine, sync_handler(fails_after_its_writes))
    assert await consumer.process(record) is Outcome.DEAD
    assert stored(engine, record, body["candidate_id"]) == (0, 0, 0)
    unknown = payload(document_id=str(uuid4()))
    dead, _ = consumer_of(engine, worker.candidate_handler())
    unknown_record = message_of(unknown)
    assert await dead.process(unknown_record) is Outcome.DEAD
    assert stored(engine, unknown_record, unknown["candidate_id"]) == (0, 0, 0)
    assert producer.topics() == ["rule.candidate.created.rulebook.rule-candidates.dlq"]


# ---------------------------------------------------------------- the way down


def test_migration_0010_goes_down_only_while_no_candidate_is_stored(
    notification: PostgresKnowledgeUnitOfWorkFactory, alembic_config: Config, engine: Engine
) -> None:
    """Last in this module: it stores one more candidate, and the way down stays closed. The
    downgrade refuses before it changes anything, with what it found, rather than failing on
    the check it would put back."""
    IngestRuleCandidate(notification, Clock()).run(payload(), uuid4())
    candidates = scalar(engine, "SELECT count(*) FROM rule_candidate")
    tasks = scalar(engine, "SELECT count(*) FROM review_task WHERE kind = 'candidate'")
    assert candidates > 0
    with pytest.raises(
        RuntimeError, match=f"found {candidates} rule candidates and {tasks} candidate tasks"
    ):
        command.downgrade(alembic_config, "0009")
    assert scalar(engine, "SELECT version_num FROM alembic_version") == "0012"
    assert _keys_0011(engine) == list(KEYS_0011), "the refused downgrade changed nothing"
    assert scalar(engine, "SELECT count(*) FROM rule_candidate") == candidates
