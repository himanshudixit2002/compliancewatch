"""An owner reports an error in an obligation, the regulatory team confirms it with a correcting
version, and the published correction reaches the obligation and the owner's inbox, on the one
deployable's memory stores: the error report leg (error_report.submitted to the rulebook's queue,
masked, and error_report.decided back to the tenant's report) and the correction notice leg
(rule.published and rule.superseded through the engine's fan-out and obligation's rules consumer,
then obligation.closed and obligation.created through notification's consumer and the sink).

The whole app runs as ``cw-mvp serve`` runs it (``running_app``), with publishing on, the
rulebook's tokens, the notification sink and no batching window, the seed calendar loaded as
drafts, and the flag ``obligation.error_reports`` on for the business tenant only (the CA firm
stands for a tenant the flag is off for). A pump stands in for the worker: every profile.updated
goes to the engine's profile consumer (recompute on), every rule event the rulebook stores to the
engine's rules consumer (fan-out on) and to obligation's rules consumer (the flag on), every
applicability.decided to obligation's decision consumer, every error_report.submitted to the
rulebook's intake (group ``rulebook.error-reports``), every error_report.decided to obligation's
consumer of decisions (group ``obligation.error-decisions``) and every obligation event to
notification's consumer, each through an ``IdempotentConsumer`` on a SQLite inbox; the dispatcher
sends what is due through the sink. ``cw-product seed`` publishes the GSTR-3B rules as the
synthetic analysts.

The rulebook's lifecycle treats ``corrects`` as a replacement (``rulebook.domain.publication``,
ADR-017): publishing the correcting version supersedes the reported one at once when it takes
effect today or earlier, obligation closes the obligations the correction takes over with reason
``rule_superseded`` (notification's ``obligation_closed`` template: a newer version replaced it),
and the correcting version's fan-out makes them again with the corrected date (the change card).
No event is added for the leg; obligation.rescheduled with reason ``corrected`` stays for a
deadline change that carries the corrected date.
"""

import asyncio
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

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
from cw_demo.product.analysts import DRAFTER, FIRST_REVIEWER, NOTE, REVIEWERS
from cw_demo.product.check import CheckContext
from cw_demo.product.client import GOLDEN, Product, ProductSettings, as_tenant, ok
from cw_demo.product.publish import DEFAULT_RULES, register_notifications, rule_versions
from cw_demo.product.seed import seed
from cw_demo.product.tenants import BUSINESS_TENANT, CA_FIRM_TENANT
from cw_evals.qa.world import load_world
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, ClauseId, RuleVersionId, TenantId
from domain_kernel.knowledge import RelationKind, RuleRelation
from domain_kernel.predicates import specification_to_mapping
from notification import worker as notification_worker
from notification.domain.occasions import OccasionKind
from obligation import worker as obligation_worker
from obligation.application.decisions import ApplyDecision
from obligation.application.error_reports import ApplyErrorDecision
from obligation.application.materialise import IST
from obligation.application.rule_events import RuleEvents
from obligation.domain.flags import ERROR_REPORTS
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
from rulebook import worker as rulebook_worker
from rulebook.application.seed_loader import load_calendar
from rulebook.infrastructure.memory import MemoryKnowledgeStore

WRITE_TOKEN: Final = "error-report-test-write-token"
REVIEW_TOKEN: Final = "error-report-test-review-token"
MONTHLY: Final = "gstr3b_monthly"
RULEBOOK: Final = "/v1/rulebook"
OBLIGATIONS: Final = "/v1/obligation/obligations"
ERROR_REPORTS_ROUTE: Final = "/v1/obligation/error-reports"
REVIEWS: Final = f"{RULEBOOK}/error-reports"
NOTIFICATIONS: Final = "/v1/notification/notifications"
RULE_TOPICS: Final = frozenset(obligation_worker.RULE_TOPICS)
CORRECTED_DUE_DAY: Final = 25
DESCRIPTION: Final = (
    "Example: the example monthly statement shows the 20th as its due date, but the example "
    "notice gives the 25th. Call us on +91 98765 43210 if you need the notice."
)
NOTES: Final = "Example: the notice moves the date to the 25th; version 2 corrects it."


class TenantFlags:
    """The flag obligation.error_reports on for one tenant and off for every other, as a
    per-tenant rollout (``CW_FLAG_OBLIGATION_ERROR_REPORTS__TENANTS``) has it."""

    def __init__(self, tenant_id: UUID) -> None:
        self._tenant = TenantId(tenant_id)

    def enabled(self, name: str, tenant_id: TenantId) -> bool:
        return name == ERROR_REPORTS and tenant_id == self._tenant


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
        engine_store, obligation_store, rulebook_store = (
            self.engine,
            self.obligations,
            self.rulebook,
        )

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
                frozenset({rulebook_worker.ERROR_REPORT_TOPIC}),
                consumer(
                    rulebook_worker.ERROR_REPORTS_GROUP_ID,
                    rulebook_worker.error_report_handler(
                        units_on=lambda connection: rulebook_store
                    ),
                    "error-reports.sqlite",
                    read_first=False,
                ),
            ),
            (
                "rulebook",
                frozenset({obligation_worker.ERROR_DECIDED_TOPIC}),
                consumer(
                    obligation_worker.ERROR_DECISIONS_GROUP_ID,
                    obligation_worker.error_decision_handler(
                        ApplyErrorDecision(), units_on=self.obligation_units
                    ),
                    "error-decisions.sqlite",
                    read_first=False,
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


def first_open(product: Product, tenant: UUID, business_id: str, version_id: str) -> dict[str, Any]:
    """The business's open obligation of the version due first; not materialised yet is not
    yet."""
    listed = obligations_of(product, tenant, business_id, version_id)
    open_ones = [o for o in listed if o["status"] == "open"]
    if not open_ones:
        raise check.NotYetError(f"no open obligation of {version_id} yet")
    return min(open_ones, key=lambda o: str(o["due_at"]))


def draft_correction(
    product: Product,
    rulebook: MemoryKnowledgeStore,
    reported: dict[str, Any],
    effective_from: date,
    evidence: ClauseId,
) -> RuleVersionId:
    """The next version of the monthly rule with the reported one's content and the corrected
    due day, drafted as an analyst's workbench would, with a ``corrects`` relation to the
    reported version from a recorded clause (the relation an analyst approves onto a draft)."""
    detail = ok(product.internal.get(f"{RULEBOOK}/rule-versions/{reported['rule_version_id']}"))
    recurrence = dict(detail["recurrence"])
    assert recurrence["due_day"] != CORRECTED_DUE_DAY, "the correction moves the day"
    correcting = rulebook.add_version(
        MONTHLY,
        title=f"{detail['title']} (corrected, synthetic)",
        summary=detail["summary"],
        specification=detail["specification"],
        obligation_template=detail["obligation_template"],
        recurrence={**recurrence, "due_day": CORRECTED_DUE_DAY},
        effective_from=effective_from,
    )
    with rulebook() as uow:
        uow.relations.add(
            RuleRelation(
                correcting,
                RelationKind.CORRECTS,
                RuleVersionId(UUID(reported["rule_version_id"])),
                evidence,
            ),
            relation_id=uuid4(),
            candidate_id=None,
        )
    return correcting


def publish_through_review(
    product: Product, version_id: RuleVersionId, citations: Sequence[dict[str, str]]
) -> dict[str, Any]:
    """Cited, submitted by the drafter as high impact, approved by both synthetic reviewers and
    published, as ``cw-product publish`` takes a seed draft through the lifecycle."""
    path = f"{RULEBOOK}/rule-versions/{version_id}"
    headers = product.review_headers()
    cited = {"citations": list(citations)}
    ok(product.internal.put(f"{path}/citations", json=cited, headers=headers))
    submit = {"actor_id": str(DRAFTER.user_id), "high_impact": True, "note": NOTE}
    ok(product.internal.post(f"{path}/submit", json=submit, headers=headers))
    for reviewer in REVIEWERS:
        body = {"actor_id": str(reviewer.user_id), "note": NOTE, "synthetic": True}
        ok(product.internal.post(f"{path}/approve", json=body, headers=headers))
    publish = {"actor_id": str(FIRST_REVIEWER.user_id), "note": NOTE}
    published: dict[str, Any] = ok(
        product.internal.post(f"{path}/publish", json=publish, headers=headers)
    )
    return published


def _in_directory(store: Any, registration_ids: Sequence[str]) -> bool:
    assert isinstance(store, EngineStore)
    missing = [r for r in registration_ids if BusinessId(UUID(r)) not in store.directory]
    if missing:
        raise check.NotYetError(f"{len(missing)} registrations are not in the directory yet")
    return True


def test_a_confirmed_report_is_fixed_by_a_correcting_version_the_owner_hears_about(
    tmp_path: Path,
) -> None:
    sink = tmp_path / "sink.jsonl"
    tenant = BUSINESS_TENANT.tenant_id
    flags = {"obligation": {"flags": TenantFlags(tenant)}}
    with running_app(service_overrides=services(sink), build_overrides=flags) as app:
        rulebook = load_seed_drafts(app)
        pump = Pump(app, tmp_path)
        with pump.running(), product_of(app, sink) as product:
            seeded = seed(product, rules=DEFAULT_RULES, state_path=tmp_path / "last.json")
            registrations = [
                business.registration_id
                for tenant_seed in seeded.tenants
                for business in tenant_seed.businesses
            ]
            context = CheckContext(product, timeout=30.0, interval=0.1)
            check.poll(
                lambda: _in_directory(pump.engine, registrations), timeout=30.0, interval=0.1
            )
            business_id = check.the_registration(context).registration_id
            (monthly,) = [v for v in rule_versions(product, MONTHLY) if v["status"] == "published"]
            reported_version = str(monthly["rule_version_id"])
            target = check.poll(
                lambda: first_open(product, tenant, business_id, reported_version),
                timeout=30.0,
                interval=0.1,
            )
            headers = as_tenant(tenant, **{"Idempotency-Key": "error-report-1"})
            report_route = f"{OBLIGATIONS}/{target['obligation_id']}/error-reports"
            body = {"category": "due_date", "description": DESCRIPTION}

            # The CA firm stands for a tenant the flag is off for: 404, and nothing is stored.
            firm = product.internal.post(
                report_route,
                json=body,
                headers=as_tenant(CA_FIRM_TENANT.tenant_id, **{"Idempotency-Key": "firm-report-1"}),
            )
            assert firm.status_code == 404, firm.text
            assert firm.json()["type"].endswith(":obligation-error-reports-disabled")
            assert pump.obligations.error_reports == {}
            assert (
                ok(product.internal.get(ERROR_REPORTS_ROUTE, headers=as_tenant(tenant)))["items"]
                == []
            )

            # 1. The owner reports a wrong due date.
            made = product.internal.post(report_route, json=body, headers=headers)
            assert made.status_code == 201, made.text
            report = made.json()
            report_id = str(report["report_id"])
            assert (report["status"], report["category"], report["description"]) == (
                "submitted",
                "due_date",
                DESCRIPTION,
            )
            assert report["rule_version_id"] == reported_version
            assert (
                made.status_code
                == product.internal.post(report_route, json=body, headers=headers).status_code
            ), "the same key answers the same report"
            assert len(pump.obligations.error_reports) == 1

            # 2. It reaches the rulebook's open reviews with the phone number masked.
            def queued() -> dict[str, Any]:
                page: dict[str, Any] = ok(
                    product.internal.get(REVIEWS, params={"rule_version_id": reported_version})
                )
                if not any(i["report_id"] == report_id for i in page["items"]):
                    raise check.NotYetError("the report is not in the rulebook's queue yet")
                return page

            page = check.poll(queued, timeout=30.0, interval=0.1)
            (review,) = [i for i in page["items"] if i["report_id"] == report_id]
            assert (review["tenant_id"], review["status"], review["category"]) == (
                str(tenant),
                "open",
                "due_date",
            )
            assert "[PHONE]" in review["description"]
            assert "98765" not in review["description"]
            assert review["description"].startswith("Example: the example monthly statement")
            (group,) = [g for g in page["groups"] if g["rule_version_id"] == reported_version]
            assert (group["open"], group["rule_key"], group["version"]) == (1, MONTHLY, 1)

            # 3. An analyst drafts the correcting version from the reported one, and the
            #    reviewer confirms the report with it.
            world = load_world(GOLDEN)
            _, clause_ids = register_notifications(product, world)
            citations = [
                {"clause_id": str(clause_ids[c.document, c.clause_ref]), "quote": c.quote}
                for c in world.rule(MONTHLY).citations
            ]
            today = datetime.now(UTC).astimezone(IST).date()
            effective_from = min(date.fromisoformat(str(target["period_start"])), today)
            correcting = draft_correction(
                product,
                rulebook,
                target,
                effective_from,
                ClauseId(UUID(citations[0]["clause_id"])),
            )
            decision = product.internal.post(
                f"{REVIEWS}/{report_id}/decision",
                json={
                    "actor_id": str(FIRST_REVIEWER.user_id),
                    "decision": "confirmed",
                    "notes": NOTES,
                    "correcting_rule_version_id": str(correcting),
                },
                headers=product.review_headers(),
            )
            assert decision.status_code == 200, decision.text
            assert (decision.json()["status"], decision.json()["decided_by"]) == (
                "confirmed",
                str(FIRST_REVIEWER.user_id),
            )

            # 4. The obligation service shows the decision on the tenant's report.
            def confirmed() -> dict[str, Any]:
                page: dict[str, Any] = ok(
                    product.internal.get(
                        ERROR_REPORTS_ROUTE,
                        params={"status": "confirmed"},
                        headers=as_tenant(tenant),
                    )
                )
                mine: list[dict[str, Any]] = [
                    i for i in page["items"] if i["report_id"] == report_id
                ]
                if not mine:
                    raise check.NotYetError("the decision has not reached the report yet")
                return mine[0]

            mine = check.poll(confirmed, timeout=30.0, interval=0.1)
            assert (mine["correcting_rule_version_id"], mine["notes"]) == (str(correcting), NOTES)
            assert mine["decided_at"] is not None
            assert mine["description"] == DESCRIPTION, "the tenant keeps its own text"

            # 5. The correction is published through the lifecycle and reaches the obligation:
            #    the reported obligation closes (rule_superseded), the correcting version makes
            #    it again with the corrected date, and the owner hears of both through the sink.
            published = publish_through_review(product, correcting, citations)
            assert published["status"] == "published"

            def corrected() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
                after = obligations_of(product, tenant, business_id, reported_version)
                (closed,) = [o for o in after if o["obligation_id"] == target["obligation_id"]]
                if closed["status"] == "open":
                    raise check.NotYetError("the reported obligation is still open")
                remade = [
                    o
                    for o in obligations_of(product, tenant, business_id, str(correcting))
                    if o["period_label"] == target["period_label"]
                ]
                if not remade:
                    raise check.NotYetError("the correcting version has not remade it yet")
                notices: list[dict[str, Any]] = ok(
                    product.internal.get(
                        NOTIFICATIONS,
                        params={"business_id": business_id, "limit": 200},
                        headers=as_tenant(tenant),
                    )
                )["items"]
                sent = {
                    (n["occasion"], n["obligation_id"]): n for n in notices if n["state"] == "sent"
                }
                heard = [
                    sent.get((OccasionKind.CLOSURE.value, target["obligation_id"])),
                    sent.get((OccasionKind.CHANGE_CARD.value, remade[0]["obligation_id"])),
                ]
                if any(notice is None for notice in heard):
                    raise check.NotYetError("the owner has not heard of both yet")
                return closed, remade[0], [n for n in heard if n is not None]

            closed, remade, sent = check.poll(corrected, timeout=60.0, interval=0.1)

    assert closed["closed_reason"] == "rule_superseded"
    assert datetime.fromisoformat(str(remade["due_at"])).astimezone(IST).day == CORRECTED_DUE_DAY
    assert remade["due_at"] != target["due_at"], "the corrected date"
    assert remade["status"] == "open"
    closure, card = sent
    assert (closure["obligation_id"], closure["template_key"]) == (
        target["obligation_id"],
        "obligation_closed",
    ), "a newer version replaced it"
    assert (card["obligation_id"], card["template_key"]) == (remade["obligation_id"], "change_card")

    # The audit trail: the report submitted and decided at obligation, without the text, and
    # the review decided at the rulebook.
    trail = [entry for entry in pump.obligations.audit if entry.subject_id == report_id]
    assert [e.action for e in trail] == ["error_report.submitted", "error_report.decided"]
    assert all("98765" not in str(e.after) for e in trail)
    assert trail[1].after is not None
    assert trail[1].after["correcting_rule_version_id"] == str(correcting)
    (decided,) = [
        e
        for e in rulebook.audit_entries("error_report_review.decided")
        if e.subject_id == report_id
    ]
    assert decided.actor.id == str(FIRST_REVIEWER.user_id)
    assert decided.reason == NOTES
    assert Outcome.DEAD not in pump.outcomes
    assert pump.producer.sent == []
