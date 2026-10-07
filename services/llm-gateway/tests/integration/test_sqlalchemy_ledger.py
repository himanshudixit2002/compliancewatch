"""SqlAlchemyLedger against Postgres through the service's own migrations. Needs Docker.

A module-scoped container is created once; the first migration runs against it exactly as
``make migrate`` does, with the schema on the connection's ``search_path`` and the
``alembic_version`` table inside that schema. The ledger writes and reads as the gateway's own
role, ``cw_llm_gateway`` as infra/dev/postgres/roles.sql makes it, which is not a superuser.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import TenantId
from llm_gateway.domain.features import CallStatus, CostSource, Feature
from llm_gateway.domain.ledger import LedgerEntry
from llm_gateway.infrastructure.ledger.models import TABLE_COMMENT
from llm_gateway.infrastructure.ledger.sqlalchemy import SqlAlchemyLedger
from py_common.db_roles import apply_roles, as_role

SERVICE_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = SERVICE_ROOT / "alembic.ini"
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "llm_gateway"
IST = timezone(timedelta(hours=5, minutes=30))
SEPTEMBER = date(2026, 9, 1)
TENANT_A = TenantId.new()
TENANT_B = TenantId.new()
COLUMNS = {
    "id",
    "occurred_at",
    "tenant_id",
    "feature",
    "prompt_name",
    "prompt_version",
    "model_requested",
    "model_served",
    "provider",
    "input_tokens",
    "output_tokens",
    "cached",
    "cost_usd",
    "cost_inr",
    "cost_source",
    "latency_ms",
    "correlation_id",
    "trace_id",
    "generation_id",
    "status",
    "error_type",
}


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """A fresh Postgres with the service schema, migrated to head through env.py."""
    with PostgresContainer(IMAGE, driver="psycopg") as container:
        base_url = container.get_connection_url()
        engine = create_engine(base_url, poolclass=NullPool)
        with engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        engine.dispose()
        url = f"{base_url}?options=-csearch_path%3D{SCHEMA}%2Cpublic"
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("CW_DATABASE_URL", url)
            patch.setenv("CW_DB_SCHEMA", SCHEMA)
            command.upgrade(alembic_config(), "head")
            apply_roles(url)
            yield url


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def ledger(database_url: str, engine: Engine) -> SqlAlchemyLedger:
    """A ledger over an empty table, as the gateway's role."""
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM cost_ledger"))
    return SqlAlchemyLedger.from_url(as_role(database_url, SCHEMA))


def entry(**changes: Any) -> LedgerEntry:
    entry_id = uuid4()
    fields: dict[str, Any] = {
        "id": entry_id,
        "occurred_at": datetime(2026, 9, 15, 10, 0, tzinfo=UTC),
        "tenant_id": TENANT_A,
        "feature": Feature.EXTRACTION,
        "prompt_name": "extraction.rule_candidate",
        "prompt_version": "0",
        "model_requested": "deepseek/deepseek-v4-pro-0813",
        "model_served": "zai/glm-5.3",
        "provider": "morph",
        "input_tokens": 1008,
        "output_tokens": 52,
        "cached": False,
        "cost_usd": Decimal("0.000122"),
        "cost_inr": Decimal("1.0000"),
        "cost_source": CostSource.GATEWAY,
        "latency_ms": 840,
        "correlation_id": "req-1",
        "trace_id": str(entry_id),
        "generation_id": "gen-1",
        "status": CallStatus.OK,
    }
    fields.update(changes)
    return LedgerEntry(**fields)


def table_names(engine: Engine, schema: str) -> list[str]:
    return inspect(engine).get_table_names(schema=schema)


def test_the_migration_creates_the_table_indexes_and_comment_in_the_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names(schema=SCHEMA)
    assert "cost_ledger" in tables
    assert "alembic_version" in tables
    assert "cost_ledger" not in inspector.get_table_names(schema="public")
    assert {column["name"] for column in inspector.get_columns("cost_ledger", schema=SCHEMA)} == (
        COLUMNS
    )
    indexes = {
        index["name"]: list(index["column_names"])
        for index in inspector.get_indexes("cost_ledger", schema=SCHEMA)
    }
    assert indexes == {
        "ix_cost_ledger_tenant_month": ["tenant_id", "occurred_at"],
        "ix_cost_ledger_feature_month": ["feature", "occurred_at"],
    }
    assert inspector.get_table_comment("cost_ledger", schema=SCHEMA)["text"] == TABLE_COMMENT
    with engine.connect() as connection:
        version = connection.execute(text(f"SELECT version_num FROM {SCHEMA}.alembic_version"))
        assert version.scalar_one() == "0001"


def test_ping_runs_a_query_and_fails_loudly_when_unreachable(ledger: SqlAlchemyLedger) -> None:
    assert ledger.ping() is True
    unreachable = SqlAlchemyLedger.from_url("postgresql+psycopg://cw:cw@127.0.0.1:1/none")
    with pytest.raises(OperationalError):
        unreachable.ping()


def test_a_round_trip_preserves_the_entry(ledger: SqlAlchemyLedger) -> None:
    at = datetime(2026, 9, 27, 15, 30, 0, 123456, tzinfo=IST)
    row = entry(occurred_at=at, cost_usd=Decimal("0.000122"), cost_inr=Decimal("0.0107"))
    ledger.add(row)

    [stored] = ledger.recent(10)
    assert stored == row
    assert stored.occurred_at == at
    assert stored.occurred_at.utcoffset() == timedelta(0)
    assert stored.occurred_at.hour == 10
    assert isinstance(stored.tenant_id, TenantId)
    assert (stored.cost_usd, str(stored.cost_inr)) == (Decimal("0.000122"), "0.0107")
    assert (stored.feature, stored.cost_source, stored.status) == (
        Feature.EXTRACTION,
        CostSource.GATEWAY,
        CallStatus.OK,
    )


def test_a_regulatory_error_row_round_trips_with_nulls(ledger: SqlAlchemyLedger) -> None:
    row = entry(
        tenant_id=None,
        cost_usd=None,
        cost_inr=Decimal("0.0000"),
        cost_source=CostSource.ESTIMATE,
        input_tokens=0,
        output_tokens=0,
        generation_id="",
        provider="",
        status=CallStatus.ERROR,
        error_type="llm-provider-unavailable",
    )
    ledger.add(row)
    [stored] = ledger.recent(1)
    assert stored == row
    assert stored.tenant_id is None
    assert stored.cost_usd is None
    assert stored.error_type == "llm-provider-unavailable"


def seed(ledger: SqlAlchemyLedger) -> None:
    for row in (
        entry(cost_inr=Decimal("10.5"), occurred_at=datetime(2026, 9, 15, tzinfo=UTC)),
        entry(
            cost_inr=Decimal("2.25"),
            feature=Feature.QA,
            occurred_at=datetime(2026, 9, 16, tzinfo=UTC),
        ),
        entry(
            cost_inr=Decimal("1.0"),
            tenant_id=TENANT_B,
            occurred_at=datetime(2026, 9, 17, tzinfo=UTC),
        ),
        entry(
            cost_inr=Decimal("4.0"), tenant_id=None, occurred_at=datetime(2026, 9, 18, tzinfo=UTC)
        ),
        entry(cost_inr=Decimal("100"), occurred_at=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC)),
        entry(cost_inr=Decimal("7"), occurred_at=datetime(2026, 10, 1, tzinfo=UTC)),
    ):
        ledger.add(row)


@pytest.mark.parametrize(
    ("tenant", "feature", "month", "expected"),
    [
        (TENANT_A, None, SEPTEMBER, "12.7500"),
        (None, Feature.EXTRACTION, SEPTEMBER, "15.5000"),
        (TENANT_A, Feature.EXTRACTION, SEPTEMBER, "10.5000"),
        (None, None, SEPTEMBER, "17.7500"),
        (TENANT_A, None, date(2026, 8, 1), "100.0000"),
        (TENANT_B, Feature.QA, SEPTEMBER, "0.0000"),
        (None, Feature.QA, SEPTEMBER, "2.2500"),
        (TENANT_A, None, date(2026, 10, 1), "7.0000"),
    ],
)
def test_spent_inr_sums_by_tenant_feature_and_utc_month(
    ledger: SqlAlchemyLedger,
    tenant: TenantId | None,
    feature: Feature | None,
    month: date,
    expected: str,
) -> None:
    seed(ledger)
    spent = ledger.spent_inr(tenant_id=tenant, feature=feature, month=month)
    assert isinstance(spent, Decimal)
    assert str(spent) == expected


def test_spent_inr_is_a_quantised_zero_on_an_empty_table(ledger: SqlAlchemyLedger) -> None:
    assert str(ledger.spent_inr(tenant_id=None, feature=None, month=SEPTEMBER)) == "0.0000"
    with pytest.raises(InvariantViolationError, match="first day"):
        ledger.spent_inr(tenant_id=None, feature=None, month=date(2026, 9, 2))


def test_recent_is_newest_first_and_limited(ledger: SqlAlchemyLedger) -> None:
    seed(ledger)
    assert [row.cost_inr for row in ledger.recent(3)] == [
        Decimal("7.0000"),
        Decimal("4.0000"),
        Decimal("1.0000"),
    ]
    assert len(ledger.recent(100)) == 6
    assert ledger.recent(0) == ()
    with pytest.raises(InvariantViolationError):
        ledger.recent(-1)


def test_downgrade_drops_the_table_and_upgrade_recreates_it(engine: Engine) -> None:
    command.downgrade(alembic_config(), "base")
    assert "cost_ledger" not in table_names(engine, SCHEMA)
    command.upgrade(alembic_config(), "head")
    assert "cost_ledger" in table_names(engine, SCHEMA)
    with engine.connect() as connection:
        version = connection.execute(text(f"SELECT version_num FROM {SCHEMA}.alembic_version"))
        assert version.scalar_one() == "0001"
