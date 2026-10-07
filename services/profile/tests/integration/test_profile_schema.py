"""Migration 0001 on Postgres: four tenant tables with row-level security, the unit of work
with the outbox, and the use cases end to end through the profile's own role, cw_profile as
infra/dev/postgres/roles.sql makes it, which is not a superuser. Needs Docker."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import TenantId
from profile_service.application.attributes import (
    BuildSnapshot,
    ConfirmFinancialYear,
    SetAttributes,
)
from profile_service.application.audit import ATTRIBUTES_CHANGED, REGISTERED
from profile_service.application.registration import RegisterNodes
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import AttributeChange, ValueState
from profile_service.infrastructure.repository import (
    JsonLinesEvalRecorder,
    PostgresUnitOfWorkFactory,
)
from profile_service.testing import GSTIN_KARNATAKA
from py_common.audit.testing import install_audit_table, read_audit_entries
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "profile"
TABLES = {
    "profile_node",
    "profile_attribute",
    "profile_version",
    "review_task",
    "outbox_event",
    "processed_event",
    "idempotency_key",
    "alembic_version",
}
FY = FinancialYear(2025)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


def install_audit(database_url: str) -> None:
    """``audit.event`` as identity's migration makes it, before the roles are applied, so
    cw_profile may add rows to it."""
    engine = create_engine(database_url)
    with engine.begin() as connection:
        install_audit_table(connection)
    engine.dispose()


@pytest.fixture(scope="module")
def migrated(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        config = Config(str(SERVICE_DIR / "alembic.ini"))
        command.upgrade(config, "head")
        install_audit(database_url)
        yield config


@pytest.fixture(scope="module")
def engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    apply_roles(database_url)
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def test_migration_creates_the_tables_with_row_level_security(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(inspector.get_table_names(schema=SCHEMA)) == TABLES
    with engine.connect() as connection:
        policies: list[str] = sorted(
            connection.execute(
                text("SELECT policyname FROM pg_policies WHERE schemaname = :s"), {"s": SCHEMA}
            ).scalars()
        )
        forced: list[bool] = list(
            connection.execute(
                text(
                    "SELECT relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                    "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname IN "
                    "('profile_node', 'profile_attribute', 'profile_version', 'review_task')"
                ),
                {"s": SCHEMA},
            ).scalars()
        )
    assert policies == [
        "idempotency_key_purge_expired",
        "idempotency_key_tenant_isolation",
        "profile_attribute_tenant_isolation",
        "profile_node_tenant_isolation",
        "profile_version_tenant_isolation",
        "review_task_tenant_isolation",
    ]
    assert forced == [True, True, True, True]


def test_use_cases_end_to_end_with_the_outbox(
    app_engine: Engine, engine: Engine, tmp_path: Path
) -> None:
    ontology = ontology_package.load()
    cases = tmp_path / "cases.jsonl"
    factory = PostgresUnitOfWorkFactory(app_engine, eval_cases=JsonLinesEvalRecorder(cases))
    tenant, other = TenantId.new(), TenantId.new()
    registered = RegisterNodes(factory).registration(
        tenant, GSTIN_KARNATAKA, "Acme", entity_name="Acme"
    )
    entity_id, registration_id = registered.node.parent_id, registered.node.id
    assert entity_id is not None
    assert not RegisterNodes(factory).registration(tenant, GSTIN_KARNATAKA, "again").created

    result = SetAttributes(factory, ontology).run(
        tenant,
        entity_id,
        [
            AttributeChange("turnover_band", "2_crore_to_5_crore", as_of_fy=FY),
            AttributeChange("state_codes", ["29", "07"]),
            AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE),
        ],
        source=ChangeSource.USER_INPUT,
    )
    assert result.node.version == 2
    assert len(result.review_tasks) == 1
    SetAttributes(factory, ontology).run(
        tenant,
        registration_id,
        [AttributeChange("registration_type", "regular")],
        source=ChangeSource.GSTIN_LOOKUP,
    )
    snapshot = BuildSnapshot(factory).run(tenant, registration_id, as_of_fy=FY)
    assert snapshot.attributes == {
        "turnover_band": "2_crore_to_5_crore",
        "state_codes": frozenset({"29", "07"}),
        "registration_type": "regular",
    }
    assert snapshot.lineage == (entity_id,)
    assert ConfirmFinancialYear(factory, ontology).run(tenant, FY) == ()
    assert len(ConfirmFinancialYear(factory, ontology).run(tenant, FY.next())) == 1

    with factory(tenant) as uow:
        assert [t.attribute_key for t in uow.profiles.open_review_tasks(entity_id)] == [
            "employee_count",
            "turnover_band",
        ]
    with factory(other) as uow:
        assert uow.profiles.get(entity_id) is None, "row-level security hides other tenants"
        assert uow.profiles.entities() == []
    with app_engine.connect() as connection:
        bare: int = connection.execute(text("SELECT count(*) FROM profile_node")).scalar_one()
        topics = connection.execute(
            text("SELECT topic, count(*) FROM outbox_event GROUP BY topic")
        ).all()
    assert bare == 0
    assert [tuple(row) for row in topics] == [("profile.updated", 2)]
    lines = cases.read_text().splitlines()
    assert len(lines) == 1
    assert '"attribute": "employee_count"' in lines[0]

    # cw_profile only adds audit rows; the container's superuser reads them back.
    with engine.connect() as connection:
        created = read_audit_entries(connection, action=REGISTERED)
        changed = read_audit_entries(connection, action=ATTRIBUTES_CHANGED)
    # One unit creates both nodes at one clock time, so the rows come back in id order.
    assert {(e.tenant_id, e.subject_id) for e in created} == {
        (tenant, str(entity_id)),
        (tenant, str(registration_id)),
    }
    assert [e.subject_id for e in changed] == [str(entity_id), str(registration_id)]
    on_entity = changed[0]
    assert (on_entity.tenant_id, on_entity.subject_type, on_entity.actor.label) == (
        tenant,
        "profile_node",
        "system:profile",
    )
    assert on_entity.before == {
        "employee_count": None,
        "state_codes": None,
        "turnover_band@2025-26": None,
    }
    assert on_entity.after == {
        "employee_count": {"state": "not_applicable", "value": None, "source": "user_input"},
        "state_codes": {"state": "known", "value": ("07", "29"), "source": "user_input"},
        "turnover_band@2025-26": {
            "state": "known",
            "value": "2_crore_to_5_crore",
            "source": "user_input",
        },
    }


def test_downgrade_and_upgrade(migrated: Config, engine: Engine) -> None:
    command.downgrade(migrated, "base")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == {"alembic_version"}
    command.upgrade(migrated, "head")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == TABLES
