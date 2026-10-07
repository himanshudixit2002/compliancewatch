"""The engine's erasure on Postgres, as its own role cw_applicability under forced row-level
security: the append-only decisions go only inside an erasure, the tenant's review items,
decisions and directory entries go and another tenant's stay. Needs Docker."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.domain.repository import UnitOfWorkFactory
from applicability_engine.domain.review import ReviewItem, ReviewReason
from applicability_engine.infrastructure.erasure import TABLES, PostgresEngineEraser
from applicability_engine.infrastructure.repository import PostgresUnitOfWorkFactory
from domain_kernel.confidence import CERTAIN, ZERO
from domain_kernel.erasure import DeletionRequest
from domain_kernel.ids import (
    BusinessId,
    CorrelationId,
    DecisionId,
    EventId,
    RuleVersionId,
    TenantId,
)
from domain_kernel.ontology import AttributeLevel
from domain_kernel.operators import Operator
from domain_kernel.predicates import Applicability, Predicate, PredicateResult
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.erasure import count_rows, erase_and_record

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "applicability"
START = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)

REGULAR = Predicate("registration_type", Operator.EQ, "regular")


def decision(tenant: TenantId, minutes: int, *, unsure: bool) -> Decision:
    result = Applicability.UNSURE if unsure else Applicability.APPLIES
    return Decision(
        decision_id=DecisionId.new(),
        tenant_id=tenant,
        business_id=BusinessId.new(),
        rule_version_id=RuleVersionId.new(),
        result=result,
        confidence=ZERO if unsure else CERTAIN,
        evaluated=(PredicateResult(REGULAR, result, ZERO if unsure else CERTAIN, "synthetic"),),
        profile_version=1,
        decided_at=START + timedelta(minutes=minutes),
        trigger=Trigger.PROFILE_UPDATED,
        as_of_fy=None,
    )


def keep(factory: UnitOfWorkFactory, tenant: TenantId, count: int) -> None:
    """``count`` decisions of the tenant, every other one unsure with its open review item, and
    a directory entry per business."""
    with factory(tenant) as uow:
        for index in range(count):
            made = decision(tenant, index, unsure=bool(index % 2))
            uow.decisions.add(made)
            uow.directory.add(
                DirectoryEntry(
                    tenant, made.business_id, AttributeLevel.ENTITY, None, made.business_id
                )
            )
            if index % 2:
                uow.reviews.add(ReviewItem.open(made, ReviewReason.FREE_TEXT))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            install_audit_table(connection)
        admin.dispose()
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        apply_roles(url)
        engine = create_engine(as_role(url, SCHEMA))
        yield engine
        engine.dispose()


def counts(engine: Engine, tenant: TenantId) -> dict[str, int]:
    with engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        return {table: count_rows(connection, table, tenant) for table in TABLES}


def refused_outside_an_erasure(engine: Engine, tenant: TenantId) -> bool:
    try:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)}
            )
            connection.execute(text("DELETE FROM applicability_decision"))
    except DBAPIError:
        return True
    return False


def test_the_tenant_s_decisions_go_and_another_s_stay(engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(engine)
    tenant, other = TenantId.new(), TenantId.new()
    keep(factory, tenant, 4)
    keep(factory, other, 3)
    before, theirs = counts(engine, tenant), counts(engine, other)
    assert (before["applicability_decision"], before["review_item"]) == (4, 2)
    assert refused_outside_an_erasure(engine, tenant), "decisions stay append-only"
    request = DeletionRequest(
        event_id=EventId.new(),
        tenant_id=tenant,
        correlation_id=CorrelationId.new(),
        requested_at=START,
        deadline_at=START + timedelta(days=30),
    )
    with engine.begin() as connection:
        answer = erase_and_record(
            "applicability-engine", PostgresEngineEraser(connection), request, clock=lambda: START
        )
    assert {table: answer.tables[table] for table in TABLES} == before
    assert counts(engine, tenant) == dict.fromkeys(TABLES, 0)
    assert counts(engine, other) == theirs, "another tenant's rows stay"
