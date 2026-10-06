"""The public API end to end, on the one deployable's memory stores: a business's obligations a
page at a time, a question the structured layer answers from them, and a CA firm's bulk change
card to the clients a change affects, all through the public listener.

The whole app runs as ``cw-mvp serve`` runs it (``running_app``), with publishing on, the
rulebook's tokens, the notification sink with no batching window, the bulk flag on, and the seed
calendar loaded as drafts. A pump stands in for the worker: every profile.updated goes to the
engine's profile consumer (recompute on), every rule.published and rule.withdrawn to the engine's
rules consumer (the fan-out on, run on threads of the process), every applicability.decided to
obligation's decision consumer, and every obligation event to notification's consumer, each
through an ``IdempotentConsumer`` on a SQLite inbox; the dispatcher sends what is due through the
sink. ``cw-product seed`` publishes the GSTR-3B rules, gstr9_annual is published and fans out to
both tenants, and the check's public step then runs against it unchanged, twice: each run makes a
client contact of its own and removes it afterwards, so the second run queues one card again.
"""

import asyncio
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
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
from cw_demo.product.check import BULK_ACTION, CONTACT_PREFIX, CheckContext, NotYetError
from cw_demo.product.client import Product, ProductSettings, as_tenant, ok
from cw_demo.product.evaluate import IST
from cw_demo.product.publish import DEFAULT_RULES, publish
from cw_demo.product.records import AuditRecord
from cw_demo.product.seed import seed
from cw_demo.product.tenants import CA_FIRM_TENANT
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.predicates import specification_to_mapping
from notification import worker as notification_worker
from notification.domain.occasions import OccasionKind
from notification.infrastructure.memory import MemoryStore as NotificationStore
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
    SyncProcessedStore,
    processed_event,
    read_first_store,
    sync_handler,
)
from py_common.outbox.testing import FakeProducer
from rulebook.application.seed_loader import load_calendar
from rulebook.infrastructure.memory import MemoryKnowledgeStore

WRITE_TOKEN: Final = "public-test-write-token"
REVIEW_TOKEN: Final = "public-test-review-token"
GSTR9: Final = "gstr9_annual"
OBLIGATIONS: Final = "/v1/obligation/obligations"
OBLIGATION_TOPICS: Final = frozenset(
    {"obligation.created", "obligation.due_soon", "obligation.rescheduled", "obligation.closed"}
)


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
            "notification_bulk_enabled": True,
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
        self.profiles = app.services["profile"].state.wiring.unit_of_work
        self.rulebook = app.services["rulebook"].state.wiring.unit_of_work
        self.engine = app.services["applicability-engine"].state.wiring.unit_of_work
        self.obligations = app.services["obligation"].state.wiring.unit_of_work
        self.notification = app.services["notification"].state.wiring
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
        engine_store = self.engine

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
                OBLIGATION_TOPICS,
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

    @property
    def notifications(self) -> NotificationStore:
        store = self.notification.unit_of_work
        assert isinstance(store, NotificationStore)
        return store

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


class NotificationRecords:
    """``ProductRecords`` over the notification service's memory store: the audit rows the
    public step reads. The step reads nothing else."""

    def __init__(self, store: NotificationStore) -> None:
        self._store = store

    def directory_count(self, level: str, *, as_of: datetime | None = None) -> int:
        raise AssertionError("the public step reads no directory")

    def listed(self, business_ids: Iterable[str], *, as_of: datetime | None = None) -> set[str]:
        raise AssertionError("the public step reads no directory")

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
            for entry in list(self._store.audit)
            if entry.action in actions and entry.occurred_at >= since
        ]

    def engine_rows(self, tenant_id: UUID) -> dict[str, int]:
        raise AssertionError("the public step reads no engine rows")


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


def in_directory(engine: EngineStore, registration_ids: Sequence[str]) -> bool:
    missing = [r for r in registration_ids if BusinessId(UUID(r)) not in engine.directory]
    if missing:
        raise NotYetError(f"{len(missing)} registrations are not in the directory yet")
    return True


def gstr9_obligations(product: Product, registration: str, version_id: str) -> int:
    listed = ok(
        product.internal.get(
            OBLIGATIONS,
            params={"business_id": registration, "rule_version_id": version_id},
            headers=as_tenant(CA_FIRM_TENANT.tenant_id),
        )
    )
    if not listed:
        raise NotYetError("no GSTR-9 obligation of the firm's client yet")
    return len(listed)


def monthly_due_next(now: datetime) -> str:
    """The structured layer's answer for a monthly GSTR-3B filer decided on ``now``'s day in
    India: the return due next that day, from the seed calendar, which is the previous month's
    while it is still due (September's, due 20 October, on 6 October)."""
    (monthly,) = [r for r in load_calendar(load_ontology()).rules if r.rule_key == "gstr3b_monthly"]
    assert monthly.recurrence is not None
    today = now.astimezone(IST).date()
    period = next(
        p for p in monthly.recurrence.periods_due(today, 1) if p.end > monthly.effective_from
    )
    due = monthly.recurrence.due_date(period)
    title = monthly.obligation_template.title
    return f"Your next GSTR-3B is due on {due.day} {due:%B %Y}: {title} ({period.label})."


def test_the_public_api_lists_answers_and_bulk_notifies(tmp_path: Path) -> None:
    sink = tmp_path / "sink.jsonl"
    with running_app(service_overrides=services(sink)) as app:
        load_seed_drafts(app)
        pump = Pump(app, tmp_path)
        engine = pump.engine
        assert isinstance(engine, EngineStore)
        with pump.running(), product_of(app, sink) as product:
            report = seed(product, rules=DEFAULT_RULES, state_path=tmp_path / "last.json")
            seeded = {b.key: b.registration_id for t in report.tenants for b in t.businesses}
            check.poll(
                lambda: in_directory(engine, list(seeded.values())), timeout=30.0, interval=0.1
            )
            (gstr9,) = publish(product, [GSTR9]).rules
            check.poll(
                lambda: gstr9_obligations(
                    product, seeded["client_karnataka"], gstr9.rule_version_id
                ),
                timeout=30.0,
                interval=0.1,
            )
            context = CheckContext(
                product,
                timeout=30.0,
                interval=0.1,
                records=NotificationRecords(pump.notifications),
            )
            first = check.public(context)
            (again,) = check.run_checks(context, check.select(["public"]))
            recipients = ok(
                product.internal.get(
                    "/v1/notification/recipients",
                    params={"business_id": seeded["client_karnataka"]},
                    headers=as_tenant(CA_FIRM_TENANT.tenant_id),
                )
            )["items"]

    assert first[0].startswith(f"GET /v1/businesses/{seeded['demo_traders']}/obligations")
    assert "pages of one alike" in first[0]
    assert first[1].endswith("404 obligation-business-not-found")
    assert first[2].startswith(
        f"POST /v1/qa 'When is my GSTR-3B due?': {monthly_due_next(datetime.now(UTC))} "
    ), "decided today, the registration's next return is the one due next today"
    assert "(structured layer," in first[2]
    assert first[3].endswith("404 qa-business-not-found")
    bulk_line = first[4]
    assert bulk_line.startswith(f"POST /v1/notification/bulk of {GSTR9} ({gstr9.rule_version_id})")
    assert "1 clients told, 1 card to the client contact, none to the firm's admin" in bulk_line
    assert "a new key found 1 duplicate" in bulk_line
    assert first[5] == f"audit.event: 2 {BULK_ACTION} rows of the firm, by system:notification"
    assert first[6].startswith("the contact's card: email sent through the sink (sink:")
    assert first[7].endswith("holds the message")
    assert first[8] == "POST /v1/notification/send on the public listener: 404 route-not-found"
    assert again.ok, again.error
    assert again.details[4] == bulk_line, "a second run queues one card to a contact of its own"

    contacts = [r for r in recipients if r["addresses"][0]["address"].startswith(CONTACT_PREFIX)]
    assert contacts == [], "each run removes its contact"
    cards = [
        n
        for n in pump.notifications.notifications_of(TenantId(CA_FIRM_TENANT.tenant_id))
        if n.occasion is OccasionKind.CHANGE_CARD
        and n.business_id == BusinessId(UUID(seeded["client_karnataka"]))
    ]
    by_contact = [n for n in cards if n.address.startswith(CONTACT_PREFIX)]
    assert len(by_contact) == 2, "one card per run, each to that run's contact"
    firm_admin = [n for n in cards if not n.address.startswith(CONTACT_PREFIX)]
    gstr9_cards = [
        n for n in firm_admin if n.params.get("rule_version_id") == gstr9.rule_version_id
    ]
    assert len(gstr9_cards) == 1, "the firm's admin has the change's own card, and no bulk one"
    bulk_rows = [entry for entry in pump.notifications.audit if entry.action == BULK_ACTION]
    assert len(bulk_rows) == 4, "two requests ran in each run; the replays ran nothing"
    assert {entry.tenant_id for entry in bulk_rows} == {TenantId(CA_FIRM_TENANT.tenant_id)}
    assert Outcome.DEAD not in pump.outcomes
    assert pump.fanouts.failures == {}
