"""Migration 0001 on Postgres: the tables, row-level security by tenant, the append-only guard,
the unit of work with the outbox, and the use cases end to end. Needs Docker.

The use cases run as a plain database role, not the container's superuser: a superuser bypasses
row-level security whatever the table says, so the service's runtime role must never be one.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from applicability_engine.application.evaluate import EvaluateRequest, EvaluateRule
from applicability_engine.application.queries import DecisionQuery, ListDecisions, ReadDecision
from applicability_engine.domain.errors import DecisionNotFoundError
from applicability_engine.domain.model import DecisionKey
from applicability_engine.infrastructure.repository import PostgresUnitOfWorkFactory
from applicability_engine.testing import (
    BUSINESS,
    OTHER_TENANT,
    TENANT,
    MemoryProfiles,
    MemoryRulebook,
    rule_version,
)
from domain_kernel.predicates import Applicability

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "applicability"
TABLE = "applicability_decision"
TABLES = {TABLE, "outbox_event", "idempotency_key", "alembic_version"}
APP_ROLE = "applicability_app"
APP_PASSWORD = "app-role-for-tests"
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
FREE_TEXT = {"attribute": "business_category", "free_text": "Runs a restaurant in a hotel"}


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
    """An engine for a role that owns nothing and is not a superuser, so the policy applies."""
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
        connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "
                f"{SCHEMA} TO {APP_ROLE}"
            )
        )
    admin.dispose()
    url = database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@")
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(app_engine: Engine) -> PostgresUnitOfWorkFactory:
    return PostgresUnitOfWorkFactory(app_engine)


@pytest.fixture
def readers() -> tuple[MemoryProfiles, MemoryRulebook]:
    profiles = MemoryProfiles()
    profiles.put({"registration_type": "regular"}, version=2)
    profiles.put({"registration_type": "regular"}, tenant_id=OTHER_TENANT)
    return profiles, MemoryRulebook()


def evaluator(
    factory: PostgresUnitOfWorkFactory, readers: tuple[MemoryProfiles, MemoryRulebook]
) -> EvaluateRule:
    profiles, rulebook = readers
    return EvaluateRule(factory, profiles, rulebook, ontology_package.load())


def test_migration_creates_the_tables_with_row_level_security(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == TABLES
    with engine.connect() as connection:
        rls = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = :table AND relnamespace = CAST(:schema AS regnamespace)"
            ),
            {"table": TABLE, "schema": SCHEMA},
        ).one()
        policies: list[str] = list(
            connection.execute(
                text("SELECT policyname FROM pg_policies WHERE tablename = :table"),
                {"table": TABLE},
            ).scalars()
        )
    assert tuple(rls) == (True, True)
    assert policies == [f"{TABLE}_tenant_isolation"]


def test_the_app_role_is_not_a_superuser(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        query = text("SELECT usesuper FROM pg_user WHERE usename = current_user")
        assert connection.execute(query).scalar_one() is False


def test_a_decision_and_its_event_commit_together_for_the_tenant_only(
    app_engine: Engine,
    factory: PostgresUnitOfWorkFactory,
    readers: tuple[MemoryProfiles, MemoryRulebook],
) -> None:
    rule = readers[1].put(rule_version({"all_of": [REGULAR, FREE_TEXT]}))
    decision = evaluator(factory, readers).run(
        EvaluateRequest(TENANT, BUSINESS, rule.rule_version_id)
    )
    assert decision.result is Applicability.UNSURE

    read = ReadDecision(factory)
    assert read.run(TENANT, decision.decision_id) == decision
    with pytest.raises(DecisionNotFoundError):
        read.run(OTHER_TENANT, decision.decision_id)

    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT topic, tenant_id, message -> 'payload' FROM outbox_event "
                "WHERE message -> 'payload' ->> 'decision_id' = :id"
            ),
            {"id": str(decision.decision_id)},
        ).all()
    [(topic, tenant, payload)] = rows
    assert (topic, tenant) == ("applicability.decided", TENANT.value)
    assert payload["result"] == "unsure"
    assert payload["needs_review"] is True
    assert payload["profile_version"] == 2


def test_decisions_are_append_only(
    app_engine: Engine,
    factory: PostgresUnitOfWorkFactory,
    readers: tuple[MemoryProfiles, MemoryRulebook],
) -> None:
    rule = readers[1].put(rule_version(REGULAR))
    decision = evaluator(factory, readers).run(
        EvaluateRequest(TENANT, BUSINESS, rule.rule_version_id)
    )
    for statement in (
        f"UPDATE {TABLE} SET result = 'not_applicable' WHERE id = :id",
        f"DELETE FROM {TABLE} WHERE id = :id",
    ):
        with app_engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(TENANT)},
            )
            with pytest.raises(DBAPIError, match="append-only"):
                connection.execute(text(statement), {"id": decision.decision_id.value})


def test_the_listing_pages_newest_first_within_the_tenant(
    factory: PostgresUnitOfWorkFactory, readers: tuple[MemoryProfiles, MemoryRulebook]
) -> None:
    rule = readers[1].put(rule_version(REGULAR))
    evaluate = evaluator(factory, readers)
    made = [evaluate.run(EvaluateRequest(TENANT, BUSINESS, rule.rule_version_id)) for _ in range(3)]
    evaluate.run(EvaluateRequest(OTHER_TENANT, BUSINESS, rule.rule_version_id))

    listing = ListDecisions(factory)
    of_rule = listing.run(
        DecisionQuery(TENANT, BUSINESS, limit=10, rule_version_id=rule.rule_version_id)
    )
    assert [d.decision_id for d in of_rule] == [d.decision_id for d in reversed(made)]
    after = listing.run(
        DecisionQuery(
            TENANT,
            BUSINESS,
            limit=10,
            rule_version_id=rule.rule_version_id,
            after=DecisionKey.of(made[2]),
        )
    )
    assert [d.decision_id for d in after] == [made[1].decision_id, made[0].decision_id]
    assert all(
        d.tenant_id == TENANT for d in listing.run(DecisionQuery(TENANT, BUSINESS, limit=50))
    )
