"""A withdrawn rule closes its obligations in both synthetic tenants and sends withdrawal notices,
a deadline change reschedules a period, and a sweep run before a due date sends a reminder: the
rule events through obligation's consumer of group ``obligation.rules``, on the one deployable's
memory stores.

The whole app runs as ``cw-mvp serve`` runs it (``running_app``), with publishing on, the
rulebook's tokens, the notification sink and no batching window, and the seed calendar loaded as
drafts. A pump stands in for the worker: every profile.updated goes to the engine's profile
consumer (recompute on), every rule event the rulebook stores to the engine's rules consumer
(fan-out on) and to obligation's rules consumer (the flag on), every applicability.decided to
obligation's decision consumer, and every obligation event to notification's consumer, each
through an ``IdempotentConsumer`` on a SQLite inbox; the dispatcher sends what is due through the
sink. ``cw-product seed`` publishes the GSTR-3B rules, gstr9_annual is published and fans out to
both tenants, and the check's reminders and rollback steps then run against it unchanged.

The deadline change is published as the rulebook writes one into its outbox (a
``RuleDeadlineChanged`` of the monthly rule's version, caused by a synthetic draft): the product's
seed has no extension with an approved ``extends_deadline`` relation to publish.
"""

import asyncio
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

from applicability_engine import worker as engine_worker
from applicability_engine.application.fanout_activities import fanout_activities
from applicability_engine.application.rule_events import RuleEvents as EngineRuleEvents
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory
from applicability_engine.infrastructure.memory import MemoryStore as EngineStore
from applicability_engine.main import http_readers
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import LocalFanOuts
from cw_demo.product import check
from cw_demo.product.check import CheckContext
from cw_demo.product.client import Product, ProductSettings, as_tenant, ok
from cw_demo.product.publish import DEFAULT_RULES, publish, rule_versions
from cw_demo.product.seed import seed
from cw_demo.product.tenants import BUSINESS_TENANT, CA_FIRM_TENANT, TENANTS
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, ClauseId, CorrelationId, RuleId, RuleVersionId, TenantId
from domain_kernel.predicates import specification_to_mapping
from notification import worker as notification_worker
from obligation import sweep
from obligation import worker as obligation_worker
from obligation.application.decisions import ApplyDecision
from obligation.application.materialise import IST
from obligation.application.rule_events import RuleEvents
from obligation.infrastructure.memory import MemoryStore as ObligationStore
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from ontology import load as load_ontology
from py_common.events import encode, to_message
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
    read_first_store,
    sync_handler,
)
from py_common.outbox.testing import FakeProducer
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.events import DeadlineChangeReason, RuleDeadlineChanged
from rulebook.infrastructure.memory import MemoryKnowledgeStore

WRITE_TOKEN: Final = "rollback-test-write-token"
REVIEW_TOKEN: Final = "rollback-test-review-token"
GSTR9: Final = "gstr9_annual"
MONTHLY: Final = "gstr3b_monthly"
OBLIGATIONS: Final = "/v1/obligation/obligations"
NOTIFICATIONS: Final = "/v1/notification/notifications"
RULE_TOPICS: Final = frozenset(obligation_worker.RULE_TOPICS)


def services(sink: Path) -> dict[str, dict[str, Any]]:
    return {
        **{name: dict(values) for name, values in MEMORY_SERVICES.items()},
        "profile": {"profile_store": "memory", "profile_gstin_lookup": "static"},
        "rulebook": {
            "rulebook_store": "memory",
            "rulebook_publish_enabled": True,
            "rulebook_write_token": WRITE_TOKEN,
            "rulebook_review_token": REVIEW_TOKEN,
        },
        "notification": {
            "notification_store": "memory",
            "notification_channels": "sink",
            "notification_sink_path": str(sink),
            "notification_batch_window_seconds": 0,
        },
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
    """The worker's part, without Kafka or Temporal: each new event of a store goes to the
    consumers that read it, the fan-outs run on threads of the process, and the dispatcher sends
    what is due."""

    def __init__(self, app: CombinedApp, tmp_path: Path) -> None:
        url = app.settings.mvp_internal_url
        wirings = {
            name: app.services[name].state.wiring
            for name in (
                "profile",
                "rulebook",
                "applicability-engine",
                "obligation",
                "notification",
            )
        }
        self.profiles = wirings["profile"].unit_of_work
        self.rulebook = wirings["rulebook"].unit_of_work
        self.engine = wirings["applicability-engine"].unit_of_work
        self.obligations = wirings["obligation"].unit_of_work
        self.notification = wirings["notification"]
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
        self.reader = HttpRuleVersionReader(url)
        self.producer = FakeProducer()
        config = ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0)
        engine_store, obligation_store = self.engine, self.obligations

        def consumer(group: str, handler: Any, path: str, *, read_first: bool) -> Any:
            engine = inbox(tmp_path / path)
            store = (
                read_first_store(engine, group)
                if read_first
                else SyncProcessedStore(engine, group_id=group)
            )
            return IdempotentConsumer(
                group_id=group, store=store, handler=handler, producer=self.producer, config=config
            )

        self.consumers: tuple[tuple[str, frozenset[str], Any], ...] = (
            (
                "profile",
                frozenset({"profile.updated"}),
                consumer(
                    engine_worker.GROUP_ID,
                    engine_worker.profile_handler(
                        engine_worker.recompute_of(settings, readers),
                        units_on=lambda connection: engine_store,
                    ),
                    "profiles.sqlite",
                    read_first=True,
                ),
            ),
            (
                "rulebook",
                frozenset({"rule.published", "rule.withdrawn"}),
                consumer(
                    engine_worker.RULES_GROUP_ID,
                    engine_worker.rules_handler(
                        EngineRuleEvents(readers.rulebook, self.fanouts, enabled=True),
                        units_on=lambda connection: engine_store.fanouts,
                    ),
                    "engine-rules.sqlite",
                    read_first=True,
                ),
            ),
            (
                "rulebook",
                RULE_TOPICS,
                consumer(
                    obligation_worker.RULES_GROUP_ID,
                    obligation_worker.rules_handler(
                        RuleEvents(self.reader, enabled=True),
                        units_on=self.obligation_units,
                        refs_on=lambda connection: obligation_store.rule_version_refs(),
                        tenants_on=lambda connection: obligation_store,
                    ),
                    "obligation-rules.sqlite",
                    read_first=True,
                ),
            ),
            (
                "engine",
                frozenset({"applicability.decided"}),
                consumer(
                    obligation_worker.GROUP_ID,
                    obligation_worker.decision_handler(
                        ApplyDecision(self.reader), units_on=self.obligation_units
                    ),
                    "decisions.sqlite",
                    read_first=True,
                ),
            ),
            (
                "obligation",
                frozenset(
                    {
                        "obligation.created",
                        "obligation.due_soon",
                        "obligation.rescheduled",
                        "obligation.closed",
                    }
                ),
                consumer(
                    notification_worker.GROUP_ID,
                    sync_handler(
                        notification_worker.obligation_handler(
                            self.notification.enqueue, unit_on=self.notification_unit
                        )
                    ),
                    "notifications.sqlite",
                    read_first=False,
                ),
            ),
        )
        self.handed: dict[int, int] = {}
        self.outcomes: list[Outcome] = []
        self.lock = threading.Lock()

    def obligation_units(self, connection: Connection) -> Any:
        return self.obligations

    def notification_unit(self, connection: Connection, tenant_id: TenantId) -> Any:
        return self.notification.unit_of_work(tenant_id)

    def sources(self) -> dict[str, list[DomainEvent]]:
        assert isinstance(self.rulebook, MemoryKnowledgeStore)
        assert isinstance(self.engine, EngineStore)
        assert isinstance(self.obligations, ObligationStore)
        return {
            "profile": list(self.profiles.events),
            "rulebook": list(self.rulebook.events()),
            "engine": list(self.engine.events),
            "obligation": list(self.obligations.events),
        }

    def drain(self) -> None:
        with self.lock:
            events = self.sources()
            for index, (source, topics, consumer) in enumerate(self.consumers):
                handed = self.handed.get(index, 0)
                new = events[source][handed:]
                for offset, event in enumerate(new, start=handed):
                    if type(event).topic in topics:
                        self.outcomes.append(asyncio.run(consumer.process(record(event, offset))))
                self.handed[index] = handed + len(new)
            self.notification.dispatch.run()

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
            self.reader.close()

    def sweep(self, arguments: Sequence[str]) -> tuple[int, dict[str, Any]]:
        """``obligation-sweep --once --json`` on the memory store, as the reminders step runs it
        on the product's database."""
        args = sweep.parser().parse_args(["--once", "--json", *arguments])
        assert isinstance(self.obligations, ObligationStore)
        only = None if not args.tenant else {TenantId(tenant) for tenant in args.tenant}
        with self.lock:
            report = sweep.run_once(
                self.obligations, self.obligations, self.reader, now=args.now, only=only
            )
        return (1 if report.failed else 0), report.as_json()


def load_seed_drafts(app: CombinedApp) -> MemoryKnowledgeStore:
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
    return store


@contextmanager
def product_of(app: CombinedApp, sink: Path) -> Iterator[Product]:
    settings = ProductSettings(
        _env_file=None,
        service_name="cw-product",
        mvp_host=LOCALHOST,
        mvp_public_port=app.settings.mvp_public_port,
        mvp_internal_port=app.settings.mvp_internal_port,
        mvp_internal_url=app.settings.mvp_internal_url,
        rulebook_write_token=SecretStr(WRITE_TOKEN),
        rulebook_review_token=SecretStr(REVIEW_TOKEN),
        notification_sink_path=str(sink),
    )
    public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
    with (
        httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
        httpx2.Client(base_url=public_url, timeout=30.0) as public,
        httpx2.Client(base_url=public_url, timeout=30.0) as worker,
    ):
        yield Product(settings, internal, public, worker)


def obligations_of(
    product: Product, tenant: UUID, business_id: str, version_id: str
) -> list[dict[str, Any]]:
    listed: list[dict[str, Any]] = ok(
        product.internal.get(
            OBLIGATIONS,
            params={"business_id": business_id, "rule_version_id": version_id},
            headers=as_tenant(tenant),
        )
    )
    return listed


def test_a_withdrawal_closes_both_tenants_obligations_and_a_deadline_change_moves_one(
    tmp_path: Path,
) -> None:
    sink = tmp_path / "sink.jsonl"
    with running_app(service_overrides=services(sink)) as app:
        rulebook = load_seed_drafts(app)
        pump = Pump(app, tmp_path)
        with pump.running(), product_of(app, sink) as product:
            report = seed(product, rules=DEFAULT_RULES, state_path=tmp_path / "last.json")
            seeded = {b.key: b.registration_id for t in report.tenants for b in t.businesses}
            context = CheckContext(
                product, timeout=30.0, interval=0.1, destructive=True, sweep=pump.sweep
            )
            check.poll(
                lambda: _in_directory(pump.engine, list(seeded.values())),
                timeout=30.0,
                interval=0.1,
            )
            (gstr9,) = publish(product, [GSTR9]).rules
            check.poll(
                lambda: _held_in_both(context, gstr9.rule_version_id), timeout=30.0, interval=0.1
            )

            reminded = check.reminders(context)
            skipped = check.run_checks(CheckContext(product), check.select(["rollback"]))
            rolled_back = check.rollback(context)
            again = check.rollback(context)

            (monthly,) = [v for v in rule_versions(product, MONTHLY) if v["status"] == "published"]
            moved = change_a_deadline(product, rulebook, pump, str(monthly["rule_version_id"]))

    assert reminded[0].startswith("obligation-sweep --once --now ")
    assert reminded[2].startswith("reminder: email sent through the sink (sink:")
    assert (skipped[0].skipped, skipped[0].details) == (True, ["skipped (destructive; CI runs it)"])

    assert rolled_back[0] == (
        f"{GSTR9} v1 withdrawn ({gstr9.rule_version_id}) as Demo reviewer one (synthetic)"
    )
    business_line = next(line for line in rolled_back if line.startswith(BUSINESS_TENANT.name))
    firm_line = next(line for line in rolled_back if line.startswith(CA_FIRM_TENANT.name))
    assert "GSTR-9 obligations closed (rule_withdrawn)" in business_line
    assert "email sent" in business_line
    assert "GSTR-9 obligations closed (rule_withdrawn)" in firm_line
    assert "digest_pending" in firm_line or "email sent" in firm_line, (
        "the CA firm hears by its daily digest, held until 09:00 IST"
    )
    assert any(line.endswith("holds the message") for line in rolled_back)
    assert (
        again[0]
        == f"{GSTR9} was withdrawn before ({gstr9.rule_version_id}): checking what followed"
    )

    obligations = pump.obligations
    assert isinstance(obligations, ObligationStore)
    version = RuleVersionId(UUID(gstr9.rule_version_id))
    closed = [o for o in obligations.obligations.values() if o.rule_version_id == version]
    assert {o.tenant_id.value for o in closed} == {tenant.tenant_id for tenant in TENANTS}
    assert {o.closed_reason.value for o in closed if o.closed_reason} == {"rule_withdrawn"}
    assert all(not o.is_open for o in closed)
    assert obligations.rule_versions[version].status.value == "withdrawn"

    previous, new_due_at, notice = moved
    assert new_due_at - previous == timedelta(days=5)
    assert (notice["occasion"], notice["template_key"], notice["state"]) == (
        "reschedule",
        "obligation_deadline_extended",
        "sent",
    )
    assert Outcome.DEAD not in pump.outcomes
    assert pump.producer.sent == []


def change_a_deadline(
    product: Product, rulebook: MemoryKnowledgeStore, pump: Pump, monthly_id: str
) -> tuple[datetime, datetime, dict[str, Any]]:
    """rule.deadline_changed for the first open period of the business tenant's monthly
    obligations, five days later, as the rulebook writes it when an extension is published;
    the obligation is rescheduled and the owner hears about it through the sink."""
    registration = check.the_registration(CheckContext(product, timeout=30.0, interval=0.1))
    tenant = BUSINESS_TENANT.tenant_id
    listed = obligations_of(product, tenant, registration.registration_id, monthly_id)
    target = min((o for o in listed if o["status"] == "open"), key=lambda o: str(o["due_at"]))
    previous = datetime.fromisoformat(str(target["due_at"]))
    _, extension = rulebook.add_rule(
        "example_extension_synthetic", title="Example extension of GSTR-3B (synthetic)"
    )
    with rulebook() as uow:
        uow.events.publish(
            RuleDeadlineChanged(
                occurred_at=datetime.now(UTC),
                correlation_id=CorrelationId.new(),
                rule_id=RuleId.new(),
                rule_version_id=RuleVersionId(UUID(monthly_id)),
                caused_by_rule_version_id=extension,
                period_label=str(target["period_label"]),
                new_due_on=(previous + timedelta(days=5)).astimezone(IST).date(),
                reason=DeadlineChangeReason.DEADLINE_EXTENDED,
                evidence_clause_id=ClauseId.new(),
            )
        )

    def rescheduled() -> tuple[datetime, dict[str, Any]]:
        after = obligations_of(product, tenant, registration.registration_id, monthly_id)
        (now,) = [o for o in after if o["obligation_id"] == target["obligation_id"]]
        moved_to = datetime.fromisoformat(str(now["due_at"]))
        if moved_to == previous:
            raise check.NotYetError("the obligation is not rescheduled yet")
        page = ok(
            product.internal.get(
                NOTIFICATIONS,
                params={"business_id": registration.registration_id, "limit": 200},
                headers=as_tenant(tenant),
            )
        )
        sent = [
            n
            for n in page["items"]
            if n["occasion"] == "reschedule"
            and n["obligation_id"] == target["obligation_id"]
            and n["state"] == "sent"
        ]
        if not sent:
            raise check.NotYetError("no reschedule notice sent yet")
        return moved_to, sent[0]

    moved_to, notice = check.poll(rescheduled, timeout=30.0, interval=0.1)
    return previous, moved_to, notice


def _in_directory(store: Any, registration_ids: Sequence[str]) -> bool:
    assert isinstance(store, EngineStore)
    missing = [r for r in registration_ids if BusinessId(UUID(r)) not in store.directory]
    if missing:
        raise check.NotYetError(f"{len(missing)} registrations are not in the directory yet")
    return True


def _held_in_both(context: CheckContext, version_id: str) -> bool:
    holders = check.gstr9_holders(context, version_id)
    if set(holders) != {tenant.key for tenant in TENANTS}:
        raise check.NotYetError(f"GSTR-9 obligations only in {sorted(holders)}")
    return True
