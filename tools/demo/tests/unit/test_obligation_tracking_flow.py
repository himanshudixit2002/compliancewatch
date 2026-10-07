"""A member tracks an obligation end to end, on the one deployable's memory stores.

The whole app runs as ``cw-mvp serve`` runs it (``running_app``), with publishing on and the
rulebook's tokens. ``cw-product seed`` publishes the GSTR-3B rules as the synthetic analysts, and a
pump stands in for the worker: every profile.updated goes to the engine's profile consumer
(recompute on) and every applicability.decided to obligation's decision consumer, each through an
``IdempotentConsumer`` on a SQLite inbox. The tracking step of ``cw-product check`` then runs
against it unchanged: it makes a business, waits for its monthly obligations, starts, assigns and
completes the first one due (twice with one Idempotency-Key), reads it whole and comments on it.
The obligation service's store then holds one closure, the change rows and an audit entry of every
change, none of them carrying the comment's text; a second run passes with a business of its own.

In token mode a signed-in owner gives an obligation to a colleague: obligation asks identity, over
the internal listener and with its own token minted in the process, whether the colleague belongs
to the tenant, and refuses someone who does not.
"""

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx2
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

from applicability_engine import worker as engine_worker
from applicability_engine.infrastructure.memory import MemoryStore as EngineStore
from applicability_engine.settings import ApplicabilityEngineSettings
from cw_demo.product import check
from cw_demo.product.analysts import REVIEWERS
from cw_demo.product.check import CheckContext
from cw_demo.product.client import Product, ProductSettings
from cw_demo.product.publish import DEFAULT_RULES
from cw_demo.product.seed import seed
from cw_demo.product.tenants import BUSINESS_TENANT
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.audit import AuditActor
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, TenantId
from domain_kernel.predicates import specification_to_mapping
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation import worker as obligation_worker
from obligation.application.decisions import ApplyDecision
from obligation.application.materialise import MaterialiseRequest
from obligation.application.tracking import (
    ASSIGN_ACTION,
    COMMENT_ACTION,
    COMPLETE_ACTION,
    START_ACTION,
)
from obligation.domain.events import ObligationClosed
from obligation.domain.history import ChangeKind
from obligation.infrastructure.memory import MemoryStore as ObligationStore
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from obligation.testing import rule
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

WRITE_TOKEN: Final = "tracking-test-write-token"
REVIEW_TOKEN: Final = "tracking-test-review-token"
OBLIGATIONS: Final = "/v1/obligation/obligations"
PUBLIC_OBLIGATIONS: Final = "/v1/obligations"
OWNER_PHONE: Final = "+910000000011"
"""A synthetic number: +91 followed by zeros, which no Indian mobile number starts with."""
COLLEAGUE_PHONE: Final = "+910000000012"


def services() -> dict[str, dict[str, Any]]:
    return {
        **{name: dict(values) for name, values in MEMORY_SERVICES.items()},
        "profile": {"profile_store": "memory", "profile_gstin_lookup": "static"},
        "rulebook": {
            "rulebook_store": "memory",
            "rulebook_publish_enabled": True,
            "rulebook_write_token": WRITE_TOKEN,
            "rulebook_review_token": REVIEW_TOKEN,
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
    """The worker's part, without Kafka: profile.updated to the engine's consumer, and
    applicability.decided to obligation's, as the relays and the consumer groups pass them on."""

    def __init__(self, app: CombinedApp, tmp_path: Path) -> None:
        url = app.settings.mvp_internal_url
        self.profiles = app.services["profile"].state.wiring.unit_of_work
        self.engine = app.services["applicability-engine"].state.wiring.unit_of_work
        self.obligations = app.services["obligation"].state.wiring.unit_of_work
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
        self.reader = HttpRuleVersionReader(url)
        self.consumers = (
            (
                "profile",
                "profile.updated",
                IdempotentConsumer(
                    group_id=engine_worker.GROUP_ID,
                    store=read_first_store(
                        inbox(tmp_path / "engine.sqlite"), engine_worker.GROUP_ID
                    ),
                    handler=engine_worker.profile_handler(
                        engine_worker.recompute_of(settings), units_on=self.engine_units
                    ),
                    producer=self.producer,
                    config=config,
                ),
            ),
            (
                "engine",
                "applicability.decided",
                IdempotentConsumer(
                    group_id=obligation_worker.GROUP_ID,
                    store=read_first_store(
                        inbox(tmp_path / "obligation.sqlite"), obligation_worker.GROUP_ID
                    ),
                    handler=obligation_worker.decision_handler(
                        ApplyDecision(self.reader), units_on=self.obligation_units
                    ),
                    producer=self.producer,
                    config=config,
                ),
            ),
        )
        self.handed = {"profile": 0, "engine": 0}
        self.outcomes: list[Outcome] = []
        self.lock = threading.Lock()

    def engine_units(self, connection: Connection) -> Any:
        return self.engine

    def obligation_units(self, connection: Connection) -> Any:
        return self.obligations

    def drain(self) -> None:
        with self.lock:
            sources = {"profile": self.profiles.events, "engine": self.engine.events}
            for source, topic, consumer in self.consumers:
                new = list(sources[source][self.handed[source] :])
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
            self.reader.close()


def load_seed_drafts(app: CombinedApp) -> None:
    """The seed calendar as drafts, as ``make seed SERVICE=rulebook`` writes it."""
    store = app.services["rulebook"].state.wiring.unit_of_work
    assert isinstance(store, MemoryKnowledgeStore)
    for seeded in load_calendar(load_ontology()).rules:
        store.add_rule(
            seeded.rule_key,
            title=seeded.title,
            regulator=seeded.regulator,
            level=seeded.level,
            effective_from=seeded.effective_from,
            summary=seeded.summary,
            specification=specification_to_mapping(seeded.specification),
            obligation_template=seeded.obligation_template.to_mapping(),
            recurrence=None if seeded.recurrence is None else seeded.recurrence.to_mapping(),
        )


@contextmanager
def product_of(app: CombinedApp, tmp_path: Path) -> Iterator[Product]:
    settings = ProductSettings(
        _env_file=None,
        service_name="cw-product",
        mvp_host=LOCALHOST,
        mvp_public_port=app.settings.mvp_public_port,
        mvp_internal_port=app.settings.mvp_internal_port,
        mvp_internal_url=app.settings.mvp_internal_url,
        rulebook_write_token=SecretStr(WRITE_TOKEN),
        rulebook_review_token=SecretStr(REVIEW_TOKEN),
        notification_sink_path=str(tmp_path / "sink.jsonl"),
    )
    public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
    with (
        httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
        httpx2.Client(base_url=public_url, timeout=30.0) as public,
        httpx2.Client(base_url=public_url, timeout=30.0) as worker,
    ):
        yield Product(settings, internal, public, worker)


def tracked_obligation(store: ObligationStore, lines: list[str]) -> ObligationId:
    """The obligation the step tracked: the one done in the probe's registration."""
    registration = lines[0].split("registration ")[1].split(";")[0]
    (done,) = [
        o
        for o in store.obligations.values()
        if str(o.business_id) == registration and o.status is ObligationStatus.DONE
    ]
    return done.id


def test_a_member_tracks_an_obligation_from_start_to_comment(tmp_path: Path) -> None:
    with running_app(service_overrides=services()) as app:
        load_seed_drafts(app)
        pump = Pump(app, tmp_path)
        with pump.running(), product_of(app, tmp_path) as product:
            seed(product, rules=DEFAULT_RULES, state_path=tmp_path / "last.json")
            context = CheckContext(product, timeout=30.0, interval=0.1)
            first = check.tracking(context)
            again = check.run_checks(context, check.select(["tracking"]))

    assert first[0].startswith("probe: Tracking probe ")
    assert "gstr3b_monthly" in first[0]
    assert "the return due next on" in first[0], "the first one due is the next to file"
    assert "replayed (Idempotent-Replayed: true) with the same answer" in first[1]
    assert first[2] == "history: created, started, assigned, closed; one closure"
    reviewers = " and ".join(sorted(r.name for r in REVIEWERS))
    assert first[3].startswith(f"reviewed by {reviewers} on ")
    assert "seed status needs_review" in first[3]
    assert first[4] == f"comment by system:obligation: {check.TRACKING_COMMENT}"
    (rerun,) = again
    assert rerun.ok, rerun.error
    assert rerun.details[0] != first[0], "a second run makes a business of its own"

    store = pump.obligations
    assert isinstance(store, ObligationStore)
    tracked = tracked_obligation(store, first)
    obligation = store.obligations[tracked]
    assert obligation.assignee_id is not None
    assert obligation.assignee_id.value == BUSINESS_TENANT.owner_id
    assert obligation.closed_reason is ClosureReason.COMPLETED
    closures = [
        e for e in store.events if isinstance(e, ObligationClosed) and e.obligation_id == tracked
    ]
    assert len(closures) == 1, "one transition from two requests with one key"
    kinds = [c.kind for c in store.changes if c.obligation_id == tracked]
    assert kinds == [ChangeKind.CREATED, ChangeKind.STARTED, ChangeKind.ASSIGNED, ChangeKind.CLOSED]
    entries = [e for e in store.audit if e.subject_id == str(tracked)]
    assert entries[0].action == "obligation.created", "materialised by the system"
    entries = entries[1:]
    assert [e.action for e in entries] == [
        START_ACTION,
        ASSIGN_ACTION,
        COMPLETE_ACTION,
        COMMENT_ACTION,
    ]
    assert {e.actor for e in entries} == {AuditActor.system("obligation")}, "no token, no person"
    assert {e.tenant_id for e in entries} == {TenantId(BUSINESS_TENANT.tenant_id)}
    assert all(check.TRACKING_COMMENT not in str(e.after) for e in entries)
    (comment,) = [c for c in store.comments if c.obligation_id == tracked]
    assert dict(entries[-1].after or {}) == {"comment_id": str(comment.id)}
    assert Outcome.DEAD not in pump.outcomes
    assert pump.producer.sent == []


def test_in_token_mode_an_assignee_is_checked_with_identity(tmp_path: Path) -> None:
    with running_app(auth_mode="token") as app:
        public_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
        with httpx2.Client(base_url=public_url, timeout=30.0) as public:
            owner, tenant = sign_up(public)
            colleague = public.post(
                "/v1/identity/users",
                json={"phone": COLLEAGUE_PHONE, "roles": ["staff"]},
                headers=owner,
            )
            assert colleague.status_code == 201, colleague.text
            obligation = materialised(app, tenant)
            route = f"{PUBLIC_OBLIGATIONS}/{obligation}/assignee"

            def assign(assignee: str) -> httpx2.Response:
                return public.put(
                    route,
                    json={"assignee_id": assignee},
                    headers={**owner, "Idempotency-Key": str(uuid4())},
                )

            given = assign(colleague.json()["id"])
            stranger = assign(str(uuid4()))
            detail = public.get(f"{PUBLIC_OBLIGATIONS}/{obligation}", headers=owner)
            anonymous = public.get(f"{OBLIGATIONS}/{obligation}", headers={"x-tenant-id": tenant})

    assert given.status_code == 200, given.text
    assert given.json()["assignee_id"] == colleague.json()["id"]
    assert stranger.status_code == 422, stranger.text
    assert stranger.json()["type"].endswith(":obligation-assignee-unknown")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["rule_version"] is None, "the rulebook has no such version"
    (assigned,) = [c for c in body["history"] if c["kind"] == "assigned"]
    assert assigned["new_assignee_id"] == colleague.json()["id"]
    assert assigned["actor"] is not None
    assert anonymous.status_code == 401


def sign_up(public: httpx2.Client) -> tuple[dict[str, str], str]:
    """A business tenant made through identity's sign-up: its owner's bearer header and its
    id."""
    issued = public.post("/v1/identity/dev/provider-tokens", json={"phone": OWNER_PHONE})
    assert issued.status_code == 200, issued.text
    created = public.post(
        "/v1/identity/tenants",
        json={
            "kind": "business",
            "name": "Example Tracking Traders (synthetic)",
            "provider_token": issued.json()["provider_token"],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    return {"authorization": f"Bearer {body['session']['access_token']}"}, body["tenant"]["id"]


def materialised(app: CombinedApp, tenant: str) -> ObligationId:
    """An open obligation of the tenant, made as a decision would make it."""
    made = app.services["obligation"].state.wiring.materialise.run(
        MaterialiseRequest(
            TenantId(UUID(tenant)), BusinessId.new(), DecisionId.new(), rule(), date(2026, 9, 28)
        )
    )
    obligation: ObligationId = made.created[0]
    return obligation
