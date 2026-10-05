"""Migration 0004 on Postgres, the impact of a change and the dry run through a plain role: the
impact reads each business's latest decision of a version under its client for the unit's tenant
alone, and a dry run reads the directory and the profiles with no transaction open and writes
nothing but its audit row: no decision, no review item, no outbox row. Needs Docker.

The stores run as a role that owns nothing and is not a superuser, as ``cw_app`` does in the
product; the rows of every tenant and the audit rows of no tenant are counted as the superuser.
"""

from collections.abc import Iterator, Sequence
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text

import ontology as ontology_package
from applicability_engine.application.dry_run import DRY_RUN_ACTION, DryRun, DryRunRequest
from applicability_engine.application.impact import ReadChangeImpact
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.impact import ImpactQuery
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.infrastructure.repository import (
    PostgresBusinessDirectory,
    PostgresFanOutUnitOfWorkFactory,
    PostgresUnitOfWorkFactory,
)
from applicability_engine.testing import NOW, MemoryProfiles, MemoryRulebook, rule_version
from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.confidence import CERTAIN
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Applicability
from domain_kernel.profiles import ProfileSnapshot
from py_common.audit.schema import AUDIT_SCHEMA, QUALIFIED_TABLE
from py_common.audit.testing import install_audit_table, read_audit_entries

pytestmark = pytest.mark.integration

SERVICE_DIR = Path(__file__).resolve().parents[2]
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "applicability"
INDEX = "ix_applicability_decision_impact"
APP_ROLE = "impact_app"
APP_PASSWORD = "app-role-for-tests"
REGULAR = {"attribute": "registration_type", "operator": "eq", "value": "regular"}
ADMIN = AuditActor.user(UserId.new(), [Role.ADMIN])
WRITTEN = ("applicability_decision", "review_item", "outbox_event", "fanout_run")
"""The tables a dry run must leave as they were."""


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(IMAGE, driver="psycopg") as postgres:
        base_url = postgres.get_connection_url()
        admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
            connection.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}'"))
            connection.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
            connection.execute(
                text(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
                )
            )
        admin.dispose()
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
    with engine.begin() as connection:
        install_audit_table(connection)
        connection.execute(text(f"GRANT USAGE ON SCHEMA {AUDIT_SCHEMA} TO {APP_ROLE}"))
        connection.execute(
            text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {QUALIFIED_TABLE} TO {APP_ROLE}")
        )
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def app_engine(database_url: str, engine: Engine) -> Iterator[Engine]:
    engine = create_engine(database_url.replace("test:test@", f"{APP_ROLE}:{APP_PASSWORD}@"))
    with engine.connect() as connection:
        superuser = "SELECT usesuper FROM pg_user WHERE usename = current_user"
        assert connection.execute(text(superuser)).scalar_one() is False
    yield engine
    engine.dispose()


def indexes(engine: Engine) -> set[str]:
    found = inspect(engine).get_indexes("applicability_decision", schema=SCHEMA)
    return {str(index["name"]) for index in found}


def test_upgrade_downgrade_upgrade(alembic_config: Config, engine: Engine) -> None:
    assert INDEX in indexes(engine)
    command.downgrade(alembic_config, "0003")
    assert INDEX not in indexes(engine)
    command.upgrade(alembic_config, "head")
    assert INDEX in indexes(engine)


def decide(
    units: PostgresUnitOfWorkFactory,
    tenant: TenantId,
    business: BusinessId,
    version: RuleVersionId,
    result: Applicability,
    *,
    minutes: int = 0,
) -> Decision:
    decision = Decision(
        decision_id=DecisionId.new(),
        tenant_id=tenant,
        business_id=business,
        rule_version_id=version,
        result=result,
        confidence=CERTAIN,
        evaluated=(),
        profile_version=1,
        decided_at=NOW + timedelta(minutes=minutes),
        trigger=Trigger.RULE_PUBLISHED,
        as_of_fy=None,
    )
    with units(tenant) as uow:
        uow.decisions.add(decision)
    return decision


def client_of(
    units: PostgresUnitOfWorkFactory, tenant: TenantId, registrations: int
) -> tuple[BusinessId, list[BusinessId]]:
    entity = BusinessId.new()
    businesses = [BusinessId.new() for _ in range(registrations)]
    with units(tenant) as uow:
        uow.directory.add(DirectoryEntry(tenant, entity, AttributeLevel.ENTITY, None, entity))
        for business in businesses:
            uow.directory.add(
                DirectoryEntry(tenant, business, AttributeLevel.REGISTRATION, entity, entity)
            )
    return entity, businesses


def test_the_impact_reads_the_latest_decisions_of_its_tenant_alone(app_engine: Engine) -> None:
    units = PostgresUnitOfWorkFactory(app_engine)
    fanouts = PostgresFanOutUnitOfWorkFactory(app_engine)
    version = RuleVersionId.new()
    firm, other = TenantId.new(), TenantId.new()
    first, (one, two) = client_of(units, firm, 2)
    second, (three,) = client_of(units, firm, 1)
    decide(units, firm, one, version, Applicability.UNSURE, minutes=1)
    latest = decide(units, firm, one, version, Applicability.APPLIES, minutes=2)
    decide(units, firm, two, version, Applicability.NOT_APPLICABLE)
    decide(units, firm, three, version, Applicability.APPLIES)
    decide(units, firm, three, RuleVersionId.new(), Applicability.NOT_APPLICABLE, minutes=5)
    stranger = decide(units, other, BusinessId.new(), version, Applicability.APPLIES)
    _, (theirs,) = client_of(units, other, 1)
    decide(units, other, theirs, version, Applicability.UNSURE)

    read = ReadChangeImpact(units, fanouts)
    impact = read.run(ImpactQuery(tenant_id=firm, rule_version_id=version, limit=50))
    placed = {group.entity_id: group for group in impact.groups}
    assert set(placed) == {first, second}
    assert [group.entity_id.value for group in impact.groups] == sorted([first.value, second.value])
    assert [entry.business_id for entry in placed[first].entries] == sorted(
        [one, two], key=lambda business: business.value
    )
    by_business = {entry.business_id: entry for entry in placed[first].entries}
    assert by_business[one].decision == latest
    assert by_business[one].level is AttributeLevel.REGISTRATION
    assert impact.counts == {
        Applicability.APPLIES: 2,
        Applicability.NOT_APPLICABLE: 1,
        Applicability.UNSURE: 0,
    }
    assert impact.fan_out is None

    affected = read.run(
        ImpactQuery(tenant_id=firm, rule_version_id=version, limit=50, result=Applicability.APPLIES)
    )
    assert [entry.business_id for group in affected.groups for entry in group.entries] == [
        entry.business_id
        for group in impact.groups
        for entry in group.entries
        if entry.decision.result is Applicability.APPLIES
    ]
    page = read.run(ImpactQuery(tenant_id=firm, rule_version_id=version, limit=1))
    rest = read.run(
        ImpactQuery(
            tenant_id=firm, rule_version_id=version, limit=50, after=page.groups[0].entity_id
        )
    )
    assert page.groups + rest.groups == impact.groups

    theirs_impact = read.run(ImpactQuery(tenant_id=other, rule_version_id=version, limit=50))
    entries = [entry for group in theirs_impact.groups for entry in group.entries]
    assert {entry.business_id for entry in entries} == {stranger.business_id, theirs}
    unlisted = next(e for e in entries if e.business_id == stranger.business_id)
    assert (unlisted.entity_id, unlisted.level) == (stranger.business_id, None)


class Watched:
    """A profile reader that, on every read, finds no session of the app role holding a
    transaction open: the dry run reads over HTTP with none open."""

    def __init__(self, profiles: MemoryProfiles, engine: Engine) -> None:
        self._profiles = profiles
        self._engine = engine
        self.reads = 0

    def snapshot(
        self, tenant_id: TenantId, business_id: BusinessId, fy: FinancialYear | None
    ) -> ProfileSnapshot | None:
        with self._engine.connect() as connection:
            open_transactions = connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE usename = :role "
                    "AND state LIKE 'idle in transaction%'"
                ),
                {"role": APP_ROLE},
            ).scalar_one()
        assert open_transactions == 0, "a transaction was open during the read"
        self.reads += 1
        return self._profiles.snapshot(tenant_id, business_id, fy)

    def registrations(
        self, tenant_id: TenantId, entity_id: BusinessId
    ) -> Sequence[BusinessId] | None:
        return self._profiles.registrations(tenant_id, entity_id)


def counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        found = {
            table: int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
            for table in WRITTEN
        }
        found["audit"] = len(read_audit_entries(connection, action=DRY_RUN_ACTION))
    return found


def test_a_dry_run_writes_its_audit_row_and_nothing_else(
    engine: Engine, app_engine: Engine
) -> None:
    units = PostgresUnitOfWorkFactory(app_engine)
    profiles, rulebook = MemoryProfiles(), MemoryRulebook()
    tenant = TenantId.new()
    for registration_type in ("regular", "regular", "composition"):
        entity, (business,) = client_of(units, tenant, 1)
        profiles.put(
            {"registration_type": registration_type},
            tenant_id=tenant,
            business_id=business,
            lineage=[entity],
        )
    version = rulebook.put(rule_version(REGULAR))
    watched = Watched(profiles, engine)
    dry_run = DryRun(
        PostgresBusinessDirectory(app_engine),
        PostgresFanOutUnitOfWorkFactory(app_engine),
        watched,
        rulebook,
        ontology_package.load(),
    )
    before = counts(engine)
    report = dry_run.run(
        DryRunRequest(
            actor=ADMIN,
            rule_version_id=version.rule_version_id,
            tenant_id=tenant,
            correlation_id="dry-run-check",
        )
    )
    assert (report.businesses_total, report.evaluated, watched.reads) == (3, 3, 3)
    assert report.counts[Applicability.APPLIES] == 2
    after = counts(engine)
    assert after == {**before, "audit": before["audit"] + 1}
    with engine.connect() as connection:
        (entry,) = [
            e
            for e in read_audit_entries(connection, action=DRY_RUN_ACTION)
            if e.correlation_id == "dry-run-check"
        ]
    assert (entry.tenant_id, entry.actor, entry.subject_id) == (
        None,
        ADMIN,
        str(version.rule_version_id),
    )
    assert entry.after is not None
    assert entry.after["counts"] == {"applies": 2, "not_applicable": 1, "unsure": 0}
    assert entry.after["tenant_id"] == str(tenant)
    with app_engine.connect() as connection:
        assert read_audit_entries(connection, action=DRY_RUN_ACTION) == [], (
            "no policy lets the app role read rows of no tenant"
        )
