"""Migration 0003 and the seed repository on Postgres: draft versions are created, re-runs are
idempotent, edits update drafts, versions that left draft stay untouched (a direct move to
published is refused by the migration 0007 guard, so the test moves one to review). Needs
Docker.

The seed runs as the rulebook's own role, ``cw_rulebook`` as infra/dev/postgres/roles.sql makes
it, which is the role ``make seed SERVICE=rulebook`` connects as; the owner only migrates."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

import ontology as ontology_package
from py_common.db_roles import apply_roles, as_role
from rulebook.application.seed_loader import load_calendar
from rulebook.infrastructure.models import RuleRow, RuleVersionRow
from rulebook.infrastructure.seed_repository import SqlAlchemySeedRepository

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "rulebook"


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
def engine(database_url: str) -> Iterator[Engine]:
    with pytest.MonkeyPatch.context() as env:
        env.setenv("CW_DATABASE_URL", database_url)
        env.setenv("CW_DB_SCHEMA", SCHEMA)
        command.upgrade(Config(str(SERVICE_DIR / "alembic.ini")), "head")
    apply_roles(database_url)
    engine = create_engine(as_role(database_url, SCHEMA))
    yield engine
    engine.dispose()


def test_rule_tables_exist(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {"rule", "rule_version"} <= set(inspector.get_table_names(schema=SCHEMA))
    checks = {c["name"] for c in inspector.get_check_constraints("rule_version", schema=SCHEMA)}
    assert {
        "ck_rule_version_status",
        "ck_rule_version_seed_status",
        "ck_rule_version_effective",
    } <= checks


def test_seed_is_idempotent_updates_drafts_and_respects_reviewed_versions(engine: Engine) -> None:
    calendar = load_calendar(ontology_package.load())
    repository = SqlAlchemySeedRepository(engine)
    first = repository.apply(calendar, now=datetime(2026, 9, 28, tzinfo=UTC))
    assert len(first.created_rules) == len(calendar.rules) == 13
    assert len(first.created_versions) == 13
    second = repository.apply(calendar)
    assert second.created_rules == ()
    assert second.created_versions == ()
    assert len(second.unchanged) == 13

    with Session(engine) as session:
        rows = session.scalars(select(RuleVersionRow)).all()
        assert {row.status for row in rows} == {"draft"}
        assert {row.seed_status for row in rows} == {"needs_review"}
        gstr3b = session.scalars(
            select(RuleVersionRow).join(RuleRow).where(RuleRow.rule_key == "gstr3b_monthly")
        ).one()
        assert gstr3b.recurrence == {"frequency": "monthly", "due_day": 20, "due_month_offset": 0}
        all_of = gstr3b.specification["all_of"]
        assert isinstance(all_of, list)
        assert all_of[0] == {"attribute": "registration_type", "operator": "eq", "value": "regular"}
        assert gstr3b.todo
        gstr3b.status = "in_review"
        session.commit()

    edited = load_calendar(
        ontology_package.load(),
    )
    edited_rule = edited.get("gstr3b_monthly")
    changed = type(edited_rule)(
        **{
            **{s: getattr(edited_rule, s) for s in edited_rule.__slots__},
            "title": "File GSTR-3B monthly",
        }
    )
    calendar_edited = type(edited)(
        edited.version,
        edited.ontology_version,
        tuple(changed if r.rule_key == "gstr3b_monthly" else r for r in edited.rules),
    )
    third = repository.apply(calendar_edited)
    assert third.created_versions == ("gstr3b_monthly@2",)
    with Session(engine) as session:
        versions = session.scalars(
            select(RuleVersionRow)
            .join(RuleRow)
            .where(RuleRow.rule_key == "gstr3b_monthly")
            .order_by(RuleVersionRow.version)
        ).all()
        assert [(v.version, v.status, v.title) for v in versions] == [
            (1, "in_review", "File FORM GSTR-3B every month"),
            (2, "draft", "File GSTR-3B monthly"),
        ]

    calendar_edited_again = type(edited)(
        edited.version,
        edited.ontology_version,
        tuple(
            type(changed)(
                **{**{s: getattr(changed, s) for s in changed.__slots__}, "summary": "edited again"}
            )
            if r.rule_key == "gstr3b_monthly"
            else r
            for r in calendar_edited.rules
        ),
    )
    fourth = repository.apply(calendar_edited_again)
    assert fourth.updated_drafts == ("gstr3b_monthly@2",)
    assert fourth.created_versions == ()


def test_a_rerun_leaves_an_approved_version_alone(engine: Engine) -> None:
    calendar = load_calendar(ontology_package.load())
    repository = SqlAlchemySeedRepository(engine)
    repository.apply(calendar)
    with Session(engine) as session:
        gstr1 = session.scalars(
            select(RuleVersionRow).join(RuleRow).where(RuleRow.rule_key == "gstr1_monthly")
        ).one()
        gstr1.status, gstr1.submitted_at = "in_review", datetime(2026, 9, 29, tzinfo=UTC)
        session.flush()
        gstr1.status, gstr1.seed_status = "approved", "reviewed"
        session.commit()
    again = repository.apply(calendar)
    assert "gstr1_monthly" in again.unchanged
    assert not [key for key in again.created_versions if key.startswith("gstr1_monthly@")]
    with Session(engine) as session:
        versions = session.scalars(
            select(RuleVersionRow.status)
            .join(RuleRow)
            .where(RuleRow.rule_key == "gstr1_monthly")
            .order_by(RuleVersionRow.version)
        ).all()
    assert versions == ["approved"]
