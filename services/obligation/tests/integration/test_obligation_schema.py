"""Migration 0001 on Postgres: the table, row-level security by tenant, the unit of work with
the outbox, the use cases end to end, and the listing a read goes through. Needs Docker.

The use cases run as obligation's own role, cw_obligation as infra/dev/postgres/roles.sql makes
it, not the container's superuser: a superuser bypasses row-level security whatever the table
says, so the service's runtime role must never be one.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import BusinessId, DecisionId, TenantId
from domain_kernel.recurrence import Recurrence
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.application.changes import (
    ApplyDeadlineChange,
    CloseObligation,
    DeadlineChange,
    WithdrawRule,
)
from obligation.application.materialise import IST, MaterialiseObligations, MaterialiseRequest
from obligation.application.queries import ListObligations, ObligationQuery
from obligation.domain.events import RescheduleReason
from obligation.domain.model import DueWindow
from obligation.infrastructure.repository import PostgresUnitOfWorkFactory
from obligation.testing import rule
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
TABLES = {
    "obligation",
    "obligation_change",
    "obligation_comment",
    "obligation_decision",
    "obligation_reminder",
    "obligation_tenant",
    "rule_version_ref",
    "outbox_event",
    "processed_event",
    "idempotency_key",
    "erased_tenant",
    "alembic_version",
}


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            # audit.event, which identity's migrations make: every change writes its entry.
            install_audit_table(connection)
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def migrated(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        config = Config(str(SERVICE_DIR / "alembic.ini"))
        command.upgrade(config, "head")
        yield config


@pytest.fixture(scope="module")
def engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    """An engine for cw_obligation, which owns nothing and is not a superuser, so the policy
    applies."""
    apply_roles(database_url)
    url = as_role(database_url, SCHEMA)
    engine = create_engine(url)
    yield engine
    engine.dispose()


def test_migration_creates_the_tables_with_row_level_security(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(inspector.get_table_names(schema=SCHEMA)) == TABLES
    with engine.connect() as connection:
        rls = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'obligation' AND relnamespace = CAST(:schema AS regnamespace)"
            ),
            {"schema": SCHEMA},
        ).one()
        policies: list[str] = list(
            connection.execute(
                text("SELECT policyname FROM pg_policies WHERE tablename = 'obligation'")
            ).scalars()
        )
    assert tuple(rls) == (True, True)
    assert policies == ["obligation_tenant_isolation"]


def test_the_container_user_is_a_superuser_and_the_app_role_is_not(
    engine: Engine, app_engine: Engine
) -> None:
    query = text("SELECT usesuper FROM pg_user WHERE usename = current_user")
    with engine.connect() as connection:
        container_user_is_super: bool = connection.execute(query).scalar_one()
    with app_engine.connect() as connection:
        app_role_is_super: bool = connection.execute(query).scalar_one()
    assert container_user_is_super
    assert not app_role_is_super


def test_use_cases_run_end_to_end_with_the_outbox(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    the_rule = rule()
    request = MaterialiseRequest(
        tenant, BusinessId.new(), DecisionId.new(), the_rule, date(2026, 9, 28)
    )
    first = MaterialiseObligations(factory, window=2).run(request)
    assert len(first.created) == 2
    assert MaterialiseObligations(factory, window=2).run(request).existing == 2

    moved = ApplyDeadlineChange(factory).run(
        DeadlineChange(
            tenant,
            the_rule.rule_version_id,
            "2026-09",
            date(2026, 10, 25),
            RescheduleReason.DEADLINE_EXTENDED,
        )
    )
    assert len(moved.changed) == 1
    with factory(tenant) as uow:
        open_ones = uow.obligations.open_for_rule_version(the_rule.rule_version_id)
        assert [o.period_label for o in open_ones] == ["2026-09", "2026-10"]
        september = open_ones[0]
        assert september.due_at is not None
        assert september.due_at.astimezone(IST).date() == date(2026, 10, 25)
        assert uow.obligations.get(september.id) == september

    withdrawn = WithdrawRule(factory).run(tenant, the_rule.rule_version_id)
    assert len(withdrawn.changed) == 2
    with factory(tenant) as uow:
        assert uow.obligations.open_for_rule_version(the_rule.rule_version_id) == []
        closed = uow.obligations.get(september.id)
        assert closed is not None
        assert closed.status is ObligationStatus.CLOSED_NOT_APPLICABLE

    with factory(other) as uow:
        assert uow.obligations.get(september.id) is None, "row-level security hides other tenants"
        assert uow.obligations.open_for_rule_version(the_rule.rule_version_id) == []

    with app_engine.connect() as connection:
        without_setting: int = connection.execute(
            text("SELECT count(*) FROM obligation")
        ).scalar_one()
        topics = connection.execute(
            text("SELECT topic, count(*) FROM outbox_event GROUP BY topic ORDER BY topic")
        ).all()
    assert without_setting == 0, "no tenant setting means no rows for the app role"
    assert [tuple(row) for row in topics] == [
        ("obligation.closed", 2),
        ("obligation.created", 2),
        ("obligation.rescheduled", 1),
    ]


def test_the_return_still_due_is_stored_once_and_nothing_overdue(app_engine: Engine) -> None:
    """Decided on 5 October, a business gets September, due 20 October; a replay and the window
    of 25 October add nothing; a business decided on 25 October starts with October."""
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, early, late, the_rule = TenantId.new(), BusinessId.new(), BusinessId.new(), rule()
    use_case = MaterialiseObligations(factory, window=2)

    def run(business: BusinessId, day: date) -> tuple[int, int]:
        result = use_case.run(MaterialiseRequest(tenant, business, DecisionId.new(), the_rule, day))
        return len(result.created), result.existing

    days = (date(2026, 10, 5), date(2026, 10, 5), date(2026, 10, 25))
    assert [run(early, day) for day in days] == [(3, 0), (0, 3), (0, 2)]
    assert run(late, date(2026, 10, 25)) == (2, 0)

    def due(business: BusinessId) -> list[tuple[str | None, date | None]]:
        return [
            (o.period_label, None if o.due_at is None else o.due_at.astimezone(IST).date())
            for o in ListObligations(factory).run(ObligationQuery(tenant, business))
        ]

    assert due(early) == [
        ("2026-09", date(2026, 10, 20)),
        ("2026-10", date(2026, 11, 20)),
        ("2026-11", date(2026, 12, 20)),
    ]
    assert due(late) == [("2026-10", date(2026, 11, 20)), ("2026-11", date(2026, 12, 20))]


def test_listing_a_business_under_row_level_security(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    business, other_business = BusinessId.new(), BusinessId.new()
    on_the_20th, on_the_11th, undated = (
        rule(),
        rule(recurrence=Recurrence.monthly(11)),
        rule(recurrence=None),
    )
    for the_rule in (on_the_20th, undated, on_the_11th):
        MaterialiseObligations(factory, window=2).run(
            MaterialiseRequest(tenant, business, DecisionId.new(), the_rule, date(2026, 9, 28))
        )
    MaterialiseObligations(factory, window=2).run(
        MaterialiseRequest(other, other_business, DecisionId.new(), on_the_20th, date(2026, 9, 28))
    )
    list_obligations = ListObligations(factory)

    def due_days(query: ObligationQuery) -> list[date | None]:
        return [
            None if o.due_at is None else o.due_at.astimezone(IST).date()
            for o in list_obligations.run(query)
        ]

    everything = list_obligations.run(ObligationQuery(tenant, business))
    assert [None if o.due_at is None else o.due_at.astimezone(IST).date() for o in everything] == [
        date(2026, 10, 11),
        date(2026, 10, 20),
        date(2026, 11, 11),
        date(2026, 11, 20),
        None,
    ]
    assert {o.tenant_id for o in everything} == {tenant}
    assert due_days(
        ObligationQuery(tenant, business, DueWindow(date(2026, 10, 20), date(2026, 11, 11)))
    ) == [date(2026, 10, 20), date(2026, 11, 11)]
    assert due_days(
        ObligationQuery(tenant, business, rule_version_id=on_the_11th.rule_version_id)
    ) == [date(2026, 10, 11), date(2026, 11, 11)]
    assert due_days(ObligationQuery(tenant, business, limit=2)) == [
        date(2026, 10, 11),
        date(2026, 10, 20),
    ]

    CloseObligation(factory).run(tenant, everything[0].id, ClosureReason.COMPLETED)
    (closed,) = list_obligations.run(
        ObligationQuery(tenant, business, DueWindow(due_to=date(2026, 10, 11)))
    )
    assert closed.status is ObligationStatus.DONE
    assert closed == list_obligations.run(ObligationQuery(tenant, business))[0]

    assert list_obligations.run(ObligationQuery(tenant, other_business)) == (), (
        "row-level security hides the other tenant's rows"
    )
    assert list_obligations.run(ObligationQuery(other, business)) == ()
    other_rows = list_obligations.run(ObligationQuery(other, other_business))
    assert [o.period_label for o in other_rows] == ["2026-09", "2026-10"]
    assert {o.tenant_id for o in other_rows} == {other}


def test_downgrade_and_upgrade(migrated: Config, engine: Engine) -> None:
    command.downgrade(migrated, "base")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == {"alembic_version"}
    command.upgrade(migrated, "head")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == TABLES
