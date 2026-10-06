"""A notification the detector set aside comes back through the pipeline's operations, and its
rule candidate ends as a draft golden case, through the one deployable.

The whole app runs as ``cw-mvp serve`` runs it, on memory stores, with the pipeline's knowledge
and extraction on and its ingest starter handed in (a recording one, no Temporal), the rulebook
with its tokens, and the llm-gateway answering completions from a scripted model: for the
recorded 01/2026-Central Tax, the draft label of its golden case (evals/golden/extraction,
``label_status: draft``: nobody has reviewed it, so it shows the plumbing, not the law).

1. An admin uploads the recorded notification under a portal user guide's title (synthetic: the
   wrong row of a listing copied). Its ingest runs as the worker runs it, the parse and then the
   classify step, whose detector reads the title and sets the document aside as irrelevant.
2. On the operations API the admin finds it among every source's documents, set aside, and
   retries it from the classify stage as a notification, with a reason and an Idempotency-Key:
   the person's type beats the detector (classifier ``retry``), the same request again replays
   its attempt, and the ingest ``pipeline-retry-<document>-1`` starts. It runs as the worker runs
   it: the parse, the classify step (the person's type stands), the registration in the
   rulebook and the rule extraction, which stores the candidate with its rule.candidate.created.
   The knowledge child (mentions, relations) and the embedding are left out: nothing here needs
   them.
3. The broker is away: the relay's sends fail until every pending row is dead. The admin lists
   the dead rows of rule.candidate.created and requeues the candidate's, audited; once the
   broker is back the relay sends it, and only it.
4. The rulebook worker's consumer (group ``rulebook.rule-candidates``) fails on it (its database
   away, synthetic) and dead-letters it to ``rule.candidate.created.rulebook.rule-candidates.dlq``.
   ``make replay``'s command lists that topic, refuses an event id the topic does not hold, and
   sends the message back to rule.candidate.created without its dead-letter headers; the
   consumer takes it in (one candidate task) and skips it the second time.
5. An analyst claims the task and drafts a new rule from the candidate (a one-off duty needs its
   ``due_in_days``: a synthetic edit), and two reviewers approve it. ``rulebook-golden-export``
   writes the decided candidate as a draft golden case (labelled by the reviewer who decided it,
   reviewed by nobody), which the pipeline's case loader reads and its validators accept.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx2
import pytest
import yaml
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from cw_mvp.testing import MEMORY_SERVICES, running_app
from domain_kernel.documents import DocumentType
from domain_kernel.ids import DocumentId
from ontology import load as load_ontology
from pipeline.application.activities import ParseDocument, ParseRequest
from pipeline.application.classify import Classified, ClassifyDocument, ClassifyRequest
from pipeline.application.extraction import (
    RULE_PROMPT,
    ExtractionRequest,
    ExtractRules,
    RuleExtractionStage,
    StoreExtraction,
)
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.application.knowledge_activities import RegisterDocument, RegisterRequest
from pipeline.domain.classification import RETRY
from pipeline.domain.retry import retry_workflow_id
from pipeline.infrastructure.adapters import StoreCatalog
from pipeline.infrastructure.gateway import GatewayProvider
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.prompts import load_prompt
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.infrastructure.temporal import ingest_payload
from pipeline.label import check_case, load_case
from pipeline.testing import MemoryIngests, ScriptedProvider, recorded_client
from pipeline.workflows import IngestRequest
from py_common.events import EventMessage
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
)
from py_common.outbox import replay as dead_letters
from py_common.outbox.relay import OutboxRelay, RelayConfig
from py_common.outbox.store import UnitOfWork
from py_common.outbox.testing import FakeConsumer, FakeProducer, Sent
from rulebook import golden
from rulebook import worker as rulebook_worker
from rulebook.infrastructure.memory import MemoryKnowledgeStore

REPO: Final = Path(__file__).resolve().parents[4]
FIXTURES: Final = REPO / "services/pipeline/tests/fixtures"
CASE: Final = load_case(
    REPO / "evals/golden/extraction/cbic_notifications/cases/01-2026-central-tax.yaml"
)
PIPELINE: Final = "/v1/pipeline"
RULEBOOK: Final = "/v1/rulebook"
TASKS: Final = f"{RULEBOOK}/review/tasks"
WRITE_TOKEN: Final = "pipeline-ops-journey-write-token"
REVIEW_TOKEN: Final = "pipeline-ops-journey-review-token"
WRITE: Final = {"x-cw-write-token": WRITE_TOKEN}
REVIEW: Final = {"x-cw-review-token": REVIEW_TOKEN}
ADMIN, ANALYST, REVIEWER, OTHER_REVIEWER = (str(UUID(int=n)) for n in (111, 112, 113, 114))
GUIDE_TITLE: Final = "Example user guide for furnishing the return on the portal"
"""The title the upload is listed under: a portal user guide's, which the detector sets aside."""
TOPIC: Final = "rule.candidate.created"
DLQ: Final = f"{TOPIC}.{rulebook_worker.CANDIDATES_GROUP_ID}.dlq"
EXTENSION: Final = "gstr3b_extension_2026_03"
DEAD_LETTER_HEADERS: Final = {"origin_topic", "consumer_group", "attempts", "error"}


def ok(response: httpx2.Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


def recorded_notification() -> bytes:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-01-2026.pdf.json").read_text())
    return base64.b64decode(wrapper["data"])


def services() -> dict[str, dict[str, Any]]:
    return {
        **{name: dict(values) for name, values in MEMORY_SERVICES.items()},
        "pipeline": {
            **MEMORY_SERVICES["pipeline"],
            "pipeline_knowledge_enabled": True,
            "pipeline_extraction_enabled": True,
            "rulebook_write_token": WRITE_TOKEN,
        },
        "rulebook": {
            "rulebook_store": "memory",
            "rulebook_write_token": WRITE_TOKEN,
            "rulebook_review_token": REVIEW_TOKEN,
        },
    }


class Pipeline:
    """The pipeline's store, raw store and ingest starter, shared by the app and the steps the
    worker would run, and the steps themselves."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.ingests = MemoryIngests()

    def overrides(self) -> dict[str, Any]:
        return {"units": self.store, "raw_store": self.raw, "ingests": self.ingests}

    def chain(self) -> ParserChain:
        return ParserChain(StoreCatalog(self.store, recorded_client()))

    async def classify(self) -> tuple[IngestRequest, ParseRequest, Classified]:
        """The last ingest started, up to its classify step, as its workflow runs it."""
        request = IngestRequest.model_validate(ingest_payload(self.ingests.started[-1]))
        assert request.stored is not None
        parse = ParseRequest(
            document_id=request.stored.document_id,
            stored=request.stored,
            title=request.stored.title,
            published_at=request.stored.published_at,
        )
        await ParseDocument(self.chain(), self.raw, units=self.store).run(parse)
        classified = await ClassifyDocument(
            self.chain(), self.raw, self.store, extraction=True
        ).run(ClassifyRequest(parse=parse, fresh=request.reclassify))
        return request, parse, classified

    async def extract(
        self,
        internal: httpx2.Client,
        request: IngestRequest,
        parse: ParseRequest,
        classified: Classified,
    ) -> None:
        """The rest of the ingest a classified document goes on to: its registration in the
        rulebook, then its rule extraction, stored with its rule.candidate.created."""
        assert request.stored is not None
        assert request.knowledge, "the registration runs while knowledge is on"
        rulebook = HttpRulebook(token=WRITE_TOKEN, client=internal)
        doc_type = DocumentType(classified.doc_type)
        registered = await RegisterDocument(
            self.chain(), rulebook, enabled=True, raw_store=self.raw, units=self.store
        ).run(RegisterRequest(parse=parse, regulator=request.regulator, doc_type=doc_type))
        assert not registered.skipped
        extraction = ExtractRules(
            rulebook,
            RuleExtractionStage(
                LlmRuleExtractor(
                    GatewayProvider(client=internal), load_prompt(*RULE_PROMPT), load_ontology()
                )
            ),
            self.store,
            enabled=True,
        )
        answer = await extraction.run(
            ExtractionRequest(
                document_id=request.stored.document_id,
                source_id=request.source_id,
                source_key=request.stored.source_key,
                regulator=request.regulator,
                doc_type=doc_type,
                own_ref=request.stored.external_ref,
            )
        )
        assert (answer.outcome, answer.needs_review) == ("extracted", False)
        assert (await StoreExtraction(self.store).run(answer)).created

    async def relay(self, *, broker_away: bool) -> FakeProducer:
        """One pass of the outbox relay: with the broker away every send fails and, one attempt
        allowed, every pending row goes dead; with it back, the pending rows are sent."""
        broker = FakeProducer()
        if broker_away:
            for topic in {row.message.topic for row in self.store.outbox.rows.values()}:
                broker.fail_times[topic] = 1_000
        relay = OutboxRelay(
            store=self.store.outbox,
            producer=broker,
            config=RelayConfig(max_attempts=1),
            clock=lambda: datetime.now(UTC) + timedelta(minutes=1 if broker_away else 60),
        )
        await relay.run_once()
        return broker


def inbox(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    processed_event.create(engine)
    return engine


def inbound(sent: Sent, offset: int) -> InboundRecord:
    return InboundRecord(
        topic=sent.topic,
        partition=0,
        offset=offset,
        key=sent.key,
        value=sent.value,
        headers=tuple(sent.headers),
    )


async def test_a_set_aside_notification_comes_back_and_ends_as_a_draft_golden_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert CASE.expected is not None
    assert CASE.label_status == "draft"
    scripted = ScriptedProvider({str(CASE.document.document_id): json.dumps(CASE.expected)})
    pipeline = Pipeline()
    builds = {"pipeline": pipeline.overrides(), "llm-gateway": {"completion_provider": scripted}}
    with (
        running_app(service_overrides=services(), build_overrides=builds) as app,
        httpx2.Client(base_url=app.settings.mvp_internal_url, timeout=30.0) as internal,
    ):
        rulebook = app.services["rulebook"].state.wiring.unit_of_work
        assert isinstance(rulebook, MemoryKnowledgeStore)

        # 1. uploaded under a user guide's title, and set aside by the detector
        uploaded = ok(
            internal.post(
                f"{PIPELINE}/sources/cbic_notifications/uploads",
                headers=WRITE,
                files={"file": ("notification.pdf", recorded_notification(), "application/pdf")},
                data={
                    "actor_id": ADMIN,
                    "reason": "Example: the notification for the operations journey",
                    "title": GUIDE_TITLE,
                    "external_ref": "01/2026-Central Tax",
                },
            ),
            202,
        )
        document_id = uploaded["document"]["document_id"]
        assert document_id == str(CASE.document.document_id)
        _, _, set_aside = await pipeline.classify()
        assert (set_aside.route, set_aside.stops) == ("irrelevant", True)
        pipeline.ingests.finish()

        # 2. found among every source's documents, and retried as a notification
        (listed,) = ok(internal.get(f"{PIPELINE}/documents", params={"status": "irrelevant"}))[
            "items"
        ]
        assert (listed["document_id"], listed["classification"]["classifier"]) == (
            document_id,
            "detector@1",
        )
        retry = {
            "actor_id": ADMIN,
            "reason": "Example: a notification listed under the wrong title",
            "stage": "classify",
            "doc_type": "notification",
        }
        keyed = {**WRITE, "Idempotency-Key": "pipeline-ops-journey-retry-1"}
        accepted = ok(
            internal.post(f"{PIPELINE}/documents/{document_id}/retry", json=retry, headers=keyed),
            202,
        )
        workflow_id = retry_workflow_id(DocumentId(UUID(document_id)), 1)
        assert (accepted["workflow_id"], accepted["started"], accepted["reclassified"]) == (
            workflow_id,
            True,
            True,
        )
        classification = accepted["document"]["classification"]
        assert (classification["classifier"], classification["decided_by"]) == (RETRY, ADMIN)
        assert accepted["document"]["status"] == "classified"
        again = internal.post(
            f"{PIPELINE}/documents/{document_id}/retry", json=retry, headers=keyed
        )
        assert (again.status_code, again.headers.get("Idempotent-Replayed")) == (202, "true")
        assert again.json()["retry"]["attempt"] == 1, "the same attempt, not a second one"
        assert [start.workflow_id for start in pipeline.ingests.started][-1] == workflow_id
        request, parse, classified = await pipeline.classify()
        assert (classified.created, classified.extracts) == (False, True), (
            "the person's type stands: nothing is read again"
        )
        await pipeline.extract(internal, request, parse, classified)
        pipeline.ingests.finish()
        detail = ok(internal.get(f"{PIPELINE}/documents/{document_id}"))
        assert (detail["status"], detail["read_as"]) == ("extracted", "notification")
        assert detail["extraction"]["outcome"] == "extracted"
        assert [r["attempt"] for r in detail["retries"]] == [1]
        candidate_id = detail["extraction"]["candidate_id"]

        # 3. the broker away: every row dead; the candidate's requeued and relayed
        await pipeline.relay(broker_away=True)
        (dead,) = ok(internal.get(f"{PIPELINE}/outbox/dead", params={"topic": TOPIC}))["items"]
        assert (dead["status"], dead["summary"]["candidate_id"]) == ("dead", candidate_id)
        requeued = ok(
            internal.post(
                f"{PIPELINE}/outbox/{dead['event_id']}/requeue",
                json={"actor_id": ADMIN, "reason": "Example: the broker is back"},
                headers=WRITE,
            )
        )
        assert (requeued["requeued"], requeued["event"]["status"]) == (True, "pending")
        assert [e.action for e in pipeline.store.audit if e.subject_id == dead["event_id"]] == [
            "pipeline.outbox.requeue"
        ]
        broker = await pipeline.relay(broker_away=False)
        assert broker.topics() == [TOPIC], "only the requeued row; the others stay dead"
        assert ok(internal.get(f"{PIPELINE}/outbox/dead", params={"topic": TOPIC}))["items"] == []
        (relayed,) = broker.sent

        # 4. dead-lettered by the rulebook's consumer, replayed with make replay, taken in
        taken = rulebook_worker.candidate_handler(units_on=lambda connection: rulebook)
        failed: list[UUID] = []

        async def away_once(message: EventMessage, unit: UnitOfWork) -> None:
            if not failed:
                failed.append(message.event_id)
                raise ConnectionError("Example: the rulebook's database is away")
            await taken(message, unit)

        consumer_dlq = FakeProducer()
        consumer = IdempotentConsumer(
            group_id=rulebook_worker.CANDIDATES_GROUP_ID,
            store=SyncProcessedStore(
                inbox(tmp_path / "rulebook.sqlite"), group_id=rulebook_worker.CANDIDATES_GROUP_ID
            ),
            handler=away_once,
            producer=consumer_dlq,
            config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
        )
        assert await consumer.process(inbound(relayed, 0)) is Outcome.DEAD
        assert consumer_dlq.topics() == [DLQ]
        assert ok(internal.get(TASKS, params={"kind": "candidate"}, headers=REVIEW))["items"] == []
        # The broker holds the dead letter and the candidates' topic it goes back to.
        held = FakeConsumer.of(consumer_dlq).create(TOPIC)
        capsys.readouterr()
        listed_dead = await dead_letters.run(
            ["list", "--topic", DLQ], reader=held, producer=FakeProducer
        )
        assert listed_dead == 0
        listing = capsys.readouterr().out
        assert f"{DLQ}: 1 message(s)" in listing
        assert f"event {dead['event_id']} from {TOPIC} group rulebook.rule-candidates" in listing
        assert "ConnectionError: Example: the rulebook's database is away" in listing
        origin = FakeProducer()
        unknown = await dead_letters.run(
            ["send", "--topic", DLQ, "--event-id", str(uuid4())],
            reader=held,
            producer=lambda: origin,
        )
        assert unknown == 1
        assert "holds no message with event id" in capsys.readouterr().err
        sent = await dead_letters.run(
            ["send", "--topic", DLQ, "--event-id", dead["event_id"]],
            reader=held,
            producer=lambda: origin,
        )
        assert sent == 0
        assert f"to {TOPIC}" in capsys.readouterr().out
        (back,) = origin.sent
        assert back.topic == TOPIC
        assert (back.key, back.value) == (relayed.key, relayed.value)
        assert not DEAD_LETTER_HEADERS & {name for name, _ in back.headers}
        assert await consumer.process(inbound(back, 1)) is Outcome.PROCESSED
        assert await consumer.process(inbound(back, 2)) is Outcome.SKIPPED
        (queued,) = ok(internal.get(TASKS, params={"kind": "candidate"}, headers=REVIEW))["items"]
        task_id = queued["task_id"]
        task = ok(internal.get(f"{TASKS}/{task_id}", headers=REVIEW))
        assert task["candidate"]["document_id"] == document_id

        # 5. drafted, approved by two reviewers, and exported as a draft golden case
        ok(internal.post(f"{TASKS}/{task_id}/claim", json={"actor_id": ANALYST}, headers=REVIEW))
        obligation = dict(CASE.expected["obligation"])
        obligation.pop("clause_ref")
        drafted = ok(
            internal.post(
                f"{TASKS}/{task_id}/draft",
                json={
                    "actor_id": ANALYST,
                    "rule_key": EXTENSION,
                    "new_rule": {"regulator": "cbic", "level": "registration"},
                    "edits": {"obligation_template": {**obligation, "due_in_days": 0}},
                    "note": "Synthetic edit: a one-off duty needs its due_in_days",
                },
                headers=REVIEW,
            )
        )
        version = drafted["rule_version"]
        assert (version["rule_key"], version["status"], version["closed"]) == (
            EXTENSION,
            "draft",
            False,
        )
        for reviewer in (REVIEWER, OTHER_REVIEWER):
            decided = ok(
                internal.post(
                    f"{TASKS}/{task_id}/decide",
                    json={"actor_id": reviewer, "decision": "approve"},
                    headers=REVIEW,
                )
            )
        assert (decided["candidate_status"], decided["version"]["status"]) == (
            "approved",
            "approved",
        )

    out = tmp_path / "golden-export"
    assert golden.run(["--since", "2000-01-01", "--out", str(out)], units=rulebook) == 0
    assert "1 draft case(s), 0 rejection(s) listed, 0 skipped" in capsys.readouterr().out
    (written,) = sorted((out / "cases").glob("*.yaml"))
    assert written.name == f"01-2026-central-tax-{UUID(candidate_id).hex[-8:]}.yaml"
    content = yaml.safe_load(written.read_text(encoding="utf-8"))
    assert (content["label_status"], content["labelled_by"], content["reviewed_by"]) == (
        "draft",
        OTHER_REVIEWER,
        "",
    )
    assert content["export"]["candidate_id"] == candidate_id
    assert content["export"]["edited"] == ["obligation_template.due_in_days"]
    exported = load_case(written)
    assert exported.label_status == "draft"
    assert exported.expected is not None
    assert exported.expected["obligation"]["due_in_days"] == 0, "the analyst's edit"
    assert exported.expected["applies_to"] == CASE.expected["applies_to"]
    assert exported.expected["citations"] == CASE.expected["citations"]
    assert check_case(exported) == [], "the validators accept the exported expected"
    summary = yaml.safe_load((out / "summary.yaml").read_text(encoding="utf-8"))
    assert (summary["label_status"], summary["rejections"]) == ("draft", [])
