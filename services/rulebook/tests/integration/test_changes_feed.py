"""The changes feed on Postgres, read by the rulebook's own role, ``cw_rulebook`` as
infra/dev/postgres/roles.sql makes it, which owns nothing and is not a superuser:
publications, a supersession, a withdrawal and a deadline change from the decision log, the
deadline change's id the same as the domain derives it, and the pages, filters and order. The
versions are published through the use cases as the database owner. Needs Docker."""

import hashlib
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import ClauseId, RuleId, RuleVersionId, SourceId, UserId
from domain_kernel.knowledge import EntityType, RelationKind, RuleRelation
from py_common.db_roles import apply_roles, as_role
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
from rulebook.domain.changes import ChangeQuery, RuleChangeKind, deadline_change_id
from rulebook.domain.documents import StoredDocument
from rulebook.domain.relations import RelationCandidate
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
TEXT = (
    "The due date for furnishing the return in FORM GSTR-3B for the month of September, 2026 "
    "is extended till the 27th day of October, 2026."
)
QUOTE = "furnishing the return in FORM GSTR-3B for the month of September, 2026"
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
def owner(database_url: str) -> Iterator[PostgresKnowledgeUnitOfWorkFactory]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
    apply_roles(database_url)
    factory = PostgresKnowledgeUnitOfWorkFactory.from_url(database_url)
    yield factory
    factory.engine.dispose()


@pytest.fixture(scope="module")
def reader(
    database_url: str, owner: PostgresKnowledgeUnitOfWorkFactory
) -> Iterator[PostgresKnowledgeUnitOfWorkFactory]:
    factory = PostgresKnowledgeUnitOfWorkFactory.from_url(as_role(database_url, SCHEMA))
    with factory.engine.connect() as connection:
        superuser = "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        assert connection.execute(text(superuser)).scalar_one() is False
    yield factory
    factory.engine.dispose()


def execute(engine: Engine, statement: str, **params: object) -> None:
    with engine.begin() as connection:
        connection.execute(text(statement), params)


def clause_of(owner: PostgresKnowledgeUnitOfWorkFactory) -> ClauseId:
    digest = hashlib.sha256(b"changes feed").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(owner).run(
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
            fetched_at=NOW,
            published_at=date(2026, 9, 30),
        ),
        [Clause("en.p1", TEXT)],
    )
    return clause_id_for(document_id, "en.p1")


def rule(engine: Engine, key: str, regulator: str = "CBIC") -> RuleId:
    rule_id = RuleId(uuid4())
    execute(
        engine,
        "INSERT INTO rule (id, rule_key, regulator, level) VALUES (:id, :key, :regulator,"
        " 'registration')",
        id=rule_id.value,
        key=key,
        regulator=regulator,
    )
    return rule_id


def draft(engine: Engine, rule_id: RuleId, number: int, effective_from: date) -> RuleVersionId:
    version_id = RuleVersionId(uuid4())
    execute(
        engine,
        "INSERT INTO rule_version (id, rule_id, version, status, title, specification,"
        " obligation_template, effective_from) VALUES (:id, :rule, :number, 'draft', :title,"
        " CAST(:spec AS jsonb), '{}', :start)",
        id=version_id.value,
        rule=rule_id.value,
        number=number,
        title=f"version {number} (example)",
        spec=SPECIFICATION,
        start=effective_from,
    )
    return version_id


def publish(
    owner: PostgresKnowledgeUnitOfWorkFactory,
    clock: Clock,
    version_id: RuleVersionId,
    clause: ClauseId,
) -> None:
    AddCitations(owner, clock).run(version_id, [CitationInput(clause, QUOTE)])
    SubmitForReview(owner, clock).run(version_id, actor_id=ANALYST)
    ApproveVersion(owner, clock).run(version_id, actor_id=REVIEWER)
    PublishVersion(owner, enabled=True, clock=clock).run(version_id, actor_id=ANALYST)


def relate(
    owner: PostgresKnowledgeUnitOfWorkFactory,
    x: RuleVersionId,
    kind: RelationKind,
    y: RuleVersionId,
    clause: ClauseId,
    candidate_id: UUID | None = None,
) -> UUID:
    relation_id = uuid4()
    with owner() as uow:
        uow.relations.add(
            RuleRelation(x, kind, y, clause), relation_id=relation_id, candidate_id=candidate_id
        )
    return relation_id


def extension_candidate(owner: PostgresKnowledgeUnitOfWorkFactory, clause: ClauseId) -> UUID:
    candidate_id = uuid4()
    with owner() as uow:
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
    return candidate_id


def test_the_feed_reads_every_kind_of_change_in_pages(
    owner: PostgresKnowledgeUnitOfWorkFactory, reader: PostgresKnowledgeUnitOfWorkFactory
) -> None:
    clock = Clock()
    engine = owner.engine
    clause = clause_of(owner)

    monthly_rule = rule(engine, "gstr1_monthly")
    old = draft(engine, monthly_rule, 1, date(2026, 4, 1))
    publish(owner, clock, old, clause)
    new = draft(engine, monthly_rule, 2, date(2026, 7, 1))
    relate(owner, new, RelationKind.SUPERSEDES, old, clause)
    publish(owner, clock, new, clause)

    target = draft(engine, rule(engine, "gstr3b_monthly"), 1, date(2026, 4, 1))
    publish(owner, clock, target, clause)
    extension = draft(engine, rule(engine, "gstr3b_extension", "GSTN"), 1, date(2026, 7, 1))
    relation_id = relate(
        owner,
        extension,
        RelationKind.EXTENDS_DEADLINE,
        target,
        clause,
        extension_candidate(owner, clause),
    )
    publish(owner, clock, extension, clause)
    WithdrawVersion(owner, enabled=True, clock=clock).run(
        extension, actor_id=ANALYST, note="rescinded (example)"
    )

    every = ListChanges(reader).run(ChangeQuery(limit=100))
    pairs = [(c.entry.kind, c.entry.rule_version_id) for c in every]
    assert Counter(pairs) == Counter(
        [
            (RuleChangeKind.PUBLISHED, old),
            (RuleChangeKind.PUBLISHED, new),
            (RuleChangeKind.SUPERSEDED, old),
            (RuleChangeKind.PUBLISHED, target),
            (RuleChangeKind.PUBLISHED, extension),
            (RuleChangeKind.DEADLINE_CHANGED, target),
            (RuleChangeKind.WITHDRAWN, extension),
        ]
    )
    keys = [(c.entry.changed_at, c.entry.change_id) for c in every]
    assert keys == sorted(keys, reverse=True), "newest first, then by change id"
    assert (pairs[0], pairs[-1]) == (
        (RuleChangeKind.WITHDRAWN, extension),
        (RuleChangeKind.PUBLISHED, old),
    )
    by_kind = {(c.entry.kind, c.entry.rule_version_id): c for c in every}
    moved = by_kind[(RuleChangeKind.DEADLINE_CHANGED, target)]
    published = by_kind[(RuleChangeKind.PUBLISHED, extension)]
    assert moved.entry.change_id == deadline_change_id(published.entry.change_id, relation_id)
    assert (moved.entry.caused_by, moved.entry.period_label, moved.entry.new_due_on) == (
        extension,
        "2026-09",
        date(2026, 10, 27),
    )
    assert moved.entry.evidence_clause_id == clause
    assert moved.entry.changed_at == published.entry.changed_at
    superseded = by_kind[(RuleChangeKind.SUPERSEDED, old)]
    assert superseded.entry.changed_at == by_kind[(RuleChangeKind.PUBLISHED, new)].entry.changed_at
    assert (superseded.entry.caused_by, superseded.version.status.value) == (new, "superseded")
    assert superseded.approved_by == (REVIEWER,)
    assert [c.quote for c in superseded.citations] == [QUOTE]
    replacing = by_kind[(RuleChangeKind.PUBLISHED, new)]
    assert [(r.relation, r.to_rule_version_id) for r in replacing.relations] == [
        (RelationKind.SUPERSEDES, old)
    ]
    withdrawn = by_kind[(RuleChangeKind.WITHDRAWN, extension)]
    assert withdrawn.entry.caused_by is None

    pages = []
    after = None
    while True:
        page = ListChanges(reader).run(ChangeQuery(limit=3, after=after))
        pages.append(page)
        if len(page) < 3:
            break
        after = page[-1].entry.key
    assert [c.entry for page in pages for c in page] == [c.entry for c in every]

    since = by_kind[(RuleChangeKind.PUBLISHED, target)].entry.changed_at
    recent = ListChanges(reader).run(ChangeQuery(limit=100, since=since))
    assert [c.entry for c in recent] == [c.entry for c in every[:4]]
    gstn = ListChanges(reader).run(ChangeQuery(limit=100, regulator="GSTN"))
    assert [(c.entry.kind, c.entry.rule_version_id) for c in gstn] == [
        (RuleChangeKind.WITHDRAWN, extension),
        (RuleChangeKind.PUBLISHED, extension),
    ]
