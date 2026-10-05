"""A rule published behind the fan-out hold reaches every business once the hold is released:
rule.published through the engine's rules consumer and its fan-out, applicability.decided through
obligation's consumer, on the one deployable's memory stores.

The whole app runs as ``cw-mvp serve`` runs it (``running_app``), with publishing on and the
rulebook's tokens, and the seed calendar loaded as drafts. A pump stands in for the worker: every
profile.updated the profile service stores goes to the engine's profile consumer (recompute on),
every rule.published and rule.withdrawn the rulebook stores to the engine's rules consumer (group
``applicability-engine.rules``, the flag on), and every applicability.decided to obligation's
consumer, each through an ``IdempotentConsumer`` on a SQLite inbox; the fan-outs run in the
process (``LocalFanOuts``), through the loop and the activities the Temporal workflow runs. The
check's fanout step then runs against it unchanged, twice: first it holds, publishes gstr9_annual
and releases, then it finds the completed run.
"""

import asyncio
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

from applicability_engine import worker as engine_worker
from applicability_engine.application.fanout_activities import fanout_activities
from applicability_engine.application.rule_events import RuleEvents
from applicability_engine.domain.fanout import FanOutStatus
from applicability_engine.domain.model import Trigger
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory
from applicability_engine.infrastructure.memory import MemoryStore as EngineStore
from applicability_engine.main import http_readers
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import LocalFanOuts
from cw_demo.product import check
from cw_demo.product.check import CheckContext
from cw_demo.product.client import Product, ProductSettings
from cw_demo.product.publish import DEFAULT_RULES
from cw_demo.product.records import AuditRecord
from cw_demo.product.seed import seed
from cw_demo.product.tenants import BUSINESS_TENANT, CA_FIRM_TENANT, TENANTS
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, RuleVersionId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import specification_to_mapping
from obligation import worker as obligation_worker
from obligation.application.decisions import ApplyDecision
from obligation.infrastructure.memory import MemoryStore as ObligationStore
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from ontology import load as load_ontology
from py_common.events import encode, to_message
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    processed_event,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer
from rulebook.application.seed_loader import load_calendar
from rulebook.infrastructure.memory import MemoryKnowledgeStore

WRITE_TOKEN: Final = "publication-test-write-token"
REVIEW_TOKEN: Final = "publication-test-review-token"
SERVICES: Final = {
    **MEMORY_SERVICES,
    "profile": {"profile_store": "memory", "profile_gstin_lookup": "static"},
    "rulebook": {
        "rulebook_store": "memory",
        "rulebook_publish_enabled": True,
        "rulebook_write_token": WRITE_TOKEN,
        "rulebook_review_token": REVIEW_TOKEN,
    },
}
GSTR9: Final = "gstr9_annual"


class MemoryRecords:
    """``ProductRecords`` over the engine's memory store, which keeps no creation times: every
    entry it lists counts, whatever ``as_of``."""

    def __init__(self, store: EngineStore) -> None:
        self._store = store

    def directory_count(self, level: str, *, as_of: datetime | None = None) -> int:
        return MemoryBusinessDirectory(self._store).count(level=AttributeLevel(level))

    def listed(self, business_ids: Iterable[str], *, as_of: datetime | None = None) -> set[str]:
        return {
            business_id
            for business_id in business_ids
            if BusinessId(UUID(business_id)) in self._store.directory
        }

    def audit_entries(self, *, actions: Sequence[str], since: datetime) -> list[AuditRecord]:
        return [
            AuditRecord(
                action=entry.action,
                subject_type=entry.subject_type,
                subject_id=entry.subject_id,
                actor_label=entry.actor.label,
                reason=entry.reason,
                occurred_at=entry.occurred_at,
                tenant_id=None if entry.tenant_id is None else entry.tenant_id.value,
            )
            for entry in self._store.audit
            if entry.action in actions and entry.occurred_at >= since
        ]


def inbox(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    processed_event.create(engine)
    return engine


def record(event: DomainEvent, offset: int) -> InboundRecord:
    message = to_message(event)
    return InboundRecord(
        topic=message.topic, partition=0, offset=offset, key=b"k", value=encode(message)
    )


class Pump:
    """The worker's part, without Kafka or Temporal: each new event of a store goes to the
    consumer that reads it, and the fan-outs run on threads of the process."""

    def __init__(self, app: CombinedApp, tmp_path: Path) -> None:
        url = app.settings.mvp_internal_url
        wirings = {
            name: app.services[name].state.wiring
            for name in ("profile", "rulebook", "applicability-engine", "obligation")
        }
        self.profiles = wirings["profile"].unit_of_work
        self.rulebook = wirings["rulebook"].unit_of_work
        self.engine = wirings["applicability-engine"].unit_of_work
        self.obligations = wirings["obligation"].unit_of_work
        assert isinstance(self.rulebook, MemoryKnowledgeStore)
        assert isinstance(self.engine, EngineStore)
        assert isinstance(self.obligations, ObligationStore)
        settings = ApplicabilityEngineSettings(
            _env_file=None,
            service_name="applicability-engine-worker",
            profile_url=url,
            rulebook_url=url,
            applicability_recompute_enabled=True,
            applicability_fanout_enabled=True,
            applicability_engine_rules_cache_seconds=0,
        )
        readers = http_readers(settings)
        self.fanouts = LocalFanOuts(
            fanout_activities(
                fanouts=self.engine.fanouts,
                directory=MemoryBusinessDirectory(self.engine),
                unit_of_work=self.engine,
                profiles=readers.profiles,
                rulebook=readers.rulebook,
                ontology=load_ontology(),
            )
        )
        self.producer = FakeProducer()
        config = ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0)
        engine_store = self.engine
        self.profile_consumer = IdempotentConsumer(
            group_id=engine_worker.GROUP_ID,
            store=read_first_store(inbox(tmp_path / "profiles.sqlite"), engine_worker.GROUP_ID),
            handler=engine_worker.profile_handler(
                engine_worker.recompute_of(settings, readers),
                units_on=lambda connection: engine_store,
            ),
            producer=self.producer,
            config=config,
        )
        self.rules_consumer = IdempotentConsumer(
            group_id=engine_worker.RULES_GROUP_ID,
            store=read_first_store(inbox(tmp_path / "rules.sqlite"), engine_worker.RULES_GROUP_ID),
            handler=engine_worker.rules_handler(
                RuleEvents(readers.rulebook, self.fanouts, enabled=True),
                units_on=lambda connection: engine_store.fanouts,
            ),
            producer=self.producer,
            config=config,
        )
        self.obligation_consumer = IdempotentConsumer(
            group_id=obligation_worker.GROUP_ID,
            store=read_first_store(
                inbox(tmp_path / "obligation.sqlite"), obligation_worker.GROUP_ID
            ),
            handler=obligation_worker.decision_handler(
                ApplyDecision(HttpRuleVersionReader(url)), units_on=self.obligation_units
            ),
            producer=self.producer,
            config=config,
        )
        self.handed = {"profile": 0, "rulebook": 0, "engine": 0}
        self.outcomes: list[Outcome] = []

    def obligation_units(self, connection: Connection) -> Any:
        return self.obligations

    def drain(self) -> None:
        assert isinstance(self.rulebook, MemoryKnowledgeStore)
        assert isinstance(self.engine, EngineStore)
        sources: tuple[tuple[str, list[DomainEvent], IdempotentConsumer, frozenset[str]], ...] = (
            (
                "profile",
                list(self.profiles.events),
                self.profile_consumer,
                frozenset({"profile.updated"}),
            ),
            (
                "rulebook",
                list(self.rulebook.events()),
                self.rules_consumer,
                frozenset({"rule.published", "rule.withdrawn"}),
            ),
            (
                "engine",
                list(self.engine.events),
                self.obligation_consumer,
                frozenset({"applicability.decided"}),
            ),
        )
        for source, events, consumer, topics in sources:
            new = events[self.handed[source] :]
            for offset, event in enumerate(new, start=self.handed[source]):
                if type(event).topic in topics:
                    self.outcomes.append(asyncio.run(consumer.process(record(event, offset))))
            self.handed[source] += len(new)

    @contextmanager
    def running(self) -> Iterator["Pump"]:
        stop = threading.Event()

        def loop() -> None:
            while not stop.is_set():
                self.drain()
                stop.wait(0.05)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        try:
            yield self
        finally:
            stop.set()
            thread.join(timeout=10)


def load_seed_drafts(app: CombinedApp) -> None:
    store = app.services["rulebook"].state.wiring.unit_of_work
    assert isinstance(store, MemoryKnowledgeStore)
    for rule in load_calendar(load_ontology()).rules:
        store.add_rule(
            rule.rule_key,
            title=rule.title,
            regulator=rule.regulator,
            level=rule.level,
            effective_from=rule.effective_from,
            summary=rule.summary,
            specification=specification_to_mapping(rule.specification),
            obligation_template=rule.obligation_template.to_mapping(),
            recurrence=None if rule.recurrence is None else rule.recurrence.to_mapping(),
        )


@contextmanager
def product_of(app: CombinedApp) -> Iterator[Product]:
    settings = ProductSettings(
        _env_file=None,
        service_name="cw-product",
        mvp_host=LOCALHOST,
        mvp_public_port=app.settings.mvp_public_port,
        mvp_internal_port=app.settings.mvp_internal_port,
        mvp_internal_url=app.settings.mvp_internal_url,
        rulebook_write_token=SecretStr(WRITE_TOKEN),
        rulebook_review_token=SecretStr(REVIEW_TOKEN),
    )
    public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
    with (
        httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
        httpx2.Client(base_url=public_url, timeout=30.0) as public,
        httpx2.Client(base_url=public_url, timeout=30.0) as worker,
    ):
        yield Product(settings, internal, public, worker)


def test_a_rule_published_behind_the_hold_fans_out_to_both_tenants_once_released(
    tmp_path: Path,
) -> None:
    with running_app(service_overrides=SERVICES) as app:
        load_seed_drafts(app)
        pump = Pump(app, tmp_path)
        with pump.running(), product_of(app) as product:
            report = seed(product, rules=DEFAULT_RULES, state_path=tmp_path / "last.json")
            seeded = [b.registration_id for t in report.tenants for b in t.businesses]
            context = CheckContext(
                product, timeout=30.0, interval=0.1, records=MemoryRecords(pump.engine)
            )
            check.poll(lambda: _listed(pump.engine, seeded), timeout=30.0, interval=0.1)
            first = check.fanout(context)
            second = check.fanout(context)

        assert first[0].startswith(f"hold set, {GSTR9} v1 published")
        assert "the run stood held with 0 of 3 decided and no decision from it" in first[0]
        assert first[1] == "hold released: the run completed"
        assert "3 of 3 decided, 2 apply" in first[2]
        assert f"demo_traders: {GSTR9} applies from the fan-out" in first
        assert f"client_karnataka: {GSTR9} applies from the fan-out" in first
        assert f"client_delhi: {GSTR9} not_applicable from the fan-out" in first
        tenants_with_obligations = [line for line in first if line.endswith("GSTR-9 obligations")]
        assert [line.split(",")[0] for line in tenants_with_obligations] == [
            BUSINESS_TENANT.name,
            CA_FIRM_TENANT.name,
        ]
        assert first[-1].startswith("audit.event: 1 hold, 1 release and 0 resume rows of no tenant")
        assert second[0].startswith(f"{GSTR9} was published before")
        assert "its fan-out is completed" in second[0]
        assert second[1] == "hold set and released again; the completed run stays completed"

        engine = pump.engine
        assert isinstance(engine, EngineStore)
        (gstr9,) = [run for run in engine.fanout_runs.values() if run.rule_key == GSTR9]
        assert (gstr9.status, gstr9.counters.evaluated, gstr9.counters.applies) == (
            FanOutStatus.COMPLETED,
            3,
            2,
        )
        fanned = [
            d
            for d in engine.decisions.values()
            if d.rule_version_id == gstr9.rule_version_id and d.trigger is Trigger.RULE_PUBLISHED
        ]
        assert {str(d.business_id) for d in fanned} == set(seeded)
        assert {d.tenant_id.value for d in fanned} == {tenant.tenant_id for tenant in TENANTS}
        assert {d.trigger_ref for d in fanned} == {f"rule.published:{gstr9.trigger_event_id}"}
        others = [run for run in engine.fanout_runs.values() if run.rule_key != GSTR9]
        assert {run.rule_key for run in others} == set(DEFAULT_RULES), "the seed fanned out too"
        actions = [entry.action for entry in engine.audit]
        assert actions.count("applicability.fanout.hold") == 2
        assert actions.count("applicability.fanout.release") == 2
        assert {entry.tenant_id for entry in engine.audit} == {None}
        obligations = pump.obligations
        assert isinstance(obligations, ObligationStore)
        gstr9_obligations = [
            o
            for o in obligations.obligations.values()
            if o.rule_version_id == RuleVersionId(gstr9.rule_version_id.value)
        ]
        assert {o.tenant_id.value for o in gstr9_obligations} == {
            tenant.tenant_id for tenant in TENANTS
        }
        assert Outcome.DEAD not in pump.outcomes
        assert pump.producer.sent == []
        assert pump.fanouts.failures == {}


def _listed(store: Any, registration_ids: Sequence[str]) -> bool:
    assert isinstance(store, EngineStore)
    missing = [r for r in registration_ids if BusinessId(UUID(r)) not in store.directory]
    if missing:
        raise check.NotYetError(f"{len(missing)} registrations are not in the directory yet")
    return True
