"""The rule extraction's activities: the model asked once more when its answer is not a
candidate, the answer written once with its rule.candidate.created, an extraction stored before
never asked about again, a used-up budget handed to the workflow, and the gateway's budget
problem read as such.

The document is a synthetic notification registered in a memory rulebook; the model is a list of
answers given in turn."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx2
import pytest
from temporalio.exceptions import ApplicationError

from domain_kernel.documents import Clause, DocumentType, ParsedDocument, clause_id_for
from domain_kernel.ids import DocumentId
from domain_kernel.llm import CompletionRequest
from ontology import load as load_ontology
from pipeline.application.extraction import (
    BUDGET_ERROR,
    RETRY_TEMPERATURE,
    RULE_PROMPT_REF,
    ExtractionAnswer,
    ExtractionRequest,
    ExtractRules,
    RuleExtractionStage,
    StoreExtraction,
)
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.domain.errors import ModelBudgetExhaustedError
from pipeline.domain.events import RuleCandidateCreated
from pipeline.domain.extraction import candidate_id_for
from pipeline.domain.knowledge import DocumentRecord
from pipeline.domain.prompt import PromptText
from pipeline.domain.raw_documents import DocumentStatus, RawDocumentRecord
from pipeline.domain.sources import Source
from pipeline.infrastructure.adapters import SOURCES, source_id_for
from pipeline.infrastructure.gateway import BUDGET_PROBLEM, GatewayError, GatewayProvider
from pipeline.infrastructure.memory import MemoryStore
from pipeline.testing import AnswersInTurn, MemoryRulebook

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
KEY = "cbic_notifications"
SHA = "ab" * 32
DOCUMENT = DocumentId(UUID(SHA[:32]))
PROMPT = PromptText("extraction.rule_candidate", "1", "regulatory-intelligence", "Extract.")
CLAUSES = (
    Clause("en.p1", "Notification No. 99/2026 - Central Tax"),
    Clause(
        "en.p2",
        "The Commissioner hereby extends the due date for furnishing the return in FORM GSTR-3B "
        "for an example month for registered persons filing monthly.",
    ),
)
ANSWER = {
    "title": "Example: the due date of an example return is extended",
    "summary": "An example notification extends the due date of FORM GSTR-3B for monthly filers.",
    "doc_kind": "notification",
    "change_kind": "extension",
    "effective_from": None,
    "effective_to": None,
    "references": [],
    "applies_to": [
        {
            "attribute": "filing_scheme",
            "operator": "eq",
            "value": "regular_monthly",
            "clause_ref": "en.p2",
        }
    ],
    "obligation": None,
    "recurrence": None,
    "amounts": [],
    "citations": [{"clause_ref": "en.p2", "quote": "extends the due date"}],
    "confidence": 0.9,
}


class World:
    def __init__(self, *answers: str | Exception, enabled: bool = True) -> None:
        self.store = MemoryStore()
        self.rulebook = MemoryRulebook()
        self.model = AnswersInTurn(*answers)
        stage = RuleExtractionStage(LlmRuleExtractor(self.model, PROMPT, load_ontology()))
        self.extract = ExtractRules(self.rulebook, stage, self.store, enabled=enabled)
        self.write = StoreExtraction(self.store, clock=lambda: NOW)
        record = RawDocumentRecord(
            document_id=DOCUMENT,
            source_key=KEY,
            source_url="upload://cbic_notifications/example",
            fetched_at=NOW,
            content_type="text/html",
            size=10,
            sha256=SHA,
            storage_key=f"ab/{SHA}",
            status=DocumentStatus.CLASSIFIED,
            parser_version="html@1",
        )
        with self.store() as unit:
            unit.sources.add(Source.of(SOURCES[KEY].definition(), NOW))
            unit.documents.add(record)
        self.rulebook.register_document(
            DocumentRecord(
                document=ParsedDocument(
                    DOCUMENT, DocumentType.NOTIFICATION, "Notification No. 99/2026", CLAUSES
                ),
                source_id=source_id_for(KEY),
                sha256=SHA,
                regulator="CBIC",
                url=record.source_url,
                media_type="text/html",
                fetched_at=NOW,
            )
        )

    def request(self, **overrides: Any) -> ExtractionRequest:
        values: dict[str, Any] = {
            "document_id": DOCUMENT.value,
            "source_id": source_id_for(KEY).value,
            "source_key": KEY,
            "regulator": "CBIC",
            "doc_type": DocumentType.NOTIFICATION,
        }
        values.update(overrides)
        return ExtractionRequest(**values)

    def candidates(self) -> list[RuleCandidateCreated]:
        return [e for e in self.store.events if isinstance(e, RuleCandidateCreated)]


def temperatures(requests: Sequence[CompletionRequest]) -> list[float]:
    return [request.temperature for request in requests]


async def test_a_candidate_is_asked_for_once_then_stored_with_its_event() -> None:
    world = World(json.dumps(ANSWER))
    answer = await world.extract.run(world.request())
    assert (answer.outcome, answer.attempts, answer.needs_review, answer.stored) == (
        "extracted",
        1,
        False,
        False,
    )
    assert answer.fields == ANSWER
    assert answer.prompt_version == RULE_PROMPT_REF
    assert temperatures(world.model.requests) == [0.0]
    stored = await world.write.run(answer)
    assert (stored.created, stored.outcome, stored.candidate_id) == (
        True,
        "extracted",
        candidate_id_for(DOCUMENT, RULE_PROMPT_REF).value,
    )
    (event,) = world.candidates()
    assert (event.suggested_rule_key, event.clause_ids) == (
        "gstr3b_monthly",
        (clause_id_for(DOCUMENT, "en.p2"),),
    )
    assert event.candidate is not None
    assert event.source_key == KEY
    assert world.store.documents[DOCUMENT].status is DocumentStatus.EXTRACTED


async def test_an_answer_that_is_not_a_candidate_is_asked_for_again_once() -> None:
    world = World("not json at all", json.dumps(ANSWER))
    answer = await world.extract.run(world.request())
    assert (answer.outcome, answer.attempts) == ("extracted", 2)
    assert temperatures(world.model.requests) == [0.0, RETRY_TEMPERATURE]
    assert world.model.requests[1].metadata["attempt"] == "2"


async def test_twice_not_a_candidate_is_stored_unparseable_for_review() -> None:
    no_citation = json.dumps({**ANSWER, "citations": []})
    world = World("not json at all", no_citation)
    answer = await world.extract.run(world.request())
    assert (answer.outcome, answer.attempts, answer.fields, answer.needs_review) == (
        "unparseable",
        2,
        None,
        True,
    )
    assert [(i.code, i.detail) for i in answer.issues] == [
        ("output_unparseable", "citations must cite at least one clause")
    ]
    assert answer.answer == no_citation, "the last answer is kept as given"
    await world.write.run(answer)
    (event,) = world.candidates()
    assert (event.outcome, event.candidate, event.clause_ids) == ("unparseable", None, ())


async def test_a_second_write_writes_nothing_and_a_stored_extraction_asks_nobody() -> None:
    world = World(json.dumps(ANSWER))
    answer = await world.extract.run(world.request())
    first = await world.write.run(answer)
    again = await world.write.run(answer)
    assert (first.created, again.created) == (True, False)
    assert len(world.candidates()) == 1, "the outbox gets the candidate once"
    later = await world.extract.run(world.request())
    assert (later.stored, later.outcome, later.fields) == (True, "extracted", ANSWER)
    assert len(world.model.requests) == 1, "no model is asked about a stored extraction"
    replayed = await world.write.run(later)
    assert (replayed.created, replayed.candidate_id) == (False, first.candidate_id)
    assert len(world.candidates()) == 1


async def test_a_used_up_budget_fails_the_attempt_for_the_workflow_to_wait() -> None:
    world = World(ModelBudgetExhaustedError("budget", retry_after_seconds=3600.0))
    with pytest.raises(ApplicationError) as raised:
        await world.extract.run(world.request())
    assert (raised.value.type, raised.value.non_retryable) == (BUDGET_ERROR, True)
    assert raised.value.details == (3600.0,)
    assert world.store.extractions == {}


async def test_with_the_extraction_off_nothing_is_asked_or_written() -> None:
    world = World(enabled=False)
    answer = await world.extract.run(world.request())
    assert answer.skipped
    stored = await world.write.run(answer)
    assert (stored.skipped, stored.created) == (True, False)
    assert (world.model.requests, world.candidates()) == ([], [])


def test_a_request_is_for_a_rule_kind_and_an_enabled_activity_needs_its_stage() -> None:
    with pytest.raises(ValueError, match="no rule is extracted from a press_release"):
        World().request(doc_type=DocumentType.PRESS_RELEASE)
    with pytest.raises(ValueError, match="needs its stage"):
        ExtractRules(MemoryRulebook(), None, MemoryStore(), enabled=True)
    assert ExtractionAnswer(request=World().request()).outcome == "unparseable"


def gateway(response: httpx2.Response) -> GatewayProvider:
    transport = httpx2.MockTransport(lambda _: response)
    return GatewayProvider(client=httpx2.Client(transport=transport, base_url="http://gw"))


def completion() -> CompletionRequest:
    return CompletionRequest(
        feature="extraction", prompt_version=RULE_PROMPT_REF, system="s", user="u"
    )


def test_the_gateways_budget_problem_is_a_budget_error_with_its_retry_after() -> None:
    problem = {
        "type": BUDGET_PROBLEM,
        "title": "LLM budget exceeded",
        "status": 429,
        "detail": "feature budget for extraction is used up for 2026-10",
    }
    refused = httpx2.Response(429, json=problem, headers={"retry-after": "86400"})
    with pytest.raises(ModelBudgetExhaustedError) as raised:
        gateway(refused).complete(completion())
    assert raised.value.retry_after_seconds == 86400.0
    assert "feature budget for extraction" in str(raised.value)
    unknown = httpx2.Response(429, json={**problem}, headers={})
    with pytest.raises(ModelBudgetExhaustedError) as without:
        gateway(unknown).complete(completion())
    assert without.value.retry_after_seconds is None


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(429, json={"type": "urn:compliancewatch:problem:rate-limited"}),
        httpx2.Response(429, text="slow down"),
        httpx2.Response(503, json={"type": BUDGET_PROBLEM}),
    ],
    ids=["another-problem", "no-problem", "not-a-429"],
)
def test_any_other_refusal_stays_a_gateway_error(response: httpx2.Response) -> None:
    with pytest.raises(GatewayError):
        gateway(response).complete(completion())
