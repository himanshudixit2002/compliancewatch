"""The rulebook's erasure on Postgres, as its own role cw_rulebook: it deletes no regulatory
row, nulls the tenant and empties the masked text of the tenant's error report reviews (the
decision stays), prunes the tenant's published outbox rows (the error_report.decided a decision
wrote, once the relay published it) and keeps the pending ones, and its answer
(tenant.data.erased of the tenant), audit entry and erased marker commit on the consumer's
connection under the tenant's setting. The catalog shows the tables of the schema with a tenant
column are the reviews, the outbox and the marker, the last two retained with a reason: when a
migration gives another rulebook table a tenant column, this fails until the eraser erases or
retains it. Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.erasure import DeletionRequest
from domain_kernel.ids import CorrelationId, EventId, ObligationId, RuleId, TenantId, UserId
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.erasure import erase_and_record
from py_common.erasure_testing import assert_nothing_left, tenant_columns
from py_common.outbox.schema import STATUS_PENDING, STATUS_PUBLISHED
from rulebook.application.error_reports import DecideErrorReview
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.error_reports import (
    ErrorCategory,
    ErrorOutcome,
    ErrorReview,
    ErrorReviewQuery,
    review_id_for,
)
from rulebook.infrastructure.erasure import PostgresRulebookEraser
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.seed_repository import SqlAlchemySeedRepository

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"
NOW = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)


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
        apply_roles(url)
        yield url


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def review_of(
    factory: PostgresKnowledgeUnitOfWorkFactory, tenant: TenantId, text: str
) -> ErrorReview:
    """A review of a report of ``tenant`` about the seed's first draft, stored."""
    with factory() as uow:
        rule_id = uow.rules.rule_id("gstr3b_monthly")
        assert rule_id is not None
        versions = uow.rule_versions.of_rule(RuleId(rule_id))
        report_id = uuid4()
        review = ErrorReview(
            review_id=review_id_for(report_id),
            report_id=report_id,
            tenant_id=tenant,
            obligation_id=ObligationId.new(),
            rule_version_id=versions[0].rule_version_id,
            category=ErrorCategory.DUE_DATE,
            description_masked=text,
            received_at=NOW,
        )
        assert uow.error_reviews.add(review)
    return review


def test_the_rulebook_pseudonymises_the_tenants_reviews_and_keeps_the_rest(
    engine: Engine, database_url: str
) -> None:
    factory = PostgresKnowledgeUnitOfWorkFactory.from_url(database_url)
    SqlAlchemySeedRepository(factory.engine).apply(load_calendar(ontology_package.load()))
    tenant, other = TenantId.new(), TenantId.new()
    ours = review_of(factory, tenant, "Example: the due date reads the 20th; call [PHONE].")
    theirs = review_of(factory, other, "Example: the step list names a form we do not file.")
    decide = DecideErrorReview(factory, lambda: NOW)
    decide.run(ours.report_id, ErrorOutcome.REJECTED, by=UserId(UUID(int=41)), notes="n")
    decide.run(theirs.report_id, ErrorOutcome.REJECTED, by=UserId(UUID(int=41)), notes="theirs")
    with engine.begin() as connection:
        # The relay published both decisions: the rows stay for auditing until pruned.
        published = connection.execute(
            text(
                "UPDATE outbox_event SET status = :published, published_at = :at "
                "WHERE topic = 'error_report.decided' AND tenant_id IN (:ours, :theirs)"
            ),
            {"published": STATUS_PUBLISHED, "at": NOW, "ours": tenant.value, "theirs": other.value},
        )
        assert published.rowcount == 2
    request = DeletionRequest(
        event_id=EventId.new(),
        tenant_id=tenant,
        correlation_id=CorrelationId.new(),
        requested_at=NOW,
        deadline_at=NOW + timedelta(days=30),
    )
    with engine.begin() as connection:
        answer = erase_and_record(
            "rulebook", PostgresRulebookEraser(connection), request, clock=lambda: NOW
        )
    assert dict(answer.tables) == {"error_report_review": 1, "outbox_event": 1}
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT topic, status, message->'payload'->>'service' FROM outbox_event "
                "WHERE tenant_id = :t ORDER BY topic"
            ),
            {"t": tenant.value},
        ).all()
        assert [tuple(row) for row in rows] == [
            ("tenant.data.erased", STATUS_PENDING, "rulebook")
        ], "the published decision is pruned; the answer waits for the relay"
        others = connection.execute(
            text("SELECT topic, status FROM outbox_event WHERE tenant_id = :t"),
            {"t": other.value},
        ).all()
        assert [tuple(row) for row in others] == [("error_report.decided", STATUS_PUBLISHED)], (
            "the other tenant's published decision stays"
        )
    with factory() as uow:
        erased = uow.error_reviews.by_report(ours.report_id)
        kept = uow.error_reviews.by_report(theirs.report_id)
        decided = uow.error_reviews.page(ErrorReviewQuery(status=None, limit=10))
    factory.engine.dispose()
    assert erased is not None
    assert kept is not None
    assert (erased.tenant_id, erased.description_masked) == (None, "")
    assert (erased.status.value, erased.notes, erased.decided_by) == (
        "rejected",
        "n",
        UserId(UUID(int=41)),
    ), "the decision stays as a fact about the rule"
    assert (kept.tenant_id, kept.description_masked, kept.status.value, kept.notes) == (
        other,
        theirs.description_masked,
        "rejected",
        "theirs",
    ), "the other tenant's review keeps its tenant and text"
    assert {review.report_id for review in decided} >= {ours.report_id, theirs.report_id}
    owner = create_engine(database_url)
    with owner.connect() as connection:
        assert {table for table, _ in tenant_columns(connection, SCHEMA)} == {
            "error_report_review",
            "erased_tenant",
            "outbox_event",
        }
        retained = assert_nothing_left(connection, SCHEMA, tenant, answer)
    owner.dispose()
    assert retained == {"erased_tenant.tenant_id": 1, "outbox_event.tenant_id": 1}
