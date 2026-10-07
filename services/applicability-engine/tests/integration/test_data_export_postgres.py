"""The tenant's data export on Postgres: two tenants' decisions and review items, the export for
one of them read as the engine's own role, cw_applicability, under row-level security, a page at
a time, holding that tenant's rows only. Needs Docker.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from testcontainers.community.postgres import PostgresContainer

from applicability_engine.application.export import DECISIONS, REVIEW_ITEMS, ExportTenantData
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.domain.review import ReviewItem, ReviewReason
from applicability_engine.infrastructure.repository import PostgresUnitOfWorkFactory
from domain_kernel.confidence import CERTAIN, ZERO
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.operators import Operator
from domain_kernel.predicates import Applicability, Predicate, PredicateResult
from py_common.db_roles import apply_roles, as_role

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "applicability"
START = datetime(2000, 4, 1, 9, 0, tzinfo=UTC)
GENERATED = datetime(2000, 6, 1, 12, 0, tzinfo=UTC)
REGULAR = Predicate("registration_type", Operator.EQ, "regular")
FREE_TEXT = Predicate("business_category", free_text="Example premises shared with a hotel")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as env:
            env.setenv("CW_DATABASE_URL", url)
            env.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
        yield url


@pytest.fixture(scope="module")
def app_engine(database_url: str) -> Iterator[Engine]:
    """An engine for cw_applicability, which owns nothing and is not a superuser, so the policy
    applies."""
    apply_roles(database_url)
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def decision(tenant: TenantId, result: Applicability, minutes: int) -> Decision:
    unsure = result is Applicability.UNSURE
    return Decision(
        decision_id=DecisionId.new(),
        tenant_id=tenant,
        business_id=BusinessId.new(),
        rule_version_id=RuleVersionId.new(),
        result=result,
        confidence=ZERO if unsure else CERTAIN,
        evaluated=(
            PredicateResult(
                FREE_TEXT if unsure else REGULAR,
                result,
                ZERO if unsure else CERTAIN,
                "nobody judged it" if unsure else "registration_type = regular holds",
            ),
        ),
        profile_version=1,
        decided_at=START + timedelta(minutes=minutes),
        trigger=Trigger.PROFILE_UPDATED,
        as_of_fy=None,
    )


def store(factory: PostgresUnitOfWorkFactory, tenant: TenantId, count: int) -> list[Decision]:
    """``count`` decisions of the tenant, every other one unsure with its open review item."""
    made = [
        decision(tenant, Applicability.UNSURE if index % 2 else Applicability.APPLIES, index % 3)
        for index in range(count)
    ]
    with factory(tenant) as uow:
        for each in made:
            uow.decisions.add(each)
            if each.result is Applicability.UNSURE:
                uow.reviews.add(ReviewItem.open(each, ReviewReason.FREE_TEXT))
    return made


def test_the_export_as_the_service_role_holds_one_tenants_rows(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    first, second = TenantId.new(), TenantId.new()
    mine = store(factory, first, 7)
    theirs = store(factory, second, 4)

    export = ExportTenantData(factory, clock=lambda: GENERATED, page_size=2).run(first)

    assert (export.service, export.tenant_id, export.generated_at) == (
        "applicability-engine",
        first,
        GENERATED,
    )
    expected = sorted(mine, key=lambda each: (each.decided_at, each.decision_id.value))
    assert [row["decision_id"] for row in export.sections[DECISIONS]] == [
        str(each.decision_id) for each in expected
    ]
    items = export.sections[REVIEW_ITEMS]
    assert len(items) == 3
    assert {row["tenant_id"] for row in [*export.sections[DECISIONS], *items]} == {str(first)}
    assert {row["decision_id"] for row in items} <= {str(each.decision_id) for each in mine}
    flattened = repr(export.sections)
    assert str(second) not in flattened
    assert not any(str(each.decision_id) in flattened for each in theirs)
    assert export.sections == ExportTenantData(factory, clock=lambda: GENERATED).run(first).sections

    nobody = ExportTenantData(factory).run(TenantId.new())
    assert nobody.sections == {DECISIONS: [], REVIEW_ITEMS: []}
