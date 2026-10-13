"""Migration 0013 on Postgres: ``error_report_review`` without row-level security, its unique
report id, its foreign keys to ``rule_version`` and its state check, and the use cases on the
Postgres unit of work: the intake once per report, the queue's order (by the rule version's id as
text, then arrival, then id) with its keyset pages and the groups joined to the versions, and a
decision committed with its outbox row keyed by the reporting tenant and its audit entry. Needs
Docker."""

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.ids import ClauseId, RuleId, RuleVersionId, SourceId, TenantId, UserId
from domain_kernel.knowledge import RelationKind, RuleRelation
from py_common.audit.testing import install_audit_table
from rulebook.application.documents import RegisterDocument
from rulebook.application.error_reports import (
    DECIDED_ACTION,
    DecideErrorReview,
    IntakeErrorReport,
    ListErrorReviews,
)
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.documents import StoredDocument
from rulebook.domain.error_reports import (
    ErrorOutcome,
    ErrorReviewKey,
    ErrorReviewStatus,
    queue_position,
)
from rulebook.domain.errors import (
    CorrectingVersionRequiredError,
    ErrorReviewClosedError,
    UnknownRuleVersionError,
)
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.seed_repository import SqlAlchemySeedRepository

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
TABLE = "error_report_review"
EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
EXAMPLE = EXAMPLES / "error_report.submitted" / "wrong-due-date.json"
START = datetime(2000, 2, 3, 5, 15, tzinfo=UTC)
TENANT = TenantId(UUID("5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a"))
OTHER_TENANT = TenantId(UUID("9d8c7b6a-5f4e-4d3c-8b2a-1a0f9e8d7c6b"))
ANALYST = UserId(UUID(int=71))
MONTHLY = "gstr3b_monthly"
QUARTERLY = "gstr3b_quarterly_group_a"
DIGEST = hashlib.sha256(b"example notice for the error review tables").hexdigest()
DOC = document_id_for(DIGEST)
CLAUSE: ClauseId = clause_id_for(DOC, "en.p1")
CHECKS = {
    "ck_error_report_review_category",
    "ck_error_report_review_status",
    "ck_error_report_review_description",
    "ck_error_report_review_notes",
    "ck_error_report_review_state",
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
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        yield url


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def factory(database_url: str) -> Iterator[PostgresKnowledgeUnitOfWorkFactory]:
    factory = PostgresKnowledgeUnitOfWorkFactory.from_url(database_url)
    SqlAlchemySeedRepository(factory.engine).apply(load_calendar(ontology_package.load()))
    RegisterDocument(factory).run(
        StoredDocument(
            document_id=DOC,
            source_id=SourceId(UUID(int=7)),
            sha256=DIGEST,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/notice.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=START,
            published_at=date(2000, 1, 15),
        ),
        [Clause("en.p1", "Example notice: the example statement is due on the 25th.")],
    )
    yield factory
    factory.engine.dispose()


def version_of(factory: PostgresKnowledgeUnitOfWorkFactory, rule_key: str) -> RuleVersionId:
    with factory() as uow:
        rule_id = uow.rules.rule_id(rule_key)
        assert rule_id is not None
        (version,) = uow.rule_versions.of_rule(RuleId(rule_id))
    return version.rule_version_id


def payload(version: RuleVersionId, **overrides: Any) -> dict[str, Any]:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))["payload"]
    data["rule_version_id"] = str(version)
    data["report_id"] = str(uuid4())
    data.update(overrides)
    return dict(data)


def test_the_table_has_no_row_level_security_and_its_keys(engine: Engine) -> None:
    inspector = inspect(engine)
    assert TABLE in inspector.get_table_names(schema=SCHEMA)
    assert {c["name"] for c in inspector.get_check_constraints(TABLE, schema=SCHEMA)} >= CHECKS
    assert {i["name"] for i in inspector.get_indexes(TABLE, schema=SCHEMA)} >= {
        "ix_error_report_review_queue",
        "ix_error_report_review_tenant",
    }, "the queue's and the erasure's indexes (the unique report id has one of its own)"
    assert [u["name"] for u in inspector.get_unique_constraints(TABLE, schema=SCHEMA)] == [
        "uq_error_report_review_report_id"
    ]
    foreign_keys = inspector.get_foreign_keys(TABLE, schema=SCHEMA)
    assert {(fk["constrained_columns"][0], fk["referred_table"]) for fk in foreign_keys} == {
        ("rule_version_id", "rule_version"),
        ("correcting_rule_version_id", "rule_version"),
    }
    with engine.connect() as connection:
        rls = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = :table AND relnamespace = CAST(:schema AS regnamespace)"
            ),
            {"table": TABLE, "schema": SCHEMA},
        ).one()
    assert tuple(rls) == (False, False), "regulatory review shared by every tenant"


def test_the_intake_keeps_one_review_per_report_and_the_queue_pages_in_order(
    factory: PostgresKnowledgeUnitOfWorkFactory,
) -> None:
    monthly, quarterly = version_of(factory, MONTHLY), version_of(factory, QUARTERLY)
    clock = Clock()
    intake = IntakeErrorReport(factory, clock)
    first = payload(monthly)
    reviews = [
        intake.run(TENANT, first).review,
        intake.run(OTHER_TENANT, payload(quarterly, category="steps")).review,
        intake.run(TENANT, payload(monthly, category="citation")).review,
    ]
    again = intake.run(TENANT, {**first, "description": "Example: sent again."})
    assert not again.created
    assert again.review == reviews[0], "the first delivery wins"
    with pytest.raises(UnknownRuleVersionError):
        intake.run(TENANT, payload(RuleVersionId.new()))
    assert "[PHONE]" in reviews[0].description_masked

    expected = sorted(reviews, key=queue_position)
    listing = ListErrorReviews(factory)
    page = listing.run(limit=2)
    assert page == expected[:2]
    assert listing.run(after=ErrorReviewKey.of(page[-1]), limit=2) == expected[2:]
    assert listing.run(rule_version_id=quarterly) == [reviews[1]]
    assert listing.run(status=ErrorReviewStatus.CONFIRMED) == []

    groups = {g.rule_version_id: g for g in listing.groups()}
    assert (groups[monthly].open_count, groups[monthly].rule_key, groups[monthly].version) == (
        2,
        MONTHLY,
        1,
    )
    assert groups[monthly].title, "the version's title from the join"
    assert groups[monthly].oldest_received_at == reviews[0].received_at
    assert groups[quarterly].open_count == 1
    assert [g.rule_version_id for g in listing.groups()] == sorted(groups, key=str)


def test_a_decision_commits_with_its_outbox_row_and_audit_entry(
    factory: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    monthly, quarterly = version_of(factory, MONTHLY), version_of(factory, QUARTERLY)
    clock = Clock(START + timedelta(days=1))
    review = IntakeErrorReport(factory, clock).run(TENANT, payload(monthly)).review
    decide = DecideErrorReview(factory, clock)

    with pytest.raises(CorrectingVersionRequiredError):
        decide.run(
            review.report_id,
            ErrorOutcome.CONFIRMED,
            by=ANALYST,
            correcting_rule_version_id=quarterly,
        )
    with factory() as uow:
        uow.relations.add(
            RuleRelation(quarterly, RelationKind.CORRECTS, monthly, CLAUSE),
            relation_id=uuid4(),
            candidate_id=None,
        )
    decided = decide.run(
        review.report_id,
        ErrorOutcome.CONFIRMED,
        by=ANALYST,
        notes="Example: the other version carries the corrected date.",
        correcting_rule_version_id=quarterly,
    )
    assert (decided.status, decided.decided_by, decided.correcting_rule_version_id) == (
        ErrorReviewStatus.CONFIRMED,
        ANALYST,
        quarterly,
    )
    with pytest.raises(ErrorReviewClosedError):
        decide.run(review.report_id, ErrorOutcome.REJECTED, by=ANALYST)
    with factory() as uow:
        assert uow.error_reviews.by_report(review.report_id) == decided

    with engine.connect() as connection:
        (message,) = connection.execute(
            text(
                "SELECT message FROM outbox_event "
                "WHERE tenant_id = :t AND topic = 'error_report.decided'"
            ),
            {"t": TENANT.value},
        ).scalars()
        entries = connection.execute(
            text("SELECT action, after FROM audit.event WHERE subject_id = :id"),
            {"id": str(review.report_id)},
        ).all()
    payload_out = message["payload"]
    assert (payload_out["outcome"], payload_out["correcting_rule_version_id"]) == (
        "confirmed",
        str(quarterly),
    )
    assert payload_out["report_id"] == str(review.report_id)
    assert [(action, after["status"]) for action, after in entries] == [
        (DECIDED_ACTION, "confirmed")
    ]


def test_the_state_check_refuses_a_confirmation_without_its_version(
    factory: PostgresKnowledgeUnitOfWorkFactory, engine: Engine
) -> None:
    review = IntakeErrorReport(factory).run(TENANT, payload(version_of(factory, MONTHLY))).review
    with (
        pytest.raises(IntegrityError, match="ck_error_report_review_state"),
        engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE error_report_review SET status = 'confirmed', decided_by = :by, "
                "decided_at = :at WHERE id = :id"
            ),
            {"id": review.review_id, "by": ANALYST.value, "at": START},
        )
    with (
        pytest.raises(IntegrityError, match="uq_error_report_review_report_id"),
        engine.begin() as connection,
    ):
        connection.execute(
            text(
                "INSERT INTO error_report_review (id, report_id, tenant_id, obligation_id, "
                "rule_version_id, category, description_masked, received_at) "
                "SELECT :new_id, report_id, tenant_id, obligation_id, rule_version_id, category, "
                "description_masked, received_at FROM error_report_review WHERE id = :id"
            ),
            {"id": review.review_id, "new_id": uuid4()},
        )
