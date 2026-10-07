"""Migration 0002 on Postgres: the channel_consent table, its append-only trigger, the partial
unique index on the message id, and the repository through identity's own role. Needs Docker.

The role is ``cw_identity`` as infra/dev/postgres/roles.sql makes it, given to the database before
the migrations as on a fresh dev volume: it owns nothing and is not a superuser.
"""

import importlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import ConsentId
from identity.application.channel_consents import ChannelConsentStatus, RecordChannelConsent
from identity.domain.channel_consent import ChannelConsentRecord, ConsentChannel
from identity.domain.consent import ConsentPurpose, ConsentSource
from identity.infrastructure.models import Base
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.db_roles import apply_roles, as_role

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "identity"
TABLE = "channel_consent"
RESTRICT_VIOLATION = "23001"
NUMBER = "919876543210"
NOTICE = "whatsapp-consent 0.1-draft"
WHATSAPP = ConsentChannel.WHATSAPP
REMINDERS = ConsentPurpose.WHATSAPP_REMINDERS
KEYWORD = ConsentSource.WHATSAPP_KEYWORD


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        admin.dispose()
        # Tables the migrations create later, again after a downgrade, reach the role too.
        apply_roles(base_url)
        yield f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"


@pytest.fixture(scope="module")
def alembic_config(database_url: str) -> Iterator[Config]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        yield Config(str(SERVICE_DIR / "alembic.ini"))


@pytest.fixture(scope="module")
def engine(database_url: str, alembic_config: Config) -> Iterator[Engine]:
    command.upgrade(alembic_config, "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, engine: Engine) -> Iterator[Engine]:
    # Again after the migrations: identity's 0005 makes the audit schema, which the role must
    # be able to write to (USAGE and INSERT), as make migrate's db-roles step grants.
    apply_roles(database_url)
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def function_exists(engine: Engine, name: str) -> bool:
    with engine.connect() as connection:
        found: object = connection.execute(
            text("SELECT to_regprocedure(:name) IS NOT NULL"), {"name": f"{SCHEMA}.{name}()"}
        ).scalar_one()
    return bool(found)


def insert(connection: Connection, *, message_id: str, granted: bool = False) -> None:
    connection.execute(
        text(
            f"INSERT INTO {TABLE} (id, channel, subject, purpose, granted, source, "
            "notice_version, message_id, recorded_at) VALUES (:id, 'whatsapp', :subject, "
            "'whatsapp_reminders', :granted, 'whatsapp_keyword', :notice, :message_id, now())"
        ),
        {
            "id": uuid4(),
            "subject": NUMBER,
            "granted": granted,
            "notice": NOTICE if granted else "",
            "message_id": message_id,
        },
    )


def sqlstate(error: DBAPIError) -> object:
    return getattr(error.orig, "sqlstate", None)


def test_upgrade_downgrade_upgrade(alembic_config: Config, engine: Engine) -> None:
    command.downgrade(alembic_config, "0001")
    assert tables(engine) == {"consent_record", "alembic_version"}
    assert not function_exists(engine, "identity_append_only")
    command.upgrade(alembic_config, "0002")
    assert TABLE in tables(engine)
    assert function_exists(engine, "identity_append_only")
    command.downgrade(alembic_config, "base")
    assert tables(engine) == {"alembic_version"}
    command.upgrade(alembic_config, "head")
    assert TABLE in tables(engine)


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_channel_consent(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table == TABLE

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_channel_consent,
            },
        )
        assert compare_metadata(context, Base.metadata) == []
    columns = {c["name"] for c in inspect(engine).get_columns(TABLE, schema=SCHEMA)}
    assert "tenant_id" not in columns
    indexes = {i["name"]: i for i in inspect(engine).get_indexes(TABLE, SCHEMA)}
    assert indexes["ix_channel_consent_subject"]["column_names"] == [
        "channel",
        "subject",
        "recorded_at",
    ]
    assert indexes["ux_channel_consent_message"]["unique"]


def test_the_catalog_lint_passes_with_the_exemption(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    (channel_consent,) = [t for t in catalog if t.name == TABLE]
    assert channel_consent.tenant_id == "absent"
    config = lint.load_config()
    assert config.exemption_for(f"{SCHEMA}.{TABLE}") is not None
    assert [p for p in lint.catalog_problems(catalog, config) if p.startswith(f"{SCHEMA}.")] == []


def test_update_and_delete_are_refused(engine: Engine, app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        insert(connection, message_id=f"wamid.{uuid4()}")
    for statement in (
        f"UPDATE {TABLE} SET evidence = 'changed'",
        f"DELETE FROM {TABLE}",
    ):
        for role in (app_engine, engine):
            with pytest.raises(DBAPIError) as refused, role.begin() as connection:
                connection.execute(text(statement))
            assert sqlstate(refused.value) == RESTRICT_VIOLATION
    with app_engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.erasure', 'on', true)"))
        with pytest.raises(DBAPIError) as erasure:
            connection.execute(text(f"DELETE FROM {TABLE}"))
    assert sqlstate(erasure.value) == RESTRICT_VIOLATION


def test_the_message_id_is_unique_per_channel_and_empty_ids_are_free(app_engine: Engine) -> None:
    message_id = f"wamid.{uuid4()}"
    with app_engine.begin() as connection:
        insert(connection, message_id=message_id)
        insert(connection, message_id="")
        insert(connection, message_id="")
    with pytest.raises(IntegrityError), app_engine.begin() as connection:
        insert(connection, message_id=message_id, granted=True)


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("subject", "+919876543210", "ck_channel_consent_subject"),
        ("purpose", "terms", "ck_channel_consent_purpose"),
        ("source", "api", "ck_channel_consent_source"),
        ("channel", "email", "ck_channel_consent_channel"),
    ],
)
def test_the_checks_refuse_what_the_domain_refuses(
    app_engine: Engine, column: str, value: str, constraint: str
) -> None:
    values = {
        "channel": "whatsapp",
        "subject": NUMBER,
        "purpose": "whatsapp_reminders",
        "source": "whatsapp_keyword",
    }
    values[column] = value
    with pytest.raises(IntegrityError, match=constraint), app_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {TABLE} (id, channel, subject, purpose, granted, source, "
                "recorded_at) VALUES (:id, :channel, :subject, :purpose, false, :source, now())"
            ),
            {"id": uuid4(), **values},
        )


def test_a_grant_needs_its_notice_version(app_engine: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="ck_channel_consent_notice_version"),
        app_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {TABLE} (id, channel, subject, purpose, granted, source, "
                "recorded_at) VALUES (:id, 'whatsapp', :subject, 'whatsapp_reminders', true, "
                "'whatsapp_keyword', now())"
            ),
            {"id": uuid4(), "subject": NUMBER},
        )


def test_the_use_cases_through_a_plain_role(app_engine: Engine) -> None:
    factory = PostgresUnitOfWorkFactory(app_engine).channel_unit_of_work
    record = RecordChannelConsent(factory)
    number = "918888888888"
    message_id = f"wamid.{uuid4()}"
    first = record.run(
        WHATSAPP,
        "+" + number,
        REMINDERS,
        granted=True,
        source=KEYWORD,
        notice_version=NOTICE,
        evidence="keyword START",
        message_id=message_id,
    )
    again = record.run(
        WHATSAPP,
        number,
        REMINDERS,
        granted=True,
        source=KEYWORD,
        notice_version=NOTICE,
        message_id=message_id,
    )
    assert first.created
    assert not again.created
    assert again.record == first.record
    record.run(WHATSAPP, number, REMINDERS, granted=False, source=KEYWORD)
    summary = ChannelConsentStatus(factory).run(WHATSAPP, number)
    assert [r.granted for r in summary.history] == [True, False]
    assert not summary.granted(REMINDERS)


def test_a_racing_redelivery_returns_the_stored_record(app_engine: Engine) -> None:
    """Two deliveries that both miss ``by_message`` meet at the unique index: the second insert
    does nothing and returns the first record."""
    factory = PostgresUnitOfWorkFactory(app_engine).channel_unit_of_work
    message_id = f"wamid.{uuid4()}"

    def build() -> ChannelConsentRecord:
        return ChannelConsentRecord(
            ConsentId.new(),
            WHATSAPP,
            "917777777777",
            REMINDERS,
            False,
            KEYWORD,
            datetime.now(UTC),
            message_id=message_id,
        )

    first, second = build(), build()
    with factory() as uow:
        assert uow.channel_consents.add(first) == first
    with factory() as uow:
        assert uow.channel_consents.add(second) == first
        assert uow.channel_consents.by_message(WHATSAPP, "") is None
