"""A business made and changed in the profile is decided, and gets and loses its obligations, by
itself: profile.updated through the engine's consumer, applicability.decided through obligation's,
on the one deployable's memory stores, with no call to the engine's evaluate route.

The whole app runs as ``cw-mvp serve`` runs it (``running_app``). A pump stands in for the
worker: it hands every profile.updated the profile service stored to the engine's handler (group
``applicability-engine.profiles``, reading the profile and the rulebook over the internal
listener with no transaction open, recompute on), and every applicability.decided the engine
stored to obligation's handler, each through an ``IdempotentConsumer`` on a SQLite inbox, as the
relays and Kafka do in the product. The recompute step of ``cw-product check`` then runs against
it unchanged. A second journey settles a review item through the engine's admin routes, which the
public listener does not serve outside token mode, and finds the resolution in the audit log.
"""

import asyncio
import hashlib
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx2
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

from applicability_engine import worker as engine_worker
from applicability_engine.application.review import RESOLVE_ACTION
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.infrastructure.memory import MemoryStore as EngineStore
from applicability_engine.settings import ApplicabilityEngineSettings
from cw_demo.product import check
from cw_demo.product.check import CheckContext
from cw_demo.product.client import Product, ProductSettings
from cw_demo.product.tenants import BUSINESS_TENANT
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, running_app
from domain_kernel.audit import AuditActor
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.events import DomainEvent
from domain_kernel.ids import RuleVersionId, SourceId, TenantId
from domain_kernel.predicates import specification_from_mapping, specification_to_mapping
from domain_kernel.status import ObligationStatus, RuleVersionStatus
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
from rulebook.application.documents import RegisterDocument
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.documents import StoredDocument
from rulebook.infrastructure.memory import MemoryKnowledgeStore

ENGINE: Final = "/v1/applicability-engine"
ROUTE_NOT_FOUND: Final = "urn:compliancewatch:problem:route-not-found"
SYNTHETIC_CLAUSE: Final = "Example clause stating a monthly return (synthetic)"
FREE_TEXT_RULE: Final = "example_judged_rule"
FREE_TEXT_SPEC: Final = {
    "all_of": [
        {"attribute": "registration_type", "operator": "eq", "value": "regular"},
        {"attribute": "business_category", "free_text": "Example premises shared with a hotel"},
    ]
}


def publish(
    app: CombinedApp, rule_key: str, specification: Mapping[str, object] | None = None
) -> RuleVersionId:
    """The seed rule ``rule_key`` published in the rulebook's memory store, or a synthetic rule
    with ``specification`` and the monthly rule's recurrence and template."""
    store = app.services["rulebook"].state.wiring.unit_of_work
    assert isinstance(store, MemoryKnowledgeStore)
    rules = {rule.rule_key: rule for rule in load_calendar(load_ontology()).rules}
    seed = rules.get(rule_key, rules["gstr3b_monthly"])
    assert seed.recurrence is not None
    _, version = store.add_rule(
        rule_key,
        title=seed.title if rule_key in rules else "Example judged rule (synthetic)",
        regulator=seed.regulator,
        level=seed.level,
        status=RuleVersionStatus.PUBLISHED,
        effective_from=seed.effective_from,
        specification=specification_to_mapping(
            seed.specification
            if specification is None
            else specification_from_mapping(specification)
        ),
        obligation_template=seed.obligation_template.to_mapping(),
        recurrence=seed.recurrence.to_mapping(),
        published_at=datetime.now(UTC),
    )
    cite(store, version)
    return version


def cite(store: MemoryKnowledgeStore, version: RuleVersionId) -> None:
    """A verified citation of a synthetic clause: the obligation service makes no obligation of
    a version that cites none."""
    digest = hashlib.sha256(b"recompute flow (synthetic)").hexdigest()
    document_id = document_id_for(digest)
    RegisterDocument(store).run(
        StoredDocument(
            document_id=document_id,
            source_id=SourceId(UUID(int=7)),
            sha256=digest,
            regulator="CBIC",
            doc_type=DocumentType.NOTIFICATION,
            url="https://example.invalid/recompute-flow.pdf",
            language="en",
            media_type="application/pdf",
            parser_version="pdf@1",
            fetched_at=datetime(2026, 9, 28, tzinfo=UTC),
        ),
        [Clause("en.p1", SYNTHETIC_CLAUSE)],
    )
    store.add_citation(version, clause_id_for(document_id, "en.p1"), SYNTHETIC_CLAUSE)


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
    """The worker's part, without Kafka: each new event of one store goes to the consumer of
    the next, as the outbox relays and the consumer groups pass them on."""

    def __init__(self, app: CombinedApp, tmp_path: Path) -> None:
        url = app.settings.mvp_internal_url
        wirings = {
            name: app.services[name].state.wiring
            for name in ("profile", "applicability-engine", "obligation")
        }
        self.profiles = wirings["profile"].unit_of_work
        self.engine = wirings["applicability-engine"].unit_of_work
        self.obligations = wirings["obligation"].unit_of_work
        assert isinstance(self.engine, EngineStore)
        assert isinstance(self.obligations, ObligationStore)
        self.producer = FakeProducer()
        config = ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0)
        settings = ApplicabilityEngineSettings(
            _env_file=None,
            service_name="applicability-engine-worker",
            profile_url=url,
            rulebook_url=url,
            applicability_recompute_enabled=True,
            applicability_engine_rules_cache_seconds=0,
        )
        self.engine_consumer = IdempotentConsumer(
            group_id=engine_worker.GROUP_ID,
            store=read_first_store(inbox(tmp_path / "engine.sqlite"), engine_worker.GROUP_ID),
            handler=engine_worker.profile_handler(
                engine_worker.recompute_of(settings), units_on=self.engine_units
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
        self.handed = {"profile": 0, "engine": 0}
        self.outcomes: list[Outcome] = []

    def engine_units(self, connection: Connection) -> Any:
        return self.engine

    def obligation_units(self, connection: Connection) -> Any:
        return self.obligations

    def drain(self) -> None:
        for source, events, consumer, topic in (
            ("profile", self.profiles.events, self.engine_consumer, "profile.updated"),
            ("engine", self.engine.events, self.obligation_consumer, "applicability.decided"),
        ):
            new = list(events[self.handed[source] :])
            for offset, event in enumerate(new, start=self.handed[source]):
                if type(event).topic == topic:
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
        self.drain()

    def decisions_of(self, business_id: str) -> list[Decision]:
        return [d for d in self.engine.decisions.values() if str(d.business_id) == business_id]


@contextmanager
def product_of(app: CombinedApp) -> Iterator[Product]:
    """The running app as ``cw-product`` reaches it."""
    settings = ProductSettings(_env_file=None, service_name="cw-product")
    public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
    with (
        httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
        httpx2.Client(base_url=public_url, timeout=30.0) as public,
        httpx2.Client(base_url=public_url, timeout=30.0) as worker,
    ):
        yield Product(settings, internal, public, worker)


def test_a_new_business_and_its_change_are_decided_by_profile_updated_alone(
    tmp_path: Path,
) -> None:
    with running_app() as app:
        monthly = publish(app, "gstr3b_monthly")
        quarterly = publish(app, "gstr3b_quarterly_group_a")
        pump = Pump(app, tmp_path)
        with pump.running(), product_of(app) as product:
            lines = check.recompute(CheckContext(product, timeout=30.0, interval=0.1))

        assert lines[0].startswith("probe: Recompute probe ")
        assert "gstr3b_monthly applies" in lines[1]
        assert "gstr3b_monthly not_applicable" in lines[2]
        assert f"obligations closed ({check.PROFILE_CHANGED})" in lines[2]
        assert lines[3].startswith("gstr3b_quarterly_group_a: ")
        assert lines[4].endswith("no review item for the probe")
        registration = lines[0].split("registration ")[1].split(",")[0]

        decisions = pump.decisions_of(registration)
        assert decisions, "the probe was decided"
        assert {d.trigger for d in decisions} == {Trigger.PROFILE_UPDATED}
        assert not [d for d in pump.engine.decisions.values() if d.trigger is Trigger.MANUAL], (
            "nothing called the evaluate route"
        )
        assert all((d.trigger_ref or "").startswith("profile.updated:") for d in decisions)
        obligations = [
            o for o in pump.obligations.obligations.values() if str(o.business_id) == registration
        ]
        closed = [o for o in obligations if o.rule_version_id == monthly]
        assert closed
        assert all(o.status is ObligationStatus.CLOSED_NOT_APPLICABLE for o in closed)
        assert [o for o in obligations if o.rule_version_id == quarterly]
        assert {str(entry.business_id) for entry in pump.engine.directory.values()} >= {
            registration
        }
        assert Outcome.DEAD not in pump.outcomes
        assert pump.producer.sent == []


def test_a_review_item_is_settled_through_the_admin_routes_and_makes_obligations(
    tmp_path: Path,
) -> None:
    tenant = {"x-tenant-id": str(BUSINESS_TENANT.tenant_id)}
    with running_app() as app:
        judged = publish(app, FREE_TEXT_RULE, FREE_TEXT_SPEC)
        pump = Pump(app, tmp_path)
        public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
        with (
            pump.running(),
            httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
            httpx2.Client(base_url=public_url, timeout=30.0) as public,
        ):
            created = public.post(
                "/v1/businesses",
                json={
                    "name": "Example Judged Traders (synthetic)",
                    "gstin": "29ZZZJD0001Z1Z5",
                    "answers": [{"key": "registration_type", "value": "regular"}],
                },
                headers={**tenant, "Idempotency-Key": str(uuid4())},
            )
            assert created.status_code == 201, created.text
            (registration,) = created.json()["business"]["registrations"]

            def opened() -> dict[str, Any]:
                page = check.answered(
                    internal.get(
                        f"{ENGINE}/review-items", params={"status": "open"}, headers=tenant
                    )
                )
                mine = [i for i in page["items"] if i["business_id"] == registration["id"]]
                if not mine:
                    raise check.NotYetError("no review item yet")
                item: dict[str, Any] = mine[0]
                return item

            item = check.poll(opened, timeout=30.0, interval=0.1)
            assert (item["reason"], item["rule_version_id"]) == ("free_text", str(judged))
            assert item["decision"]["trigger"] == "profile_updated"
            hidden = public.get(f"{ENGINE}/review-items", headers=tenant)
            assert (hidden.status_code, hidden.json()["type"]) == (404, ROUTE_NOT_FOUND)

            settled = internal.post(
                f"{ENGINE}/review-items/{item['item_id']}/resolve",
                json={
                    "resolution": "applies",
                    "note": "Example premises checked against the clause (synthetic)",
                    "resolved_by": str(uuid4()),
                },
                headers=tenant,
            )
            assert settled.status_code == 200, settled.text
            decision_id = settled.json()["resolution_decision_id"]

            def made() -> list[dict[str, Any]]:
                listed: list[dict[str, Any]] = check.answered(
                    internal.get(
                        "/v1/obligation/obligations",
                        params={"business_id": registration["id"], "rule_version_id": str(judged)},
                        headers=tenant,
                    )
                )
                if not listed:
                    raise check.NotYetError("no obligation yet")
                return listed

            obligations = check.poll(made, timeout=30.0, interval=0.1)
        assert {o["decision_id"] for o in obligations} == {decision_id}
        (review,) = [d for d in pump.engine.decisions.values() if str(d.decision_id) == decision_id]
        assert (review.trigger, review.result.value) == (Trigger.REVIEW, "applies")
        assert Outcome.DEAD not in pump.outcomes

        (audited,) = pump.engine.audit
        assert (audited.action, audited.tenant_id, audited.subject_id) == (
            RESOLVE_ACTION,
            TenantId(BUSINESS_TENANT.tenant_id),
            item["item_id"],
        )
        assert audited.actor == AuditActor.system("applicability-engine"), "no token, no person"
        assert audited.reason == "Example premises checked against the clause (synthetic)"
        assert audited.correlation_id == settled.headers["x-request-id"]
        assert audited.after is not None
        assert audited.after["resolution_decision_id"] == decision_id
