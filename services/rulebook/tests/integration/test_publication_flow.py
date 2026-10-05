"""The publish flow on Postgres: migration 0007 down and up, the rule_version guard refusing
direct updates the kernel does not allow, outbox rows committing and rolling back with their
transaction, a publication end to end, the daily sweep and its command. Needs Docker."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import ClauseId, CorrelationId, RuleId, RuleVersionId, SourceId, UserId
from domain_kernel.knowledge import RelationKind, RuleRelation
from rulebook.application.documents import RegisterDocument
from rulebook.application.publication import (
    AddCitations,
    ApplyDueTransitions,
    ApproveVersion,
    CitationInput,
    PublishVersion,
    SubmitForReview,
)
from rulebook.application.rule_versions import ListRuleVersions, ReadRuleVersion
from rulebook.domain.documents import StoredDocument
from rulebook.domain.events import RuleWithdrawn
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.transitions import main as transitions_main

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
TEXT = "The due date for furnishing the return in FORM GSTR-3B for September, 2026 is extended."
QUOTE = "furnishing the return in FORM GSTR-3B for September, 2026"
SPECIFICATION = '{"attribute": "registration_type", "operator": "eq", "value": "regular"}'
ANALYST = UserId(UUID(int=11))
REVIEWER = UserId(UUID(int=12))


class Clock:
    def __init__(self, start: datetime = NOW) -> None:
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
    yield factory
    factory.engine.dispose()


@pytest.fixture(scope="module")
def clause(factory: PostgresKnowledgeUnitOfWorkFactory) -> ClauseId:
    digest = hashlib.sha256(b"publication flow").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(factory).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/publication.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=NOW,
            published_at=date(2026, 9, 30),
        ),
        [Clause("en.p1", TEXT)],
    )
    return clause_id_for(document_id, "en.p1")


def execute(engine: Engine, statement: str, **params: object) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement), params)


def scalar(engine: Engine, statement: str, **params: object) -> object:
    with engine.connect() as connection:
        return connection.execute(text(statement), params).scalar_one()


def rule(engine: Engine) -> RuleId:
    rule_id = RuleId(uuid4())
    execute(
        engine,
        "INSERT INTO rule (id, rule_key, regulator, level)"
        " VALUES (:id, :key, 'CBIC', 'registration')",
        id=rule_id.value,
        key=f"rule_{rule_id.value.hex[:12]}",
    )
    return rule_id


def version(
    engine: Engine,
    rule_id: RuleId,
    number: int,
    status: str = "draft",
    effective_from: date = date(2026, 4, 1),
    *,
    high_impact: bool = False,
) -> RuleVersionId:
    version_id = RuleVersionId(uuid4())
    execute(
        engine,
        "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
        " obligation_template, effective_from, high_impact, published_at)"
        " VALUES (:id, :rule, :number, :status, :title, CAST(:spec AS jsonb), '{}',"
        " :start, :high_impact, CASE WHEN :published THEN now() END)",
        id=version_id.value,
        rule=rule_id.value,
        number=number,
        status=status,
        title=f"version {number}",
        spec=SPECIFICATION,
        start=effective_from,
        high_impact=high_impact,
        published=status != "draft",
    )
    return version_id


def through_review(
    factory: PostgresKnowledgeUnitOfWorkFactory,
    clock: Clock,
    rule_id: RuleId,
    clause: ClauseId,
    number: int = 1,
) -> RuleVersionId:
    """A version published through the review flow: the insert guard admits only drafts."""
    version_id = version(factory.engine, rule_id, number)
    AddCitations(factory, clock).run(version_id, [CitationInput(clause, QUOTE)])
    SubmitForReview(factory, clock).run(version_id, actor_id=ANALYST)
    ApproveVersion(factory, clock).run(version_id, actor_id=REVIEWER)
    PublishVersion(factory, enabled=True, clock=clock).run(version_id, actor_id=ANALYST)
    return version_id


def update(engine: Engine, version_id: RuleVersionId, assignment: str) -> None:
    execute(engine, f"UPDATE rule_version SET {assignment} WHERE id = :id", id=version_id.value)


def approve_directly(engine: Engine, version_id: RuleVersionId, actor: UserId) -> None:
    execute(
        engine,
        "INSERT INTO rule_version_decision (id, rule_version_id, action, from_status, to_status,"
        " actor_id, decided_at) VALUES (:id, :version, 'approved', 'in_review', 'in_review',"
        " :actor, clock_timestamp())",
        id=uuid4(),
        version=version_id.value,
        actor=actor.value,
    )


def outbox(engine: Engine) -> list[tuple[str, str, dict[str, object]]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT topic, partition_key, message FROM outbox_event"
                " ORDER BY available_at, created_at, id"
            )
        ).all()
    return [(topic, key, message) for topic, key, message in rows]


# ---------------------------------------------------------------- migration


def test_migration_0007_goes_down_and_up(
    alembic_config: Config, factory: PostgresKnowledgeUnitOfWorkFactory
) -> None:
    engine = factory.engine
    command.downgrade(alembic_config, "0006")
    columns = {c["name"] for c in inspect(engine).get_columns("rule_version", schema=SCHEMA)}
    assert {"high_impact", "submitted_at"}.isdisjoint(columns)
    tables = set(inspect(engine).get_table_names(schema=SCHEMA))
    assert {"rule_version_decision", "outbox_event"}.isdisjoint(tables)
    guards = (
        "SELECT count(*) FROM pg_proc WHERE proname IN"
        " ('rulebook_rule_version_guard', 'rulebook_rule_version_insert_guard')"
    )
    assert scalar(engine, guards) == 0
    before = RuleVersionId(uuid4())
    execute(
        engine,
        "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
        " obligation_template, effective_from, published_at)"
        " VALUES (:id, :rule, 1, 'draft', 'before 0007', '{}', '{}', DATE '2026-04-01', now())",
        id=before.value,
        rule=rule(engine).value,
    )
    update(engine, before, "status = 'published'")

    command.upgrade(alembic_config, "head")
    assert scalar(engine, "SELECT version_num FROM alembic_version") == "0007"
    assert (
        scalar(engine, "SELECT high_impact FROM rule_version WHERE id = :id", id=before.value)
        is False
    )
    tables = set(inspect(engine).get_table_names(schema=SCHEMA))
    assert {"rule_version_decision", "outbox_event"} <= tables
    assert scalar(engine, guards) == 2
    with pytest.raises(IntegrityError, match="cannot move from published to draft"):
        update(engine, before, "status = 'draft'")


# ---------------------------------------------------------------- the guard


def test_a_version_is_inserted_only_as_an_unpublished_draft(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    engine = factory.engine
    rule_id = rule(engine)
    for number, status in enumerate(("in_review", "approved", "published", "superseded"), 1):
        with pytest.raises(IntegrityError, match=f"inserted as an unpublished draft, not {status}"):
            version(engine, rule_id, number, status)
    with pytest.raises(IntegrityError, match="unpublished draft"):
        execute(
            engine,
            "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
            " obligation_template, effective_from, published_at) VALUES (:id, :rule, 1, 'draft',"
            " 'published early', '{}', '{}', DATE '2026-04-01', now())",
            id=uuid4(),
            rule=rule_id.value,
        )
    assert (
        scalar(engine, "SELECT count(*) FROM rule_version WHERE rule_id = :id", id=rule_id.value)
        == 0
    )
    version(engine, rule_id, 1)


def test_the_guard_refuses_what_the_kernel_does_not_allow(
    factory: PostgresKnowledgeUnitOfWorkFactory, clause: ClauseId
) -> None:
    engine = factory.engine
    version_id = version(engine, rule(engine), 1)
    with pytest.raises(IntegrityError, match="cannot move from draft to published"):
        update(engine, version_id, "status = 'published', published_at = now()")
    update(engine, version_id, "title = 'drafts may change'")
    update(engine, version_id, "status = 'in_review', submitted_at = clock_timestamp()")
    update(engine, version_id, "status = 'approved'")
    update(engine, version_id, "status = 'draft', submitted_at = NULL")
    update(engine, version_id, "status = 'in_review', submitted_at = clock_timestamp()")
    update(engine, version_id, "status = 'approved'")
    with pytest.raises(IntegrityError, match="needs published_at"):
        update(engine, version_id, "status = 'published'")
    with pytest.raises(IntegrityError, match="verified citations"):
        update(engine, version_id, "status = 'published', published_at = now()")
    execute(
        engine,
        "INSERT INTO citation (id, rule_version_id, clause_id, quote, verified, match_score,"
        " verified_at) VALUES (:id, :version, :clause, :quote, true, 1, now())",
        id=uuid4(),
        version=version_id.value,
        clause=clause.value,
        quote=QUOTE,
    )
    with pytest.raises(IntegrityError, match="needs 1 approvers, has 0"):
        update(engine, version_id, "status = 'published', published_at = now()")
    approve_directly(engine, version_id, REVIEWER)
    update(engine, version_id, "status = 'published', published_at = now()")

    with pytest.raises(IntegrityError, match="content of a published version is frozen"):
        update(engine, version_id, "title = 'changed after publication'")
    with pytest.raises(IntegrityError, match="frozen"):
        update(engine, version_id, "high_impact = true")
    update(engine, version_id, "effective_to = DATE '2027-04-01'")
    with pytest.raises(IntegrityError, match="set or moved earlier"):
        update(engine, version_id, "effective_to = DATE '2027-06-01'")
    with pytest.raises(IntegrityError, match="set or moved earlier"):
        update(engine, version_id, "effective_to = NULL")
    update(engine, version_id, "effective_to = DATE '2027-01-01'")
    with pytest.raises(IntegrityError, match="cannot move from published to draft"):
        update(engine, version_id, "status = 'draft'")
    update(engine, version_id, "status = 'superseded'")
    with pytest.raises(IntegrityError, match="cannot move from superseded to published"):
        update(engine, version_id, "status = 'published'")


def test_a_high_impact_version_needs_two_approvers_of_this_round(
    factory: PostgresKnowledgeUnitOfWorkFactory, clause: ClauseId
) -> None:
    engine = factory.engine
    version_id = version(engine, rule(engine), 1, high_impact=True)
    execute(
        engine,
        "INSERT INTO citation (id, rule_version_id, clause_id, quote, verified, match_score,"
        " verified_at) VALUES (:id, :version, :clause, :quote, true, 1, now())",
        id=uuid4(),
        version=version_id.value,
        clause=clause.value,
        quote=QUOTE,
    )
    update(engine, version_id, "status = 'in_review', submitted_at = clock_timestamp()")
    approve_directly(engine, version_id, REVIEWER)
    update(engine, version_id, "status = 'draft'")
    update(engine, version_id, "status = 'in_review', submitted_at = clock_timestamp()")
    approve_directly(engine, version_id, ANALYST)
    update(engine, version_id, "status = 'approved'")
    with pytest.raises(IntegrityError, match="needs 2 approvers, has 1"):
        update(engine, version_id, "status = 'published', published_at = now()")
    approve_directly(engine, version_id, ANALYST)
    with pytest.raises(IntegrityError, match="needs 2 approvers, has 1"):
        update(engine, version_id, "status = 'published', published_at = now()")
    approve_directly(engine, version_id, REVIEWER)
    update(engine, version_id, "status = 'published', published_at = now()")


def test_a_synthetic_round_publishes_a_version_that_stays_needs_review(
    factory: PostgresKnowledgeUnitOfWorkFactory, clause: ClauseId
) -> None:
    clock = Clock()
    rule_id = rule(factory.engine)
    version_id = version(factory.engine, rule_id, 1)
    AddCitations(factory, clock).run(version_id, [CitationInput(clause, QUOTE)])
    SubmitForReview(factory, clock).run(version_id, actor_id=ANALYST, high_impact=True)
    synthetic = ApproveVersion(factory, clock, synthetic_allowed=True)
    synthetic.run(version_id, actor_id=REVIEWER, synthetic=True)
    approved = synthetic.run(version_id, actor_id=ANALYST, synthetic=True)
    assert (approved.record.status.value, approved.record.seed_status.value) == (
        "approved",
        "needs_review",
    )
    PublishVersion(factory, enabled=True, clock=clock).run(version_id, actor_id=REVIEWER)
    key = scalar(factory.engine, "SELECT rule_key FROM rule WHERE id = :id", id=rule_id.value)
    draft = version(factory.engine, rule_id, 2, effective_from=date(2026, 7, 1))
    versions = ListRuleVersions(factory).run(str(key))
    assert [(v.rule_version_id, v.status.value, v.seed_status.value) for v in versions] == [
        (version_id, "published", "needs_review"),
        (draft, "draft", "needs_review"),
    ]


def test_decisions_are_append_only_and_name_an_actor_or_a_cause(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    engine = factory.engine
    version_id = version(engine, rule(engine), 1)
    approve_directly(engine, version_id, REVIEWER)
    with pytest.raises(IntegrityError, match="append-only"):
        execute(engine, "UPDATE rule_version_decision SET note = 'edited'")
    with pytest.raises(IntegrityError, match="append-only"):
        execute(engine, "DELETE FROM rule_version_decision")
    with pytest.raises(IntegrityError, match="ck_rule_version_decision_actor"):
        execute(
            engine,
            "INSERT INTO rule_version_decision (id, rule_version_id, action, from_status,"
            " to_status, decided_at) VALUES (:id, :version, 'superseded', 'published',"
            " 'superseded', now())",
            id=uuid4(),
            version=version_id.value,
        )


# ---------------------------------------------------------------- the outbox


def test_outbox_rows_commit_and_roll_back_with_their_transaction(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    rule_id = RuleId(uuid4())
    event = RuleWithdrawn(
        occurred_at=NOW,
        correlation_id=CorrelationId.new(),
        rule_id=rule_id,
        rule_version_id=RuleVersionId.new(),
        withdrawn_by_rule_version_id=None,
        effective_from=date(2026, 10, 1),
    )
    count = "SELECT count(*) FROM outbox_event WHERE id = :id"

    def publish_then_fail() -> None:
        with factory() as uow:
            uow.events.publish(event)
            raise RuntimeError("abort")

    with pytest.raises(RuntimeError, match="abort"):
        publish_then_fail()
    assert scalar(factory.engine, count, id=event.event_id.value) == 0
    with factory() as uow:
        uow.events.publish(event)
    assert scalar(factory.engine, count, id=event.event_id.value) == 1
    key = scalar(
        factory.engine,
        "SELECT partition_key FROM outbox_event WHERE id = :id",
        id=event.event_id.value,
    )
    assert key == str(rule_id)


def test_a_publication_writes_its_events_with_the_change(
    factory: PostgresKnowledgeUnitOfWorkFactory, clause: ClauseId
) -> None:
    engine = factory.engine
    clock = Clock()
    rule_id = rule(engine)
    old = through_review(factory, clock, rule_id, clause)
    execute(engine, "DELETE FROM outbox_event")
    new = version(engine, rule_id, 2, effective_from=date(2026, 7, 1))
    with factory() as uow:
        uow.relations.add(
            RuleRelation(new, RelationKind.SUPERSEDES, old, clause),
            relation_id=uuid4(),
            candidate_id=None,
        )
    AddCitations(factory, clock).run(new, [CitationInput(clause, QUOTE)])
    SubmitForReview(factory, clock).run(new, actor_id=ANALYST)
    ApproveVersion(factory, clock).run(new, actor_id=REVIEWER)
    publication = PublishVersion(factory, enabled=True, clock=clock).run(new, actor_id=ANALYST)

    rows = outbox(engine)
    assert [(topic, key) for topic, key, _ in rows] == [
        ("rule.published", str(rule_id)),
        ("rule.superseded", str(rule_id)),
    ]
    published, superseded = (message for _, _, message in rows)
    assert published["tenant_id"] is None
    assert published["correlation_id"] == str(publication.correlation_id)
    assert superseded["causation_id"] == published["event_id"]
    payload = published["payload"]
    assert isinstance(payload, dict)
    assert payload["supersedes"] == [str(old)]
    assert payload["approved_by"] == [str(REVIEWER)]
    assert payload["attribute_keys"] == ["registration_type"]
    with engine.connect() as connection:
        states: dict[UUID, str] = dict(
            connection.execute(
                text(
                    "SELECT id, status || ' ' || coalesce(effective_to::text, 'open')"
                    " FROM rule_version WHERE id IN (:old, :new)"
                ),
                {"old": old.value, "new": new.value},
            ).all()
        )
        actions: list[str] = list(
            connection.execute(
                text(
                    "SELECT action FROM rule_version_decision WHERE rule_version_id IN (:old, :new)"
                    " ORDER BY decided_at, action"
                ),
                {"old": old.value, "new": new.value},
            )
            .scalars()
            .all()
        )
    assert states == {old.value: "superseded 2026-07-01", new.value: "published open"}
    assert actions == [
        "submitted",
        "approved",
        "published",
        "submitted",
        "approved",
        "published",
        "superseded",
    ]
    detail = ReadRuleVersion(factory).run(new)
    assert (detail.approved_by, detail.record.published_at) == ((REVIEWER,), clock.now)
    assert ReadRuleVersion(factory).run(old).approved_by == (REVIEWER,), "superseded keeps them"


def test_the_sweep_moves_a_version_when_its_replacement_takes_effect(
    factory: PostgresKnowledgeUnitOfWorkFactory,
    clause: ClauseId,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    engine = factory.engine
    clock = Clock()
    rule_id = rule(engine)
    old = through_review(factory, clock, rule_id, clause)
    execute(engine, "DELETE FROM outbox_event")
    new = version(engine, rule_id, 2, effective_from=date(2026, 11, 1))
    with factory() as uow:
        uow.relations.add(
            RuleRelation(new, RelationKind.WITHDRAWS, old, clause),
            relation_id=uuid4(),
            candidate_id=None,
        )
    AddCitations(factory, clock).run(new, [CitationInput(clause, QUOTE)])
    SubmitForReview(factory, clock).run(new, actor_id=ANALYST)
    ApproveVersion(factory, clock).run(new, actor_id=REVIEWER)
    PublishVersion(factory, enabled=True, clock=clock).run(new, actor_id=ANALYST)
    assert [topic for topic, _, _ in outbox(engine)] == ["rule.published"]
    state = "SELECT status || ' ' || effective_to::text FROM rule_version WHERE id = :id"
    assert scalar(engine, state, id=old.value) == "published 2026-11-01"

    monkeypatch.setenv("CW_DATABASE_URL", database_url)
    monkeypatch.setenv("CW_RULEBOOK_PUBLISH_ENABLED", "false")
    assert transitions_main([]) == 0
    assert "nothing moved" in capsys.readouterr().out
    monkeypatch.setenv("CW_RULEBOOK_PUBLISH_ENABLED", "true")
    assert transitions_main(["--as-of", "2026-01-01"]) == 0
    assert "0 moved" in capsys.readouterr().out
    assert scalar(engine, state, id=old.value) == "published 2026-11-01"

    sweep = ApplyDueTransitions(
        factory, enabled=True, clock=Clock(datetime(2026, 10, 31, 18, 30, tzinfo=UTC))
    )
    (moved,) = sweep.run().transitions
    assert (moved.target_id, moved.replacing_id) == (old, new)
    assert scalar(engine, state, id=old.value) == "withdrawn 2026-11-01"
    assert [topic for topic, _, _ in outbox(engine)] == ["rule.published", "rule.withdrawn"]
    cause = scalar(
        engine,
        "SELECT caused_by_rule_version_id FROM rule_version_decision"
        " WHERE rule_version_id = :id AND action = 'withdrawn'",
        id=old.value,
    )
    assert cause == new.value
    assert sweep.run().transitions == ()
