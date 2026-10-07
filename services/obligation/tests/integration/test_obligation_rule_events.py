"""Migration 0004 and the rule events on Postgres, through obligation's own role, cw_obligation,
which owns nothing and is not a superuser, so row-level security holds as in a deployment. Needs
Docker.

- the cache table and the applied decisions migrate down and up, match the models, and pass the
  catalog lint (the cache exempt, the decisions under the tenant policy);
- a withdrawal closes the obligations of both tenants in one consumer transaction while each
  tenant still reads only its own, and replaying it changes nothing;
- a supersession closes the periods the newer version takes over and leaves the earlier ones;
- a business new after a supersession gets the period the older version still governs, once;
- a deadline change reschedules the period's obligations of both tenants;
- the guard refuses a late decision, whether it was planned before or after the withdrawal;
- ``obligation-sweep --once --now`` sends the reminders due then and rolls the window, for the
  tenants named only.
"""

import importlib
import io
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from testcontainers.community.postgres import PostgresContainer

from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.predicates import Applicability
from domain_kernel.status import RuleVersionStatus
from obligation import sweep, worker
from obligation.application.decisions import ApplyDecision, Decision, DecisionOutcome
from obligation.application.materialise import IST
from obligation.application.rule_events import RuleEvents
from obligation.application.window import RollWindow
from obligation.domain.rule_versions import Refusal
from obligation.infrastructure.models import Base
from obligation.infrastructure.repository import (
    PostgresTenantDirectory,
    PostgresUnitOfWorkFactory,
    SqlAlchemyRuleVersionRefs,
)
from obligation.settings import ObligationSettings
from obligation.testing import FakeRuleVersionReader, ref_of, rule
from py_common.audit.testing import install_audit_table
from py_common.db_roles import apply_roles, as_role
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer

SERVICE_DIR = Path(__file__).resolve().parents[2]
EXAMPLES = SERVICE_DIR.parents[1] / "packages" / "contracts" / "events" / "examples"
IMAGE = "pgvector/pgvector:0.8.6-pg16"
SCHEMA = "obligation"
CACHE = "rule_version_ref"
DECISION = "obligation_decision"
DECIDED_AT = datetime(2026, 10, 1, 4, 0, tzinfo=UTC)


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
        # The service's own role, as a fresh dev volume has it before the migrations:
        # the tables they create, again after a downgrade, reach it too.
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
def app_url(database_url: str, engine: Engine) -> str:
    return as_role(database_url, SCHEMA)


@pytest.fixture(scope="module")
def app_engine(app_url: str) -> Iterator[Engine]:
    engine = create_engine(app_url)
    yield engine
    engine.dispose()


def tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema=SCHEMA))


def as_tenant(connection: Connection, tenant: TenantId) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
    )


def test_upgrade_downgrade_upgrade(alembic_config: Config, engine: Engine) -> None:
    command.downgrade(alembic_config, "0003")
    assert not {CACHE, DECISION} & tables(engine)
    command.upgrade(alembic_config, "head")
    assert {CACHE, DECISION} <= tables(engine)


def test_models_and_migration_agree(engine: Engine) -> None:
    def only_the_new_tables(
        obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
    ) -> bool:
        table = name if type_ == "table" else getattr(getattr(obj, "table", None), "name", None)
        return table in {CACHE, DECISION}

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "compare_server_default": True,
                "include_object": only_the_new_tables,
            },
        )
        assert compare_metadata(context, Base.metadata) == []


def test_the_catalog_lint_accepts_the_tables(engine: Engine) -> None:
    lint = importlib.import_module("check_migrations")  # infra/scripts, on the pytest path
    with engine.connect() as connection:
        raw = connection.connection.driver_connection
        catalog = [t for t in lint.read_tables(raw) if t.schema == SCHEMA]
    (decisions,) = [t for t in catalog if t.name == DECISION]
    assert lint.tenant_table_problems(decisions) == []
    problems = lint.catalog_problems(catalog, lint.load_config())
    assert [p for p in problems if p.startswith(f"{SCHEMA}.")] == []


# ---------------------------------------------------------------- the consumers


class Worker:
    """Both consumers on the app role's engine, as the worker runs them, with one reader."""

    def __init__(self, engine: Engine, rules: FakeRuleVersionReader) -> None:
        self.engine = engine
        self.rules = rules
        self.producer = FakeProducer()
        config = ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0)
        self.decisions = IdempotentConsumer(
            group_id=worker.GROUP_ID,
            store=read_first_store(engine, worker.GROUP_ID),
            handler=worker.decision_handler(ApplyDecision(rules)),
            producer=self.producer,
            config=config,
        )
        self.rule_events = IdempotentConsumer(
            group_id=worker.RULES_GROUP_ID,
            store=read_first_store(engine, worker.RULES_GROUP_ID),
            handler=worker.rules_handler(RuleEvents(rules, enabled=True)),
            producer=self.producer,
            config=config,
        )

    async def decide(
        self,
        tenant: TenantId,
        business: BusinessId,
        version: RuleVersionId,
        result: str = "applies",
        *,
        decided_at: datetime = DECIDED_AT,
    ) -> Outcome:
        data = json.loads(
            (EXAMPLES / "applicability.decided" / "applies-after-rule-published.json").read_text(
                encoding="utf-8"
            )
        )
        data["event_id"] = str(uuid4())
        data["tenant_id"] = str(tenant)
        data["payload"].update(
            decision_id=str(uuid4()),
            business_id=str(business),
            rule_version_id=str(version),
            result=result,
            decided_at=decided_at.isoformat(),
        )
        return await self.decisions.process(inbound("applicability.decided", data))

    def obligations(self, tenant: TenantId) -> list[dict[str, Any]]:
        """What ``tenant`` reads of the obligations, by business, period and id."""
        with self.engine.begin() as connection:
            as_tenant(connection, tenant)
            return [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT id, tenant_id, business_id, rule_version_id, period_label, "
                        "status, closed_reason, due_at FROM obligation "
                        "ORDER BY business_id, period_label, id"
                    )
                ).mappings()
            ]

    def outbox(self, tenant: TenantId, topic: str) -> int:
        with self.engine.begin() as connection:
            as_tenant(connection, tenant)
            count: int = connection.execute(
                text("SELECT count(*) FROM outbox_event WHERE topic = :topic AND tenant_id = :t"),
                {"topic": topic, "t": tenant.value},
            ).scalar_one()
        return count


def inbound(topic: str, data: dict[str, Any]) -> InboundRecord:
    return InboundRecord(
        topic=topic, partition=0, offset=0, key=b"k", value=json.dumps(data).encode()
    )


def rule_event(topic: str, example: str, **payload: Any) -> InboundRecord:
    data = json.loads((EXAMPLES / topic / f"{example}.json").read_text(encoding="utf-8"))
    data["event_id"] = str(uuid4())
    data["payload"].update({key: str(value) for key, value in payload.items()})
    return inbound(topic, data)


async def held_by_two_tenants(app: Worker, version: RuleVersionId) -> tuple[TenantId, TenantId]:
    """The window of 1 October of ``version`` (September, still due, then October and November)
    for one business of each of two new tenants, made by the decision consumer, which caches the
    version."""
    first, second = TenantId.new(), TenantId.new()
    for tenant in (first, second):
        assert await app.decide(tenant, BusinessId.new(), version) is Outcome.PROCESSED
    assert [len(app.obligations(t)) for t in (first, second)] == [3, 3]
    return first, second


async def test_a_withdrawal_closes_both_tenants_obligations_and_each_reads_its_own(
    app_engine: Engine,
) -> None:
    the_rule = rule()
    version = the_rule.rule_version_id
    app = Worker(app_engine, FakeRuleVersionReader([the_rule]))
    first, second = await held_by_two_tenants(app, version)

    app.rules.end(version, RuleVersionStatus.WITHDRAWN)
    withdrawn = rule_event("rule.withdrawn", "withdrawn-by-an-analyst", rule_version_id=version)
    assert await app.rule_events.process(withdrawn) is Outcome.PROCESSED
    for tenant in (first, second):
        seen = app.obligations(tenant)
        assert {row["tenant_id"] for row in seen} == {tenant.value}, "its own rows only"
        assert {(row["status"], row["closed_reason"]) for row in seen} == {
            ("closed_not_applicable", "rule_withdrawn")
        }
        assert app.outbox(tenant, "obligation.closed") == 3
    with app_engine.begin() as connection:
        hidden: int = connection.execute(text("SELECT count(*) FROM obligation")).scalar_one()
        status: str = connection.execute(
            text(f"SELECT status FROM {CACHE} WHERE rule_version_id = :v"), {"v": version.value}
        ).scalar_one()
    assert hidden == 0, "no tenant set, no rows"
    assert status == "withdrawn"

    assert await app.rule_events.process(withdrawn) is Outcome.SKIPPED, "a redelivery"
    replayed = rule_event("rule.withdrawn", "withdrawn-by-an-analyst", rule_version_id=version)
    assert await app.rule_events.process(replayed) is Outcome.PROCESSED
    assert [app.outbox(t, "obligation.closed") for t in (first, second)] == [3, 3], (
        "replaying the event changes nothing"
    )

    late = await app.decide(first, BusinessId.new(), version)
    assert late is Outcome.PROCESSED
    assert len(app.obligations(first)) == 3, "the guard refused the late decision"
    assert app.producer.sent == []


async def test_a_supersession_closes_the_periods_the_newer_version_takes_over(
    app_engine: Engine,
) -> None:
    the_rule = rule()
    version = the_rule.rule_version_id
    app = Worker(app_engine, FakeRuleVersionReader([the_rule]))
    first, second = await held_by_two_tenants(app, version)
    superseded = rule_event(
        "rule.superseded",
        "newer-version-in-force",
        rule_version_id=version,
        effective_from=date(2026, 11, 1),
    )
    assert await app.rule_events.process(superseded) is Outcome.PROCESSED
    for tenant in (first, second):
        assert [(row["period_label"], row["closed_reason"]) for row in app.obligations(tenant)] == [
            ("2026-09", None),
            ("2026-10", None),
            ("2026-11", "rule_superseded"),
        ]
    refs = SqlAlchemyRuleVersionRefs
    with app_engine.begin() as connection:
        cached = refs(connection).get(version)
    assert cached is not None
    assert (cached.status, cached.effective_to) == (RuleVersionStatus.SUPERSEDED, date(2026, 11, 1))

    late = await app.decide(second, BusinessId.new(), version)
    assert late is Outcome.PROCESSED
    labels = [row["period_label"] for row in app.obligations(second)]
    assert sorted(labels) == ["2026-09", "2026-09", "2026-10", "2026-10", "2026-11"], (
        "only September, still due, and October for a new business"
    )


async def test_a_business_new_after_a_supersession_gets_the_month_before_once(
    app_engine: Engine,
) -> None:
    """For a business onboarded on 5 October the engine decides the version superseded from 1
    October, which still governs September (due 20 October), and its replacement: September is
    made once, of the older version, October and November of the newer. Another decision of the
    older version (a later profile change) and the rolling window of that day add nothing."""
    older, newer = rule(), rule(effective_from=date(2026, 10, 1))
    superseded = ref_of(older, status=RuleVersionStatus.SUPERSEDED, effective_to=date(2026, 10, 1))
    app = Worker(app_engine, FakeRuleVersionReader([older, newer], refs=[superseded]))
    tenant, business = TenantId.new(), BusinessId.new()
    on_the_5th = datetime(2026, 10, 5, 4, 30, tzinfo=UTC)
    for version in (older, newer, older):
        decided = await app.decide(tenant, business, version.rule_version_id, decided_at=on_the_5th)
        assert decided is Outcome.PROCESSED
    rolled = RollWindow(
        PostgresUnitOfWorkFactory(app_engine),
        PostgresTenantDirectory(app_engine),
        app.rules,
        clock=lambda: on_the_5th,
    ).run(only={tenant})
    assert (rolled.tenants, rolled.created) == (1, ())

    made = [(row["period_label"], row["rule_version_id"]) for row in app.obligations(tenant)]
    assert made == [
        ("2026-09", older.rule_version_id.value),
        ("2026-10", newer.rule_version_id.value),
        ("2026-11", newer.rule_version_id.value),
    ]
    assert app.outbox(tenant, "obligation.created") == 3
    september = app.obligations(tenant)[0]
    assert september["due_at"].astimezone(IST).date() == date(2026, 10, 20)


async def test_a_deadline_change_reschedules_both_tenants(app_engine: Engine) -> None:
    the_rule = rule()
    version = the_rule.rule_version_id
    app = Worker(app_engine, FakeRuleVersionReader([the_rule]))
    first, second = await held_by_two_tenants(app, version)
    changed = rule_event(
        "rule.deadline_changed",
        "period-extended",
        rule_version_id=version,
        period_label="2026-10",
        new_due_on=date(2026, 11, 27),
    )
    assert await app.rule_events.process(changed) is Outcome.PROCESSED
    for tenant in (first, second):
        rows = app.obligations(tenant)
        october = [row for row in rows if row["period_label"] == "2026-10"]
        assert [row["due_at"].date() for row in october] == [date(2026, 11, 27)]
        assert app.outbox(tenant, "obligation.rescheduled") == 1
    again = rule_event(
        "rule.deadline_changed",
        "period-extended",
        rule_version_id=version,
        period_label="2026-10",
        new_due_on=date(2026, 11, 27),
    )
    assert await app.rule_events.process(again) is Outcome.PROCESSED
    assert [app.outbox(t, "obligation.rescheduled") for t in (first, second)] == [1, 1]


async def test_a_decision_planned_before_the_withdrawal_is_refused_after_it(
    app_engine: Engine,
) -> None:
    """The decision's read happens before the withdrawal is cached, its write after: the
    cache row it locks says withdrawn."""
    the_rule = rule()
    version = the_rule.rule_version_id
    rules = FakeRuleVersionReader([the_rule])
    app = Worker(app_engine, rules)
    tenant, _ = await held_by_two_tenants(app, version)
    apply = ApplyDecision(rules)
    plan = apply.plan(
        Decision(
            tenant_id=tenant,
            decision_id=DecisionId.new(),
            business_id=BusinessId.new(),
            rule_version_id=version,
            result=Applicability.APPLIES,
            needs_review=False,
            decided_at=DECIDED_AT,
        )
    )
    rules.end(version, RuleVersionStatus.WITHDRAWN)
    withdrawn = rule_event("rule.withdrawn", "withdrawn-by-an-analyst", rule_version_id=version)
    assert await app.rule_events.process(withdrawn) is Outcome.PROCESSED
    with app_engine.connect() as connection:
        applied = apply.apply(plan, PostgresUnitOfWorkFactory.on_connection(connection))
        connection.commit()
    assert (applied.outcome, applied.refusal) == (DecisionOutcome.REFUSED, Refusal.RULE_WITHDRAWN)
    assert {row["status"] for row in app.obligations(tenant)} == {"closed_not_applicable"}


def test_the_cache_merges_on_postgres(app_engine: Engine) -> None:
    the_rule = rule()
    with app_engine.begin() as connection:
        refs = SqlAlchemyRuleVersionRefs(connection)
        stored = refs.merge(ref_of(the_rule))
        assert refs.get(the_rule.rule_version_id) == stored
        newer = replace(
            ref_of(the_rule, title="Retitled"),
            fetched_at=stored.fetched_at.replace(hour=stored.fetched_at.hour + 1),
        )
        ended = refs.merge(newer.ended(RuleVersionStatus.SUPERSEDED, date(2026, 11, 1)))
        assert (ended.title, ended.status, ended.effective_to) == (
            "Retitled",
            RuleVersionStatus.SUPERSEDED,
            date(2026, 11, 1),
        )
        assert refs.merge(ref_of(the_rule)) == ended, "an older read changes nothing"
        assert refs.get(the_rule.rule_version_id, lock=True) == ended
    assert ended.citations == ref_of(the_rule).citations, "the citations round-trip as JSON"


async def test_the_sweep_command_runs_once_as_of_now(app_engine: Engine, app_url: str) -> None:
    the_rule = rule()
    rules = FakeRuleVersionReader([the_rule])
    app = Worker(app_engine, rules)
    tenant, other = await held_by_two_tenants(app, the_rule.rule_version_id)
    settings = ObligationSettings(
        _env_file=None,
        service_name="obligation-sweep",
        env="test",
        obligation_store="postgres",
        database_url=app_url,
    )
    out = io.StringIO()
    argv = ["--once", "--json", "--now", "2026-11-15T09:30:00+05:30", "--tenant", str(tenant)]
    assert sweep.main(argv, settings=settings, rules=rules, stdout=out) == 0
    report = json.loads(out.getvalue())
    assert (report["tenants"], len(report["reminded"]), len(report["created"])) == (1, 1, 1)
    assert app.outbox(tenant, "obligation.due_soon") == 1
    assert app.outbox(other, "obligation.due_soon") == 0, "a tenant not named is left alone"
    assert sorted(row["period_label"] for row in app.obligations(tenant)) == [
        "2026-09",
        "2026-10",
        "2026-11",
        "2026-12",
    ]
    again = io.StringIO()
    assert sweep.main(argv, settings=settings, rules=rules, stdout=again) == 0
    assert json.loads(again.getvalue())["reminded"] == [], "each reminder once"
    assert str(UUID(report["reminded"][0])) in {str(row["id"]) for row in app.obligations(tenant)}
