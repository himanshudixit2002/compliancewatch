"""A recorded notification becomes a rule candidate, an analyst's draft that extends a deadline, a
publication two people approved, and a rescheduled obligation, through the one deployable.

The whole app runs as ``cw-mvp serve`` runs it, on memory stores, with the pipeline's knowledge
and extraction on and its ingest starter handed in (a recording one, no Temporal), the rulebook
publishing with its tokens, and the llm-gateway answering completions from a scripted model: for
the recorded 01/2026-Central Tax, the draft label of its golden case (evals/golden/extraction,
``label_status: draft``: nobody has reviewed it, so it shows the plumbing, not the law). The
published monthly rule the notification extends is the seed calendar's ``gstr3b_monthly``, put in
the memory rulebook as published (still needs_review) and starting on 1 January 2026, a
synthetic start so that it governs the March period the notification moves.

1. An admin uploads the notification; its ingest runs as the worker runs it: the parse, the
   classify step and the registration in the rulebook; the knowledge child stages the
   extension of GSTR-3B from a scripted relation answer; the extraction stores the candidate
   with its rule.candidate.created.
2. The rulebook worker's handler (group ``rulebook.rule-candidates``) takes the event in through
   an ``IdempotentConsumer`` on a SQLite inbox, on the app's memory rulebook: one candidate task,
   high impact, under ``cbic``.
3. An analyst claims it and drafts a version over HTTP: a new rule for the extension, with the
   staged ``extends_deadline`` relation approved onto the draft against the monthly version. The
   draft the candidate proposes is refused until the analyst edits it (a one-off duty needs its
   ``due_in_days``); the edit (synthetic: the version applies to nobody and only moves the
   monthly return's due date) is recorded with what it changed.
4. Two different reviewers approve it, and a reviewer publishes it: rule.published and
   rule.deadline_changed for the March 2026 period, due 21 April 2026.
5. The rule events reach obligation's handler (group ``obligation.rules``) on a SQLite inbox and
   the app's obligation memory store, which moves a business's March obligation to the new day.

The ``corrected`` run rejects the first draft after step 3 (``wrong_extraction``): the draft is
closed, the rules listing leaves its rule out, and the staged extension is open again. A corrected
extraction (a later prompt version, synthetic) is drafted into the same rule as its version 2 with
that extension, and steps 4 and 5 go through it.
"""

import base64
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from cw_mvp.testing import MEMORY_SERVICES, running_app
from domain_kernel.documents import DocumentType
from domain_kernel.events import DomainEvent
from domain_kernel.ids import (
    BusinessId,
    CandidateId,
    DecisionId,
    EventId,
    RuleVersionId,
    TenantId,
)
from domain_kernel.predicates import specification_to_mapping
from domain_kernel.status import RuleVersionStatus
from obligation import worker as obligation_worker
from obligation.application.materialise import (
    IST,
    MaterialiseObligations,
    MaterialiseRequest,
)
from obligation.application.rule_events import RuleEvents
from obligation.domain.events import ObligationRescheduled
from obligation.infrastructure.memory import MemoryStore as ObligationStore
from obligation.infrastructure.rulebook_client import HttpRuleVersionReader
from ontology import load as load_ontology
from pipeline.application.activities import ParseDocument, ParseRequest
from pipeline.application.classify import ClassifyDocument, ClassifyRequest
from pipeline.application.extraction import (
    RULE_PROMPT,
    ExtractionRequest,
    ExtractRules,
    RuleExtractionStage,
    StoreExtraction,
)
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.application.knowledge_activities import (
    ExtractMentions,
    MentionsRequest,
    ProposeRelations,
    RegisterDocument,
    RegisterRequest,
    RelationsRequest,
    SubmitRelations,
)
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.domain.events import RuleCandidateCreated
from pipeline.infrastructure.adapters import StoreCatalog
from pipeline.infrastructure.gateway import GatewayProvider
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.prompts import load_prompt
from pipeline.infrastructure.raw_store import MemoryRawStore
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.infrastructure.temporal import ingest_payload
from pipeline.label import load_case
from pipeline.testing import MemoryIngests, ScriptedProvider, recorded_client
from pipeline.workflows import IngestRequest
from py_common.events import encode, to_message
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer
from rulebook import worker as rulebook_worker
from rulebook.application.seed_loader import load_calendar
from rulebook.domain.events import RuleDeadlineChanged
from rulebook.infrastructure.memory import MemoryKnowledgeStore

REPO: Final = Path(__file__).resolve().parents[4]
FIXTURES: Final = REPO / "services/pipeline/tests/fixtures"
CASE: Final = load_case(
    REPO / "evals/golden/extraction/cbic_notifications/cases/01-2026-central-tax.yaml"
)
PIPELINE: Final = "/v1/pipeline"
RULEBOOK: Final = "/v1/rulebook"
TASKS: Final = f"{RULEBOOK}/review/tasks"
WRITE_TOKEN: Final = "candidate-journey-write-token"
REVIEW_TOKEN: Final = "candidate-journey-review-token"
WRITE: Final = {"x-cw-write-token": WRITE_TOKEN}
REVIEW: Final = {"x-cw-review-token": REVIEW_TOKEN}
ADMIN, ANALYST, REVIEWER, OTHER_REVIEWER = (str(UUID(int=n)) for n in (101, 102, 103, 104))
MONTHLY: Final = "gstr3b_monthly"
EXTENSION: Final = "gstr3b_extension_2026_03"
"""The key the analyst gives the extension's own rule in this journey."""
SYNTHETIC_START: Final = date(2026, 1, 1)
RELATIONS: Final = json.dumps(
    {
        "relations": [
            {
                "relation": "extends_deadline",
                "target_mention": "M2",
                "rule_key": MONTHLY,
                "evidence_clause_ref": "en.p3",
                "evidence_quote": (
                    "hereby extends the due  date for furnishing the return in FORM GSTR-3B for "
                    "the month of March, 2026 till the twenty -first day of April, 2026"
                ),
                "period": "2026-03",
                "new_due_date": "2026-04-21",
                "confidence": 0.9,
            }
        ]
    }
)
"""What the scripted relation model says the notification does, as the knowledge journey
scripts it."""


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
            "rulebook_publish_enabled": True,
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

    @staticmethod
    def rulebook(internal: httpx2.Client) -> HttpRulebook:
        return HttpRulebook(token=WRITE_TOKEN, client=internal)

    async def ingest(self, internal: httpx2.Client) -> tuple[IngestRequest, str]:
        """What the ingest workflow does with the uploaded document: parse, classify, register,
        the knowledge child's mentions and relations, then the extraction with its event."""
        request = IngestRequest.model_validate(ingest_payload(self.ingests.started[-1]))
        assert request.stored is not None
        chain = ParserChain(StoreCatalog(self.store, recorded_client()))
        parse = ParseRequest(
            document_id=request.stored.document_id,
            stored=request.stored,
            title=request.stored.title,
            published_at=request.stored.published_at,
        )
        await ParseDocument(chain, self.raw, units=self.store).run(parse)
        classified = await ClassifyDocument(chain, self.raw, self.store, extraction=True).run(
            ClassifyRequest(parse=parse)
        )
        assert classified.extracts
        rulebook = self.rulebook(internal)
        registered = await RegisterDocument(
            chain, rulebook, enabled=True, raw_store=self.raw, units=self.store
        ).run(
            RegisterRequest(
                parse=parse,
                regulator=request.regulator,
                doc_type=DocumentType(classified.doc_type),
            )
        )
        assert not registered.skipped
        document_id = request.stored.document_id
        own_ref = request.stored.external_ref
        await ExtractMentions(rulebook, rulebook, enabled=True).run(
            MentionsRequest(document_id=document_id, own_ref=own_ref)
        )
        stage = RelationStage(
            LlmRelationExtractor(
                ScriptedProvider({}, default=RELATIONS),
                load_prompt("extraction.rule_relations", "1"),
            )
        )
        batch = await ProposeRelations(rulebook, stage, enabled=True).run(
            RelationsRequest(document_id=document_id, own_ref=own_ref, regulator=request.regulator)
        )
        assert (await SubmitRelations(rulebook, enabled=True).run(batch)).created == 1
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
                document_id=document_id,
                source_id=request.source_id,
                source_key=request.stored.source_key,
                regulator=request.regulator,
                doc_type=DocumentType(classified.doc_type),
                own_ref=own_ref,
            )
        )
        assert (answer.outcome, answer.needs_review) == ("extracted", False)
        assert (await StoreExtraction(self.store).run(answer)).created
        return request, str(document_id)


def inbox(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}", poolclass=NullPool)
    processed_event.create(engine)
    return engine


def record(event: DomainEvent, offset: int) -> InboundRecord:
    message = to_message(event)
    return InboundRecord(
        topic=message.topic, partition=0, offset=offset, key=b"k", value=encode(message)
    )


def publish_monthly(rulebook: MemoryKnowledgeStore) -> RuleVersionId:
    """The seed calendar's monthly GSTR-3B rule, published in memory (still needs_review), from a
    synthetic start that governs March 2026."""
    seeded = load_calendar(load_ontology()).get(MONTHLY)
    assert seeded.recurrence is not None
    _, version = rulebook.add_rule(
        MONTHLY,
        title=seeded.title,
        regulator=seeded.regulator,
        level=seeded.level,
        status=RuleVersionStatus.PUBLISHED,
        effective_from=SYNTHETIC_START,
        summary=seeded.summary,
        specification=specification_to_mapping(seeded.specification),
        obligation_template=seeded.obligation_template.to_mapping(),
        recurrence=seeded.recurrence.to_mapping(),
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return version


@pytest.mark.parametrize("corrected", [False, True], ids=["as_extracted", "corrected"])
async def test_a_recorded_notification_becomes_a_published_extension_that_moves_a_due_date(
    tmp_path: Path, corrected: bool
) -> None:
    """``corrected``: the first draft is rejected after drafting, which reopens the staged
    extension, and a corrected extraction's draft takes it to the publication instead."""
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
        obligations = app.services["obligation"].state.wiring.unit_of_work
        assert isinstance(rulebook, MemoryKnowledgeStore)
        assert isinstance(obligations, ObligationStore)
        monthly = publish_monthly(rulebook)
        reader = HttpRuleVersionReader(app.settings.mvp_internal_url)
        try:
            tenant, march = due_in_march(obligations, reader, monthly)

            # 1. the recorded notification, ingested, staged and extracted
            ok(
                internal.post(
                    f"{PIPELINE}/sources/cbic_notifications/uploads",
                    headers=WRITE,
                    files={
                        "file": ("notification.pdf", recorded_notification(), "application/pdf")
                    },
                    data={
                        "actor_id": ADMIN,
                        "reason": "The recorded notification for the candidate journey",
                        "title": "Seeks to extend the due date for furnishing FORM GSTR-3B",
                        "external_ref": "01/2026-Central Tax",
                    },
                ),
                202,
            )
            _, document_id = await pipeline.ingest(internal)
            (created,) = [
                event for event in pipeline.store.events if isinstance(event, RuleCandidateCreated)
            ]

            # 2. the rulebook worker's handler opens the candidate's task
            intake = IdempotentConsumer(
                group_id=rulebook_worker.CANDIDATES_GROUP_ID,
                store=SyncProcessedStore(
                    inbox(tmp_path / "rulebook.sqlite"),
                    group_id=rulebook_worker.CANDIDATES_GROUP_ID,
                ),
                handler=rulebook_worker.candidate_handler(units_on=lambda connection: rulebook),
                producer=FakeProducer(),
                config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
            )
            assert await intake.process(record(created, 0)) is Outcome.PROCESSED
            assert await intake.process(record(created, 1)) is Outcome.SKIPPED
            (queued,) = ok(internal.get(TASKS, params={"kind": "candidate"}, headers=REVIEW))[
                "items"
            ]
            assert (queued["regulator"], queued["priority"], queued["rule_key"]) == (
                "cbic",
                100,
                MONTHLY,
            )
            assert (queued["version"], queued["high_impact"]) == (None, True)
            task_id = queued["task_id"]
            detail = ok(internal.get(f"{TASKS}/{task_id}", headers=REVIEW))
            assert detail["candidate"]["document_id"] == document_id
            assert detail["candidate"]["candidate"] == CASE.expected
            assert detail["candidate"]["suggested_rule_known"]

            # 3. claimed and drafted, with the extension approved onto the draft
            ok(
                internal.post(
                    f"{TASKS}/{task_id}/claim", json={"actor_id": ANALYST}, headers=REVIEW
                )
            )
            (relation,) = ok(
                internal.get(
                    f"{RULEBOOK}/review/relations",
                    params={"document_id": document_id},
                    headers=REVIEW,
                )
            )
            assert (relation["relation"], relation["target_rule_key"]) == (
                "extends_deadline",
                MONTHLY,
            )
            draft: dict[str, Any] = {
                "actor_id": ANALYST,
                "rule_key": EXTENSION,
                "new_rule": {"regulator": "cbic", "level": "registration"},
                "relation_candidates": [
                    {
                        "candidate_id": relation["candidate_id"],
                        "target_rule_version_id": str(monthly),
                    }
                ],
            }
            refused = internal.post(f"{TASKS}/{task_id}/draft", json=draft, headers=REVIEW)
            assert refused.status_code == 422, refused.text
            assert refused.json()["detail"] == (
                "a duty that does not recur needs obligation_template.due_in_days"
            )
            obligation = dict(CASE.expected["obligation"])
            obligation.pop("clause_ref")
            draft["edits"] = {
                "specification": {"any_of": []},
                "obligation_template": {**obligation, "due_in_days": 0},
            }
            draft["note"] = "Synthetic edit: the version moves the monthly return's due date only"
            drafted = ok(internal.post(f"{TASKS}/{task_id}/draft", json=draft, headers=REVIEW))
            version = drafted["rule_version"]
            assert (version["rule_key"], version["status"], version["high_impact"]) == (
                EXTENSION,
                "draft",
                True,
            )
            assert [c["clause_ref"] for c in drafted["citations"]] == ["en.p3", "en.p4"]
            assert all(c["verified"] for c in drafted["citations"])
            (edited,) = drafted["decisions"]
            assert edited["action"] == "edited"
            assert "changed specification, obligation_template.due_in_days" in edited["note"]
            if corrected:
                task_id, version = await drafted_again(
                    internal, intake, created, task_id, draft, relation["candidate_id"]
                )

            # 4. two reviewers approve it, and it is published
            first = ok(
                internal.post(
                    f"{TASKS}/{task_id}/decide",
                    json={"actor_id": REVIEWER, "decision": "approve"},
                    headers=REVIEW,
                )
            )
            assert (first["task"]["status"], first["version"]["status"]) == ("open", "in_review")
            second = ok(
                internal.post(
                    f"{TASKS}/{task_id}/decide",
                    json={"actor_id": OTHER_REVIEWER, "decision": "approve"},
                    headers=REVIEW,
                )
            )
            assert (second["candidate_status"], second["version"]["status"]) == (
                "approved",
                "approved",
            )
            ok(
                internal.post(
                    f"{RULEBOOK}/rule-versions/{version['rule_version_id']}/publish",
                    json={"actor_id": REVIEWER, "note": "The extension of March's GSTR-3B"},
                    headers=REVIEW,
                )
            )
            rejected = [e for e in rulebook.events() if type(e).topic == "rule.rejected"]
            assert len(rejected) == (1 if corrected else 0)
            events = [e for e in rulebook.events() if type(e).topic != "rule.rejected"]
            assert [type(event).topic for event in events] == [
                "rule.published",
                "rule.deadline_changed",
            ]
            changed = events[1]
            assert isinstance(changed, RuleDeadlineChanged)
            assert (changed.rule_version_id, changed.period_label, changed.new_due_on) == (
                monthly,
                "2026-03",
                date(2026, 4, 21),
            )

            # 5. the obligation consumer moves the March obligation
            rules = IdempotentConsumer(
                group_id=obligation_worker.RULES_GROUP_ID,
                store=read_first_store(
                    inbox(tmp_path / "obligation.sqlite"), obligation_worker.RULES_GROUP_ID
                ),
                handler=obligation_worker.rules_handler(
                    RuleEvents(reader, enabled=True),
                    units_on=lambda connection: obligations,
                    refs_on=lambda connection: obligations.rule_version_refs(),
                    tenants_on=lambda connection: obligations,
                ),
                producer=FakeProducer(),
                config=ConsumerConfig(max_handler_attempts=1, retry_backoff_seconds=0),
            )
            for offset, event in enumerate(events):
                assert await rules.process(record(event, offset)) is Outcome.PROCESSED
        finally:
            reader.close()

    moved = obligations.obligations[march]
    assert moved.due_at is not None
    assert moved.due_at.astimezone(IST).date() == date(2026, 4, 21)
    (rescheduled,) = [
        event
        for event in obligations.events
        if isinstance(event, ObligationRescheduled) and event.tenant_id == tenant
    ]
    assert rescheduled.new_due_at.astimezone(IST).date() == date(2026, 4, 21)
    candidates = rulebook.rule_candidates()
    decided = [("rejected", MONTHLY)] if corrected else []
    assert [(c.status.value, c.suggested_rule_key) for c in candidates] == [
        *decided,
        ("approved", MONTHLY),
    ]


async def drafted_again(
    internal: httpx2.Client,
    intake: IdempotentConsumer,
    created: RuleCandidateCreated,
    task_id: str,
    draft: dict[str, Any],
    relation_id: str,
) -> tuple[str, dict[str, Any]]:
    """The first draft rejected after drafting, and a corrected extraction of the notification
    (a later prompt version, synthetic here) drafted again into the extension's rule with the
    reopened extension: the new task and its version."""
    rejected = ok(
        internal.post(
            f"{TASKS}/{task_id}/decide",
            json={
                "actor_id": REVIEWER,
                "decision": "reject",
                "reason": "wrong_extraction",
                "note": "Synthetic: the model read the notification wrongly",
            },
            headers=REVIEW,
        )
    )
    assert (rejected["candidate_status"], rejected["version"]["status"]) == ("rejected", "draft")
    (reopened,) = ok(
        internal.get(
            f"{RULEBOOK}/review/relations",
            params={"document_id": str(created.document_id)},
            headers=REVIEW,
        )
    )
    assert (reopened["candidate_id"], reopened["status"]) == (relation_id, "open")
    listed = {rule["rule_key"] for rule in ok(internal.get(f"{RULEBOOK}/rules"))}
    assert EXTENSION not in listed, "a rule only a closed draft holds is not listed"
    later = replace(
        created,
        event_id=EventId.new(),
        candidate_id=CandidateId.new(),
        prompt_version="extraction.rule_candidate@2",
    )
    assert await intake.process(record(later, 2)) is Outcome.PROCESSED
    (queued,) = ok(
        internal.get(TASKS, params={"kind": "candidate", "status": "open"}, headers=REVIEW)
    )["items"]
    new_task = str(queued["task_id"])
    ok(internal.post(f"{TASKS}/{new_task}/claim", json={"actor_id": ANALYST}, headers=REVIEW))
    again = {key: value for key, value in draft.items() if key != "new_rule"}
    drafted = ok(internal.post(f"{TASKS}/{new_task}/draft", json=again, headers=REVIEW))
    version: dict[str, Any] = drafted["rule_version"]
    assert (version["rule_key"], version["version"], version["status"]) == (EXTENSION, 2, "draft")
    return new_task, version


def due_in_march(
    obligations: ObligationStore, reader: HttpRuleVersionReader, monthly: RuleVersionId
) -> tuple[TenantId, Any]:
    """A business's March 2026 GSTR-3B obligation of the monthly version, made on 10 April as a
    decision would make it; its tenant and id."""
    read = reader.read(monthly, fresh=True)
    assert read is not None
    tenant = TenantId(uuid4())
    made = MaterialiseObligations(
        obligations, clock=lambda: datetime(2026, 4, 10, 4, 30, tzinfo=UTC)
    ).run(
        MaterialiseRequest(
            tenant, BusinessId(uuid4()), DecisionId(uuid4()), read.snapshot, date(2026, 4, 10)
        )
    )
    (march,) = [
        obligation_id
        for obligation_id in made.created
        if obligations.obligations[obligation_id].period is not None
        and obligations.obligations[obligation_id].period.label == "2026-03"  # type: ignore[union-attr]
    ]
    due = obligations.obligations[march].due_at
    assert due is not None
    assert due.astimezone(IST).date() == date(2026, 4, 20)
    return tenant, march
