"""A seed rule through the review workflow to obligations, on the one deployable's memory stores.

The whole app runs as ``cw-mvp serve`` runs it (``running_app``), with publishing on, the
rulebook's tokens, the pipeline's knowledge on and the seed calendar loaded as drafts. The
synthetic tenants come from ``cw-product seed`` with nothing published. Then, over the internal
listener, the way the workbench will drive it:

1. ``POST /v1/rulebook/review/tasks/seed`` opens one task per seed draft, and again none.
2. An admin uploads a synthetic statute (an HTML page of an example Act) to the upload-only
   source ``cgst_act``; its ingest runs as the worker runs it (parse, then register in the
   rulebook over HTTP), so the statute's clauses are stored.
3. An analyst claims the task of gstr1_monthly and cites a clause of that statute through
   ``PATCH .../draft``: the quote is verified against the stored clause.
4. A reviewer approves it, raising it to high impact; the task opens again and the same
   reviewer is refused a second approval. A second reviewer approves and the version is
   approved, never published by the decision.
5. A reviewer publishes it through the existing route.
6. A pump stands in for the worker: profile.updated to the engine (the directory), rule.published
   to the engine's fan-out, applicability.decided to obligation's consumer. The monthly filer of
   the business tenant gets its GSTR-1 obligations from the fan-out; the CA firm's clients file
   quarterly and get none.

Every name is synthetic, and nothing here touches a shared database.
"""

import asyncio
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.pool import NullPool

import ontology as ontology_package
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
from cw_demo.product.client import Product, ProductSettings
from cw_demo.product.seed import seed
from cw_demo.product.tenants import BUSINESS_TENANT, CA_FIRM_TENANT
from cw_mvp.app import CombinedApp
from cw_mvp.testing import LOCALHOST, MEMORY_SERVICES, running_app
from domain_kernel.events import DomainEvent
from domain_kernel.ids import BusinessId, RuleVersionId
from obligation import worker as obligation_worker
from obligation.application.decisions import ApplyDecision
from obligation.infrastructure.memory import MemoryStore as ObligationStore
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from pipeline.application.activities import ParseDocument, ParseRequest
from pipeline.application.knowledge_activities import RegisterDocument, RegisterRequest
from pipeline.domain.ports import IngestStart
from pipeline.infrastructure.adapters import StoreCatalog
from pipeline.infrastructure.memory import MemoryStore as PipelineStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.infrastructure.temporal import ingest_payload
from pipeline.testing import MemoryIngests, recorded_client
from pipeline.workflows import IngestRequest
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

WRITE_TOKEN: Final = "review-journey-write-token"
REVIEW_TOKEN: Final = "review-journey-review-token"
WRITE: Final = {"x-cw-write-token": WRITE_TOKEN}
REVIEW: Final = {"x-cw-review-token": REVIEW_TOKEN}
RULEBOOK: Final = "/v1/rulebook"
TASKS: Final = f"{RULEBOOK}/review/tasks"
PIPELINE: Final = "/v1/pipeline"
MONTHLY: Final = "gstr1_monthly"
ADMIN: Final = str(UUID("00000000-0000-4000-8000-0000000c0101"))
ANALYST: Final = str(UUID("00000000-0000-4000-8000-0000000c0102"))
REVIEWER: Final = str(UUID("00000000-0000-4000-8000-0000000c0103"))
SECOND_REVIEWER: Final = str(UUID("00000000-0000-4000-8000-0000000c0104"))
CLAUSE_TEXT: Final = (
    "1. Every example person shall furnish the example statement of outward supplies by the "
    "eleventh day of the month following the example month."
)
QUOTE: Final = "shall furnish the example statement of outward supplies by the eleventh day"
STATUTE_HTML: Final = f"""<!doctype html>
<html><head><title>Example Act (synthetic)</title></head>
<body>
<h1>Example Act (synthetic)</h1>
<p>{CLAUSE_TEXT}</p>
<p>2. An example officer may extend the example date by an example notice.</p>
</body></html>
""".encode()
SERVICES: Final = {
    **MEMORY_SERVICES,
    "profile": {"profile_store": "memory", "profile_gstin_lookup": "static"},
    "rulebook": {
        "rulebook_store": "memory",
        "rulebook_publish_enabled": True,
        "rulebook_write_token": WRITE_TOKEN,
        "rulebook_review_token": REVIEW_TOKEN,
    },
    "pipeline": {
        **MEMORY_SERVICES["pipeline"],
        "pipeline_knowledge_enabled": True,
        "rulebook_write_token": WRITE_TOKEN,
    },
}


class Pipeline:
    """The pipeline's stores and ingest starter, shared with the app, and the ingest steps the
    worker runs: parse the stored document, then register it in the rulebook."""

    def __init__(self) -> None:
        self.store = PipelineStore()
        self.raw = MemoryRawStore()
        self.ingests = MemoryIngests()

    def overrides(self) -> dict[str, dict[str, Any]]:
        return {"pipeline": {"units": self.store, "raw_store": self.raw, "ingests": self.ingests}}

    async def ingest(self, start: IngestStart, rulebook: HttpRulebook) -> str:
        request = IngestRequest.model_validate(ingest_payload(start))
        assert request.stored is not None
        chain = ParserChain(StoreCatalog(self.store, recorded_client()))
        parse = ParseRequest(
            document_id=request.stored.document_id,
            stored=request.stored,
            title=request.stored.title,
            published_at=request.stored.published_at,
            transcript_key=request.transcript_key,
        )
        parsed = await ParseDocument(chain, self.raw, units=self.store).run(parse)
        registered = await RegisterDocument(
            chain, rulebook, enabled=True, raw_store=self.raw, units=self.store
        ).run(RegisterRequest(parse=parse, regulator=request.regulator))
        assert not registered.skipped
        return parsed.parser_version


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
        self.profiles = app.services["profile"].state.wiring.unit_of_work
        self.rulebook = app.services["rulebook"].state.wiring.unit_of_work
        self.engine = app.services["applicability-engine"].state.wiring.unit_of_work
        self.obligations = app.services["obligation"].state.wiring.unit_of_work
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
                ontology=ontology_package.load(),
            )
        )
        self.producer = FakeProducer()
        config = ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0)
        engine_store = self.engine
        self.consumers: tuple[tuple[str, IdempotentConsumer, frozenset[str]], ...] = (
            (
                "profile",
                IdempotentConsumer(
                    group_id=engine_worker.GROUP_ID,
                    store=read_first_store(
                        inbox(tmp_path / "profiles.sqlite"), engine_worker.GROUP_ID
                    ),
                    handler=engine_worker.profile_handler(
                        engine_worker.recompute_of(settings, readers),
                        units_on=lambda connection: engine_store,
                    ),
                    producer=self.producer,
                    config=config,
                ),
                frozenset({"profile.updated"}),
            ),
            (
                "rulebook",
                IdempotentConsumer(
                    group_id=engine_worker.RULES_GROUP_ID,
                    store=read_first_store(
                        inbox(tmp_path / "rules.sqlite"), engine_worker.RULES_GROUP_ID
                    ),
                    handler=engine_worker.rules_handler(
                        RuleEvents(readers.rulebook, self.fanouts, enabled=True),
                        units_on=lambda connection: engine_store.fanouts,
                    ),
                    producer=self.producer,
                    config=config,
                ),
                frozenset({"rule.published"}),
            ),
            (
                "engine",
                IdempotentConsumer(
                    group_id=obligation_worker.GROUP_ID,
                    store=read_first_store(
                        inbox(tmp_path / "obligation.sqlite"), obligation_worker.GROUP_ID
                    ),
                    handler=obligation_worker.decision_handler(
                        ApplyDecision(HttpRuleVersionReader(url)), units_on=self.obligation_units
                    ),
                    producer=self.producer,
                    config=config,
                ),
                frozenset({"applicability.decided"}),
            ),
        )
        self.handed = {"profile": 0, "rulebook": 0, "engine": 0}
        self.outcomes: list[Outcome] = []

    def obligation_units(self, connection: Connection) -> Any:
        return self.obligations

    def events(self, source: str) -> list[DomainEvent]:
        assert isinstance(self.rulebook, MemoryKnowledgeStore)
        assert isinstance(self.engine, EngineStore)
        if source == "profile":
            return list(self.profiles.events)
        if source == "rulebook":
            return list(self.rulebook.events())
        return list(self.engine.events)

    def drain(self) -> None:
        for source, consumer, topics in self.consumers:
            new = self.events(source)[self.handed[source] :]
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


def ok(response: httpx2.Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


def problem(response: httpx2.Response) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def waiting_task(internal: httpx2.Client, rule_key: str) -> dict[str, Any]:
    items = ok(internal.get(TASKS, params={"limit": 200}))["items"]
    (task,) = [i for i in items if i["rule_key"] == rule_key and i["status"] != "decided"]
    return dict(task)


def decide(internal: httpx2.Client, task_id: str, actor: str, **body: Any) -> httpx2.Response:
    return internal.post(
        f"{TASKS}/{task_id}/decide",
        json={"actor_id": actor, "decision": "approve", **body},
        headers=REVIEW,
    )


def upload_statute(internal: httpx2.Client) -> dict[str, Any]:
    uploaded = ok(
        internal.post(
            f"{PIPELINE}/sources/cgst_act/uploads",
            headers=WRITE,
            files={"file": ("example-act.html", STATUTE_HTML, "text/html")},
            data={
                "actor_id": ADMIN,
                "reason": "The Act the seed rule cites, for the review journey",
                "title": "Example Act (synthetic)",
                "external_ref": "Example Act",
            },
        ),
        202,
    )
    document: dict[str, Any] = uploaded["document"]
    return document


def test_a_seed_rule_is_reviewed_by_two_people_published_and_fanned_out(
    tmp_path: Path,
) -> None:
    pipeline = Pipeline()
    with running_app(service_overrides=SERVICES, build_overrides=pipeline.overrides()) as app:
        rulebook_store = app.services["rulebook"].state.wiring.unit_of_work
        assert isinstance(rulebook_store, MemoryKnowledgeStore)
        rulebook_store.apply_seed(load_calendar(ontology_package.load()))
        pump = Pump(app, tmp_path)
        with pump.running(), product_of(app) as product:
            internal = product.internal
            report = seed(product, rules=(), state_path=tmp_path / "last.json")
            assert report.decisions == [], "nothing is published before the review"
            registrations = [b.registration_id for t in report.tenants for b in t.businesses]
            check.poll(lambda: _listed(pump.engine, registrations), timeout=30.0, interval=0.1)

            # 1. the seed tasks, once
            assert ok(internal.post(f"{TASKS}/seed", headers=REVIEW))["opened"] == 13
            assert ok(internal.post(f"{TASKS}/seed", headers=REVIEW))["opened"] == 0

            # 2. the statute the rule cites, uploaded and registered
            document = upload_statute(internal)
            parser = asyncio.run(
                pipeline.ingest(
                    pipeline.ingests.started[-1], HttpRulebook(token=WRITE_TOKEN, client=internal)
                )
            )
            assert parser.startswith("html")
            statute = ok(internal.get(f"{RULEBOOK}/documents/{document['document_id']}"))
            assert statute["doc_type"] == "statute"
            (clause,) = [c for c in statute["clauses"] if c["text"] == CLAUSE_TEXT]

            # 3. an analyst claims the task and cites the statute
            task = waiting_task(internal, MONTHLY)
            task_id = task["task_id"]
            claimed = ok(
                internal.post(
                    f"{TASKS}/{task_id}/claim", json={"actor_id": ANALYST}, headers=REVIEW
                )
            )
            assert (claimed["status"], claimed["claimed_by"]) == ("claimed", ANALYST)
            edited = ok(
                internal.patch(
                    f"{TASKS}/{task_id}/draft",
                    json={
                        "actor_id": ANALYST,
                        "note": "cited the example Act",
                        "citations": [{"clause_id": clause["clause_id"], "quote": QUOTE}],
                    },
                    headers=REVIEW,
                )
            )
            (citation,) = edited["citations"]
            assert (citation["verified"], citation["document_id"]) == (
                True,
                document["document_id"],
            )
            assert [entry["action"] for entry in edited["decisions"]] == ["edited"]

            # 4. two different reviewers approve; the same one twice is refused
            first = ok(decide(internal, task_id, REVIEWER, high_impact=True, note="checked"))
            assert (first["task"]["status"], first["version"]["status"]) == ("open", "in_review")
            twice = decide(internal, task_id, REVIEWER)
            assert (twice.status_code, problem(twice)) == (409, "rulebook-duplicate-approver")
            second = ok(decide(internal, task_id, SECOND_REVIEWER, note="checked again"))
            assert second["task"]["status"] == "decided"
            version = second["version"]
            assert (version["status"], version["seed_status"]) == ("approved", "reviewed")
            assert sorted(version["approved_by"]) == sorted([REVIEWER, SECOND_REVIEWER])
            assert rulebook_store.events() == [], "approving publishes nothing"

            # 5. published through the existing route
            version_id = version["rule_version_id"]
            published = ok(
                internal.post(
                    f"{RULEBOOK}/rule-versions/{version_id}/publish",
                    json={"actor_id": REVIEWER, "note": "the review journey"},
                    headers=REVIEW,
                )
            )
            assert published["status"] == "published"
            assert sorted(published["approved_by"]) == sorted([REVIEWER, SECOND_REVIEWER])

            # 6. the fan-out decides every registration; the monthly filer gets obligations
            run = check.poll(
                lambda: _completed(pump.engine, version_id), timeout=30.0, interval=0.1
            )
            obligations = check.poll(
                lambda: _obligations_of(pump.obligations, version_id),
                timeout=30.0,
                interval=0.1,
            )

        assert run.counters.evaluated == len(registrations)
        engine = pump.engine
        assert isinstance(engine, EngineStore)
        decided = {
            str(d.business_id): d.result.value
            for d in engine.decisions.values()
            if str(d.rule_version_id) == version_id and d.trigger is Trigger.RULE_PUBLISHED
        }
        business = report.tenants[0].businesses[0]
        assert decided[business.registration_id] == "applies"
        clients = [b.registration_id for b in report.tenants[1].businesses]
        assert all(decided[client] != "applies" for client in clients), "they file quarterly"
        assert {o.tenant_id.value for o in obligations} == {BUSINESS_TENANT.tenant_id}
        assert CA_FIRM_TENANT.tenant_id not in {o.tenant_id.value for o in obligations}
        read = ok_read(app, task_id)
        assert [entry["action"] for entry in read["decisions"]] == [
            "edited",
            "submitted",
            "approved",
            "approved",
            "published",
        ]
        assert Outcome.DEAD not in pump.outcomes
        assert pump.producer.sent == []
        assert pump.fanouts.failures == {}


def ok_read(app: CombinedApp, task_id: str) -> dict[str, Any]:
    """The task read once more, after the pump stopped."""
    with httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as client:
        found: dict[str, Any] = ok(client.get(f"{TASKS}/{task_id}"))
        return found


def _listed(store: Any, registration_ids: Sequence[str]) -> bool:
    assert isinstance(store, EngineStore)
    missing = [r for r in registration_ids if BusinessId(UUID(r)) not in store.directory]
    if missing:
        raise check.NotYetError(f"{len(missing)} registrations are not in the directory yet")
    return True


def _completed(store: Any, version_id: str) -> Any:
    assert isinstance(store, EngineStore)
    runs = [
        run for run in store.fanout_runs.values() if str(run.rule_version_id.value) == version_id
    ]
    if not runs or runs[0].status is not FanOutStatus.COMPLETED:
        raise check.NotYetError(f"the fan-out of {version_id} has not completed")
    return runs[0]


def _obligations_of(store: Any, version_id: str) -> list[Any]:
    assert isinstance(store, ObligationStore)
    found = [
        o
        for o in store.obligations.values()
        if o.rule_version_id == RuleVersionId(UUID(version_id))
    ]
    if not found:
        raise check.NotYetError("no obligation of the reviewed rule yet")
    return found
