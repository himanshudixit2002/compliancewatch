"""The changes feed, the impact of a change and a dry run, end to end on the one deployable's
memory stores: a publication reaches the rulebook's feed with its synthetic approvers and its
needs_review status, its fan-out decides both synthetic tenants, the CA firm's impact lists its
affected client, and a dry run scoped to the firm counts what the fan-out decided while writing
nothing but its audit entry.

The whole app runs as ``cw-mvp serve`` runs it (``running_app``), with publishing on and the
rulebook's tokens, and the seed calendar loaded as drafts. A pump stands in for the worker: every
profile.updated the profile service stores goes to the engine's profile consumer (recompute on),
and every rule.published and rule.withdrawn the rulebook stores to the engine's rules consumer
(the fan-out on), each through an ``IdempotentConsumer`` on a SQLite inbox; the fan-outs run in
the process (``LocalFanOuts``). ``cw-product seed`` publishes the GSTR-3B rules, ``cw-product
publish`` publishes gstr9_annual, and the check's changes step then runs against it unchanged,
twice.
"""

import asyncio
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Final
from uuid import UUID

import httpx2
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from applicability_engine import worker as engine_worker
from applicability_engine.application.dry_run import DRY_RUN_ACTION
from applicability_engine.application.fanout_activities import fanout_activities
from applicability_engine.application.rule_events import RuleEvents
from applicability_engine.domain.fanout import FanOutStatus
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory
from applicability_engine.infrastructure.memory import MemoryStore as EngineStore
from applicability_engine.main import http_readers
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import LocalFanOuts
from cw_demo.product import check
from cw_demo.product.check import CheckContext, NotYetError
from cw_demo.product.client import Product, ProductSettings, as_tenant, ok
from cw_demo.product.publish import DEFAULT_RULES, publish
from cw_demo.product.records import AuditRecord
from cw_demo.product.seed import seed
from cw_demo.product.tenants import CA_FIRM_TENANT
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import specification_to_mapping
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

WRITE_TOKEN: Final = "changes-test-write-token"
REVIEW_TOKEN: Final = "changes-test-review-token"
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
    """``ProductRecords`` over the engine's memory store, which keeps no creation times."""

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
                correlation_id=entry.correlation_id,
            )
            for entry in self._store.audit
            if entry.action in actions and entry.occurred_at >= since
        ]

    def engine_rows(self, tenant_id: UUID) -> dict[str, int]:
        def of(tenant: TenantId | None) -> bool:
            return tenant is not None and tenant.value == tenant_id

        return {
            "applicability_decision": sum(of(d.tenant_id) for d in self._store.decisions.values()),
            "review_item": sum(of(item.tenant_id) for item in self._store.reviews.values()),
            "outbox_event": sum(of(event.tenant_id) for event in self._store.events),
        }


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
    """The worker's part the changes need, without Kafka or Temporal: profile.updated and the
    rule events to the engine's consumers, and the fan-outs on threads of the process."""

    def __init__(self, app: CombinedApp, tmp_path: Path) -> None:
        url = app.settings.mvp_internal_url
        self.profiles = app.services["profile"].state.wiring.unit_of_work
        self.rulebook = app.services["rulebook"].state.wiring.unit_of_work
        self.engine = app.services["applicability-engine"].state.wiring.unit_of_work
        assert isinstance(self.rulebook, MemoryKnowledgeStore)
        assert isinstance(self.engine, EngineStore)
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
        self.handed = {"profile": 0, "rulebook": 0}
        self.outcomes: list[Outcome] = []

    def drain(self) -> None:
        assert isinstance(self.rulebook, MemoryKnowledgeStore)
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


def listed(engine: EngineStore, registration_ids: Sequence[str]) -> bool:
    missing = [r for r in registration_ids if BusinessId(UUID(r)) not in engine.directory]
    if missing:
        raise NotYetError(f"{len(missing)} registrations are not in the directory yet")
    return True


def completed(engine: EngineStore) -> str:
    runs = [run for run in engine.fanout_runs.values() if run.rule_key == GSTR9]
    if not runs or runs[0].status is not FanOutStatus.COMPLETED:
        raise NotYetError(f"the fan-out of {GSTR9} has not completed")
    return str(runs[0].rule_version_id)


def test_the_feed_the_impact_and_a_dry_run_follow_a_publication(tmp_path: Path) -> None:
    with running_app(service_overrides=SERVICES) as app:
        load_seed_drafts(app)
        pump = Pump(app, tmp_path)
        engine = pump.engine
        assert isinstance(engine, EngineStore)
        with pump.running(), product_of(app) as product:
            report = seed(product, rules=DEFAULT_RULES, state_path=tmp_path / "last.json")
            seeded = [b.registration_id for t in report.tenants for b in t.businesses]
            context = CheckContext(
                product, timeout=30.0, interval=0.1, records=MemoryRecords(engine)
            )
            (refused,) = check.run_checks(context, check.select(["changes"]))
            assert not refused.ok, "nothing of gstr9_annual is published yet"
            assert "was never published" in refused.error
            check.poll(lambda: listed(engine, seeded), timeout=30.0, interval=0.1)
            publish(product, [GSTR9])
            version_id = check.poll(lambda: completed(engine), timeout=30.0, interval=0.1)
            decisions = len(engine.decisions)
            first = check.changes(context)
            second = check.changes(context)
            feed = ok(product.internal.get("/v1/changes", params={"limit": 100}))
            unknown = ok(
                product.internal.get(
                    "/v1/changes/00000000-0000-4000-8000-000000000999/impact",
                    headers=as_tenant(CA_FIRM_TENANT.tenant_id),
                )
            )

        assert first[0].startswith(f"GET /v1/changes: {GSTR9} v1 published")
        assert "approved by Demo reviewer one (synthetic) and Demo reviewer two" in first[0]
        assert "seed status needs_review" in first[0]
        assert first[1].startswith(f"{CA_FIRM_TENANT.name}: {GSTR9} applies to ")
        assert first[1].endswith("the fan-out completed")
        assert first[2].startswith(f"dry run of {GSTR9} (published) for {CA_FIRM_TENANT.name}")
        assert "2 of 2 decided (1 applies, 1 not_applicable, 0 unsure)" in first[2]
        assert "as the firm's decisions of the registrations the directory lists count" in first[2]
        assert first[3].startswith(f"wrote one {DRY_RUN_ACTION} row of no tenant")
        assert second[2] == first[2], "a second dry run counts the same"
        assert len(engine.decisions) == decisions, "the dry runs stored no decision"
        dry_runs = [entry for entry in engine.audit if entry.action == DRY_RUN_ACTION]
        assert len(dry_runs) == 2
        assert {entry.subject_id for entry in dry_runs} == {version_id}
        assert {entry.tenant_id for entry in dry_runs} == {None}
        kinds = [(item["kind"], item["rule_key"]) for item in feed["items"]]
        assert kinds[0] == ("published", GSTR9), "the newest change"
        assert {key for kind, key in kinds if kind == "published"} == {GSTR9, *DEFAULT_RULES}
        assert all(item["seed_status"] == "needs_review" for item in feed["items"])
        assert (unknown["items"], unknown["fan_out"]) == ([], None)
        assert Outcome.DEAD not in pump.outcomes
        assert pump.fanouts.failures == {}
