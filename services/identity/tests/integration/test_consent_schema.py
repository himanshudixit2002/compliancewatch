"""Migration 0001 on Postgres: the consent table, row-level security by tenant, the unit of
work end to end as a plain database role, the history's own tenant filter where row-level
security is bypassed; and migration 0004, which adds the web_settings source. Needs Docker."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import TenantId
from identity.application.consents import ConsentStatus, RecordConsent
from identity.domain.consent import ConsentPurpose, ConsentSource
from identity.infrastructure.repository import PostgresUnitOfWorkFactory

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "identity"
APP_ROLE = "identity_app"
APP_PASSWORD = "app-role-for-tests"


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
def app_engine(database_url: str, migrated: Config) -> Iterator[Engine]:
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
        connection.execute(
            text(f"GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA {SCHEMA} TO {APP_ROLE}")
        )
    admin.dispose()
    engine = create_engine(database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@"))
    yield engine
    engine.dispose()


def test_table_policy_and_isolation(
    database_url: str, migrated: Config, app_engine: Engine
) -> None:
    engine = create_engine(database_url)
    assert {"consent_record", "channel_consent", "alembic_version"} <= set(
        inspect(engine).get_table_names(schema=SCHEMA)
    )
    with engine.connect() as connection:
        policies: list[str] = list(
            connection.execute(
                text("SELECT policyname FROM pg_policies WHERE tablename = 'consent_record'")
            ).scalars()
        )
    assert policies == ["consent_record_tenant_isolation"]
    engine.dispose()

    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant, other = TenantId.new(), TenantId.new()
    record = RecordConsent(factory)
    record.run(
        tenant,
        "u",
        ConsentPurpose.TERMS,
        granted=True,
        source=ConsentSource.WEB_ONBOARDING,
        notice_version="0.1-draft",
    )
    record.run(tenant, "u", ConsentPurpose.TERMS, granted=False, source=ConsentSource.SUPPORT)
    mine = ConsentStatus(factory).run(tenant, "u")
    assert len(mine.history) == 2
    assert not mine.granted(ConsentPurpose.TERMS)
    assert ConsentStatus(factory).run(other, "u").history == ()
    with app_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM consent_record")).scalar_one() == 0


def test_history_names_the_tenant_where_row_level_security_is_bypassed(
    database_url: str, migrated: Config
) -> None:
    """The test database's user owns the table and is a superuser, so row-level security does
    not apply to it, as for the dev stack's role: the query's own tenant filter keeps tenants
    apart."""
    engine = create_engine(database_url)
    factory = PostgresUnitOfWorkFactory(engine)
    tenant, other = TenantId.new(), TenantId.new()
    record = RecordConsent(factory)
    record.run(tenant, "shared", ConsentPurpose.TERMS, granted=False, source=ConsentSource.API)
    record.run(other, "shared", ConsentPurpose.ANALYTICS, granted=False, source=ConsentSource.API)
    with engine.connect() as connection:
        visible: int = connection.execute(
            text("SELECT count(*) FROM consent_record WHERE subject = 'shared'")
        ).scalar_one()
    assert visible == 2, "row-level security does not hide the other tenant's row here"
    mine = ConsentStatus(factory).run(tenant, "shared")
    assert [(r.tenant_id, r.purpose) for r in mine.history] == [(tenant, ConsentPurpose.TERMS)]
    assert [state.purpose for state in mine.states] == [ConsentPurpose.TERMS]
    with factory(None) as uow:
        assert uow.consents.history("shared") == []
    engine.dispose()


def _source_check(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_consent_record_source'"
                )
            ).scalar_one()
        )


def test_web_settings_is_a_source_and_the_downgrade_keeps_the_evidence(
    migrated: Config, database_url: str, app_engine: Engine
) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine)
    tenant = TenantId.new()
    RecordConsent(factory).run(
        tenant,
        "settings-user",
        ConsentPurpose.ANALYTICS,
        granted=False,
        source=ConsentSource.WEB_SETTINGS,
        evidence="toggle: Share usage analytics",
    )
    (state,) = ConsentStatus(factory).run(tenant, "settings-user").states
    assert state.source is ConsentSource.WEB_SETTINGS

    engine = create_engine(database_url)
    with pytest.raises(IntegrityError, match="ck_consent_record_source"):
        command.downgrade(migrated, "0003")
    assert "web_settings" in _source_check(engine), "the failed downgrade changed nothing"
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM consent_record WHERE source = 'web_settings'"))
    command.downgrade(migrated, "0003")
    assert "web_settings" not in _source_check(engine)
    command.upgrade(migrated, "head")
    assert "web_settings" in _source_check(engine)
    engine.dispose()


def test_downgrade_and_upgrade(migrated: Config, database_url: str) -> None:
    engine = create_engine(database_url)
    command.downgrade(migrated, "base")
    assert set(inspect(engine).get_table_names(schema=SCHEMA)) == {"alembic_version"}
    command.upgrade(migrated, "head")
    assert "consent_record" in inspect(engine).get_table_names(schema=SCHEMA)
    engine.dispose()
