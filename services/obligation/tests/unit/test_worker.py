"""The worker's components, its decision handler and its rule events handler, on a SQLite inbox
and the memory store.

The decision handler decodes the golden applicability.decided examples and applies them; what it
cannot read is dead-lettered through ``FakeProducer``. The rule events handler applies the golden
rule events to every tenant of the store, or nothing with the flag off. Postgres, where every
write commits with the inbox row under row-level security, is covered by
tests/integration/test_obligation_reminders.py and test_obligation_rule_events.py.
"""

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool
from structlog.testing import capture_logs

from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.status import ClosureReason, RuleVersionStatus
from obligation import worker
from obligation.application.decisions import ApplyDecision
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.application.reminders import SendDueReminders
from obligation.application.rule_events import RuleEvents
from obligation.application.window import RollWindow
from obligation.domain.events import ObligationCreated, ObligationRescheduled
from obligation.domain.repository import RuleVersionRefs, TenantDirectory, UnitOfWorkFactory
from obligation.infrastructure.memory import MemoryStore
from obligation.infrastructure.metrics import GuardMetrics, refusals_counter
from obligation.settings import ObligationSettings
from obligation.testing import FakeRuleVersionReader, ref_of, rule
from py_common.events import EventMessage
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    processed_event,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer

EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
TOPIC = "applicability.decided"
DLQ = "applicability.decided.obligation.decisions.dlq"
RULE_VERSION = RuleVersionId(UUID("4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b"))
TENANT = TenantId(UUID("5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a"))
NOW = datetime(2026, 10, 1, 4, 0, tzinfo=UTC)


def obligation_settings(**overrides: Any) -> ObligationSettings:
    """Settings that ignore the repo ``.env``; the memory store unless overridden."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "obligation-worker",
        "obligation_store": "memory",
        "database_url": "postgresql+psycopg://cw:cw@localhost:5432/compliancewatch",
    }
    values.update(overrides)
    return ObligationSettings(**values)


@pytest.fixture
def inbox(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine)
    yield engine
    engine.dispose()


def consumer_of(inbox: Engine, group: str, handler: Any, producer: FakeProducer) -> Any:
    return IdempotentConsumer(
        group_id=group,
        store=read_first_store(inbox, group),
        handler=handler,
        producer=producer,
        config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
    )


class Setup:
    def __init__(self, inbox: Engine, *, enabled: bool = True) -> None:
        self.store = MemoryStore()
        self.rule = replace(rule(), rule_version_id=RULE_VERSION)
        self.rules = FakeRuleVersionReader([self.rule], clock=lambda: NOW)
        self.producer = FakeProducer()
        self.reader = InMemoryMetricReader()
        counter = refusals_counter(MeterProvider(metric_readers=[self.reader]).get_meter("t"))
        handler = worker.decision_handler(
            ApplyDecision(self.rules, clock=lambda: NOW),
            units_on=self.units_on,
            metrics=GuardMetrics(counter),
        )
        self.consumer = consumer_of(inbox, worker.GROUP_ID, handler, self.producer)
        rules_handler = worker.rules_handler(
            RuleEvents(self.rules, enabled=enabled, clock=lambda: NOW),
            units_on=self.units_on,
            refs_on=self.refs_on,
            tenants_on=self.tenants_on,
        )
        self.rule_consumer = consumer_of(inbox, worker.RULES_GROUP_ID, rules_handler, self.producer)

    def units_on(self, connection: Connection) -> UnitOfWorkFactory:
        return self.store

    def refs_on(self, connection: Connection) -> RuleVersionRefs:
        return self.store.rule_version_refs()

    def tenants_on(self, connection: Connection) -> TenantDirectory:
        return self.store

    def created(self) -> list[ObligationCreated]:
        return [e for e in self.store.events if isinstance(e, ObligationCreated)]

    def refusals(self) -> dict[str, int]:
        data = self.reader.get_metrics_data()
        found: dict[str, int] = {}
        for resource in data.resource_metrics if data else ():
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    for point in metric.data.data_points:
                        assert isinstance(point, NumberDataPoint)
                        found[str((point.attributes or {})["reason"])] = int(point.value)
        return found


def record(name: str, offset: int = 0, **payload: Any) -> InboundRecord:
    data = json.loads((EXAMPLES / TOPIC / f"{name}.json").read_text(encoding="utf-8"))
    data["payload"].update(payload)
    data["event_id"] = str(uuid4())
    return InboundRecord(
        topic=TOPIC, partition=0, offset=offset, key=b"k", value=json.dumps(data).encode()
    )


def rule_record(topic: str, name: str, offset: int = 0, **payload: Any) -> InboundRecord:
    data = json.loads((EXAMPLES / topic / f"{name}.json").read_text(encoding="utf-8"))
    data["payload"].update(payload)
    data["event_id"] = str(uuid4())
    return InboundRecord(
        topic=topic, partition=0, offset=offset, key=b"k", value=json.dumps(data).encode()
    )


async def test_an_applying_decision_materialises_once(inbox: Engine) -> None:
    setup = Setup(inbox)
    applies = record("applies-after-rule-published")
    assert await setup.consumer.process(applies) is Outcome.PROCESSED
    assert await setup.consumer.process(applies) is Outcome.SKIPPED, "a redelivery"
    created = setup.created()
    assert len(created) == 2
    assert {e.tenant_id for e in created} == {TENANT}
    assert {str(e.decision_id) for e in created} == {"7b8c9d0e-1f2a-4b3c-8d4e-5f6a7b8c9d0e"}
    assert setup.rules.reads == [RULE_VERSION]
    assert setup.rules.fresh == [], "a decision may use a read made a short while ago"
    assert setup.producer.sent == []
    assert RULE_VERSION in setup.store.rule_versions, "the miss filled the cache"


async def test_a_flip_to_not_applicable_closes_and_review_changes_nothing(inbox: Engine) -> None:
    setup = Setup(inbox)
    assert await setup.consumer.process(record("applies-after-rule-published")) is (
        Outcome.PROCESSED
    )
    unsure = record("unsure-free-text-predicate", offset=1, decision_id=str(uuid4()))
    assert await setup.consumer.process(unsure) is Outcome.PROCESSED
    assert all(o.is_open for o in setup.store.obligations.values())

    flipped = record(
        "applies-after-rule-published",
        offset=2,
        result="not_applicable",
        trigger="profile_updated",
        decided_at="2026-10-01T03:00:00Z",
    )
    assert await setup.consumer.process(flipped) is Outcome.PROCESSED
    assert not any(o.is_open for o in setup.store.obligations.values())


async def test_the_guard_refuses_a_late_decision_and_counts_it(inbox: Engine) -> None:
    setup = Setup(inbox)
    setup.store.rule_versions[RULE_VERSION] = ref_of(
        setup.rule, status=RuleVersionStatus.WITHDRAWN, fetched_at=NOW
    )
    with capture_logs() as logs:
        processed = await setup.consumer.process(record("applies-after-rule-published"))
    assert processed is Outcome.PROCESSED, "a refusal is handled, not retried"
    assert setup.store.obligations == {}
    (guarded,) = [line for line in logs if line["event"] == "obligation.decision_guarded"]
    assert (guarded["refusal"], guarded["status"], guarded["cached"]) == (
        "rule_withdrawn",
        "withdrawn",
        False,
    )
    assert setup.refusals() == {"rule_withdrawn": 1}


async def test_unreadable_decisions_are_dead_lettered(inbox: Engine) -> None:
    setup = Setup(inbox)
    unknown_result = record("applies-after-rule-published", result="maybe")
    assert await setup.consumer.process(unknown_result) is Outcome.DEAD
    data = json.loads(
        (EXAMPLES / TOPIC / "applies-after-rule-published.json").read_text(encoding="utf-8")
    )
    data["tenant_id"] = None
    tenantless = InboundRecord(
        topic=TOPIC, partition=0, offset=1, key=b"k", value=json.dumps(data).encode()
    )
    assert await setup.consumer.process(tenantless) is Outcome.DEAD
    unknown_rule = record("applies-after-rule-published", offset=2, rule_version_id=str(uuid4()))
    assert await setup.consumer.process(unknown_rule) is Outcome.DEAD
    assert setup.producer.topics() == [DLQ, DLQ, DLQ]
    assert setup.store.obligations == {}


async def test_another_topic_is_ignored(inbox: Engine) -> None:
    setup = Setup(inbox)
    other = InboundRecord(
        topic="profile.updated",
        partition=0,
        offset=0,
        key=b"k",
        value=json.dumps(
            {
                "event_id": str(uuid4()),
                "topic": "profile.updated",
                "schema_version": "1.0.0",
                "occurred_at": "2026-10-01T00:00:00Z",
                "tenant_id": str(TENANT),
                "correlation_id": str(uuid4()),
                "causation_id": None,
                "payload": {},
            }
        ).encode(),
    )
    assert await setup.consumer.process(other) is Outcome.PROCESSED
    assert await setup.rule_consumer.process(other) is Outcome.PROCESSED
    assert setup.store.events == []


def message(topic: str, payload: dict[str, Any]) -> EventMessage:
    return EventMessage(
        event_id=uuid4(),
        topic=topic,
        schema_version="1.0.0",
        occurred_at=NOW,
        tenant_id=None,
        correlation_id=uuid4(),
        causation_id=None,
        payload=payload,
    )


def test_rule_events_are_read_from_their_contracts() -> None:
    version, newer = RuleVersionId.new(), RuleVersionId.new()
    published = worker.rule_event_from(
        message(
            "rule.published",
            json.loads((EXAMPLES / "rule.published" / "first-version.json").read_text())["payload"]
            | {"rule_version_id": str(version)},
        )
    )
    assert published is not None
    assert published.rule_version_id == version
    superseded = worker.rule_event_from(
        message(
            "rule.superseded",
            {
                "rule_id": str(uuid4()),
                "rule_version_id": str(version),
                "superseded_by_rule_version_id": str(newer),
                "effective_from": "2026-11-01",
            },
        )
    )
    assert superseded is not None
    assert (superseded.rule_version_id, getattr(superseded, "superseded_by", None)) == (
        version,
        newer,
    )
    assert worker.rule_event_from(message("rule.candidate.created", {})) is None
    with pytest.raises(ValueError, match="effective_from"):
        worker.rule_event_from(
            message("rule.withdrawn", {"rule_id": str(uuid4()), "rule_version_id": str(version)})
        )


def seed_two_tenants(setup: Setup, other: TenantId) -> None:
    """Both periods of the rule for one business in ``TENANT`` and one in ``other``."""
    for tenant in (TENANT, other):
        MaterialiseObligations(setup.store, clock=lambda: NOW).run(
            MaterialiseRequest(tenant, BusinessId.new(), DecisionId.new(), setup.rule, NOW.date())
        )


async def test_a_withdrawal_closes_every_tenants_obligations_once(inbox: Engine) -> None:
    setup = Setup(inbox)
    other = TenantId.new()
    seed_two_tenants(setup, other)
    setup.rules.end(RULE_VERSION, RuleVersionStatus.WITHDRAWN)
    withdrawn = rule_record(
        "rule.withdrawn", "withdrawn-by-an-analyst", rule_version_id=str(RULE_VERSION)
    )
    assert await setup.rule_consumer.process(withdrawn) is Outcome.PROCESSED
    reasons = {(o.tenant_id, o.closed_reason) for o in setup.store.obligations.values()}
    assert reasons == {
        (TENANT, ClosureReason.RULE_WITHDRAWN),
        (other, ClosureReason.RULE_WITHDRAWN),
    }
    assert setup.store.rule_versions[RULE_VERSION].status is RuleVersionStatus.WITHDRAWN
    assert setup.rules.fresh == [RULE_VERSION]
    events = len(setup.store.events)
    replayed = rule_record(
        "rule.withdrawn", "withdrawn-by-an-analyst", rule_version_id=str(RULE_VERSION)
    )
    assert await setup.rule_consumer.process(replayed) is Outcome.PROCESSED
    assert len(setup.store.events) == events, "replaying the event changes nothing"

    late = record("applies-after-rule-published", decision_id=str(uuid4()))
    assert await setup.consumer.process(late) is Outcome.PROCESSED
    assert len(setup.store.events) == events, "a decision after the withdrawal makes nothing"


async def test_a_supersession_closes_the_periods_the_newer_version_takes_over(
    inbox: Engine,
) -> None:
    setup = Setup(inbox)
    other = TenantId.new()
    seed_two_tenants(setup, other)
    superseded = rule_record(
        "rule.superseded",
        "newer-version-in-force",
        rule_version_id=str(RULE_VERSION),
        effective_from="2026-11-01",
    )
    assert await setup.rule_consumer.process(superseded) is Outcome.PROCESSED
    by_period = sorted(
        (o.period_label or "", o.tenant_id == TENANT, o.closed_reason)
        for o in setup.store.obligations.values()
    )
    assert by_period == [
        ("2026-10", False, None),
        ("2026-10", True, None),
        ("2026-11", False, ClosureReason.RULE_SUPERSEDED),
        ("2026-11", True, ClosureReason.RULE_SUPERSEDED),
    ]
    cached = setup.store.rule_versions[RULE_VERSION]
    assert (cached.status, cached.effective_to) == (
        RuleVersionStatus.SUPERSEDED,
        date(2026, 11, 1),
    )


async def test_a_deadline_change_moves_the_period_in_every_tenant(inbox: Engine) -> None:
    setup = Setup(inbox)
    other = TenantId.new()
    seed_two_tenants(setup, other)
    changed = rule_record(
        "rule.deadline_changed",
        "period-extended",
        rule_version_id=str(RULE_VERSION),
        period_label="2026-10",
        new_due_on="2026-11-27",
    )
    assert await setup.rule_consumer.process(changed) is Outcome.PROCESSED
    moved = [e for e in setup.store.events if isinstance(e, ObligationRescheduled)]
    assert {e.tenant_id for e in moved} == {TENANT, other}
    assert {e.new_due_at.date() for e in moved} == {date(2026, 11, 27)}
    assert setup.rules.reads == [], "a deadline change reads nothing"


async def test_with_the_flag_off_rule_events_are_consumed_and_change_nothing(
    inbox: Engine,
) -> None:
    setup = Setup(inbox, enabled=False)
    seed_two_tenants(setup, TenantId.new())
    events = len(setup.store.events)
    withdrawn = rule_record(
        "rule.withdrawn", "withdrawn-by-an-analyst", rule_version_id=str(RULE_VERSION)
    )
    assert await setup.rule_consumer.process(withdrawn) is Outcome.PROCESSED
    assert await setup.rule_consumer.process(withdrawn) is Outcome.SKIPPED, "the offset moved on"
    assert len(setup.store.events) == events
    assert all(o.is_open for o in setup.store.obligations.values())
    assert setup.rules.reads == []


async def test_a_publication_refreshes_the_cache_only(inbox: Engine) -> None:
    setup = Setup(inbox)
    published = rule_record("rule.published", "first-version", rule_version_id=str(RULE_VERSION))
    assert await setup.rule_consumer.process(published) is Outcome.PROCESSED
    assert setup.store.rule_versions[RULE_VERSION] == ref_of(setup.rule, fetched_at=NOW)
    assert setup.store.obligations == {}, "obligations arrive with the decisions"
    unknown = rule_record("rule.published", "first-version", offset=1, rule_version_id=str(uuid4()))
    assert await setup.rule_consumer.process(unknown) is Outcome.PROCESSED
    setup.rules.down = True
    down = rule_record("rule.published", "first-version", offset=2)
    assert await setup.rule_consumer.process(down) is Outcome.DEAD
    assert setup.producer.topics() == ["rule.published.obligation.rules.dlq"]


async def test_a_withdrawal_neither_cached_nor_readable_is_retried(inbox: Engine) -> None:
    setup = Setup(inbox)
    setup.rules.down = True
    withdrawn = rule_record(
        "rule.withdrawn", "withdrawn-by-an-analyst", rule_version_id=str(RULE_VERSION)
    )
    assert await setup.rule_consumer.process(withdrawn) is Outcome.DEAD
    setup.store.rule_versions[RULE_VERSION] = ref_of(setup.rule, fetched_at=NOW)
    again = rule_record(
        "rule.withdrawn", "withdrawn-by-an-analyst", offset=1, rule_version_id=str(RULE_VERSION)
    )
    assert await setup.rule_consumer.process(again) is Outcome.PROCESSED, "the row is moved on"
    assert setup.store.rule_versions[RULE_VERSION].status is RuleVersionStatus.WITHDRAWN


def test_the_components_are_two_consumers_and_the_jobs_when_enabled() -> None:
    rules = FakeRuleVersionReader()
    settings = obligation_settings(obligation_store="postgres")
    components = worker.components(settings, rules=rules)
    decisions, rule_events = components.consumers
    assert (decisions.group_id, decisions.topics) == (
        "obligation.decisions",
        ("applicability.decided",),
    )
    assert decisions.dead_letter_topics() == (DLQ,)
    assert decisions.store_factory is read_first_store
    assert rule_events.group_id == "obligation.rules"
    assert rule_events.topics == (
        "rule.published",
        "rule.superseded",
        "rule.withdrawn",
        "rule.deadline_changed",
    )
    assert rule_events.store_factory is read_first_store
    assert components.periodic == (), "the jobs are off by default"
    assert components.relays == ()
    assert components.temporal == ()

    enabled = obligation_settings(
        obligation_store="postgres",
        obligation_sweep_enabled=True,
        obligation_sweep_interval_seconds=120,
    )
    sweep, window = worker.components(enabled, rules=rules).periodic
    assert (sweep.name, sweep.interval_seconds) == ("obligation-reminder-sweep", 120)
    assert (window.name, window.interval_seconds) == ("obligation-window", None)
    assert window.next_run is not None
    assert window.next_run(datetime(2026, 10, 1, 20, 0, tzinfo=UTC)) == datetime(
        2026, 10, 1, 21, 0, tzinfo=UTC
    ), "02:30 IST"
    assert worker.components(settings).consumers[0].group_id == worker.GROUP_ID
    with pytest.raises(ValueError, match="postgres"):
        worker.components(obligation_settings(), rules=rules)


def test_the_jobs_log_what_they_did() -> None:
    store = MemoryStore()
    job = worker.sweep_job(SendDueReminders(store, store))
    window = worker.window_job(RollWindow(store, store, FakeRuleVersionReader()))
    with capture_logs() as logs:
        job()
        window()
        worker._sweep_failed(TENANT, RuntimeError("boom"))
        worker._window_failed(TENANT, RuntimeError("bang"))
    assert [line["event"] for line in logs] == [
        "obligation.reminders_swept",
        "obligation.window_rolled",
        "obligation.reminder_sweep_failed",
        "obligation.window_failed",
    ]


def test_main_runs_the_components_as_a_worker_process(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(settings: Any, components: Any, *, version: str) -> None:
        seen.update(settings=settings, components=components, version=version)

    monkeypatch.setattr(worker, "run_worker_process", fake_run)
    worker.main()
    assert seen["components"] is worker.components
    assert seen["settings"].service_name == "obligation-worker"
