"""A recorded notification flows to a parsed, classified, extracted rule candidate, through the
one deployable.

The whole app runs as ``cw-mvp serve`` runs it, on memory stores, with the pipeline's knowledge
and extraction on and its ingest starter handed in (a recording one, no Temporal). The
llm-gateway answers completions from a scripted model: for the recorded 01/2026-Central Tax, the
draft label of its golden case (evals/golden/extraction, ``label_status: draft``, nobody has
reviewed it: it shows the plumbing, not the law). An admin uploads the notification on the
internal listener with the shared write token; its ingest then runs as the worker runs it, one
activity after another: the parse, the classify step, the registration in the rulebook over its
HTTP API, and the rule extraction, which reads the document back from the rulebook, asks the
gateway's completions route with the registered prompt, and stores the candidate with its
rule.candidate.created. Every event the pipeline wrote fits its published schema.

A second run makes the gateway refuse for a used-up budget, as its metering does: the extraction
reads the gateway's problem type and hands the wait to its workflow, with the gateway's
Retry-After. With the gateway's own fake model, the answer is a placeholder with no citation, so
the extraction asks twice and stores an unparseable candidate for an analyst.
"""

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx2
import pytest
from jsonschema import Draft202012Validator
from temporalio.exceptions import ApplicationError

from cw_contracts.events import TOPICS
from cw_mvp.app import CombinedApp
from cw_mvp.testing import MEMORY_SERVICES, running_app
from domain_kernel.documents import DocumentType, clause_id_for
from domain_kernel.ids import DocumentId
from llm_gateway.application.metering import BudgetGuard
from llm_gateway.domain.errors import BudgetExceededError
from ontology import load as load_ontology
from pipeline.application.activities import ParseDocument, ParseRequest
from pipeline.application.classify import ClassifyDocument, ClassifyRequest
from pipeline.application.extraction import (
    BUDGET_ERROR,
    RULE_PROMPT,
    ExtractionRequest,
    ExtractRules,
    RuleExtractionStage,
    StoreExtraction,
)
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.application.knowledge_activities import RegisterDocument, RegisterRequest
from pipeline.domain.raw_documents import DocumentStatus
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
from py_common.events import to_message

REPO: Final = Path(__file__).resolve().parents[4]
FIXTURES: Final = REPO / "services/pipeline/tests/fixtures"
SCHEMAS: Final = REPO / "packages/contracts/events/schemas"
CASE: Final = load_case(
    REPO / "evals/golden/extraction/cbic_notifications/cases/01-2026-central-tax.yaml"
)
PIPELINE: Final = "/v1/pipeline"
RULEBOOK: Final = "/v1/rulebook"
TOKEN: Final = "journey-write-token"
WRITE: Final = {"x-cw-write-token": TOKEN}
ACTOR: Final = str(UUID(int=42))


def recorded_notification() -> bytes:
    wrapper = json.loads((FIXTURES / "cbic" / "gst-ct-01-2026.pdf.json").read_text())
    return base64.b64decode(wrapper["data"])


def ok(response: httpx2.Response, status: int = 200) -> Any:
    assert response.status_code == status, (response.status_code, response.text)
    return response.json()


class Pipeline:
    """The pipeline's store, raw store and ingest starter, shared by the app and the steps the
    worker would run, and the steps themselves."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.raw = MemoryRawStore()
        self.ingests = MemoryIngests()

    def overrides(self) -> dict[str, Any]:
        return {"units": self.store, "raw_store": self.raw, "ingests": self.ingests}

    async def ingest(self, internal: httpx2.Client) -> tuple[IngestRequest, Any]:
        """What the ingest workflow does with the uploaded document up to its extraction:
        parse, classify, register."""
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
        registered = await RegisterDocument(
            chain, self.rulebook(internal), enabled=True, raw_store=self.raw, units=self.store
        ).run(
            RegisterRequest(
                parse=parse,
                regulator=request.regulator,
                doc_type=DocumentType(classified.doc_type),
            )
        )
        assert not registered.skipped
        return request, classified

    @staticmethod
    def rulebook(internal: httpx2.Client) -> HttpRulebook:
        return HttpRulebook(token=TOKEN, client=internal)

    def extract(self, internal: httpx2.Client) -> ExtractRules:
        """The extraction activity as the worker builds it, its gateway the app's own."""
        stage = RuleExtractionStage(
            LlmRuleExtractor(
                GatewayProvider(client=internal), load_prompt(*RULE_PROMPT), load_ontology()
            )
        )
        return ExtractRules(self.rulebook(internal), stage, self.store, enabled=True)

    def extraction_request(self, request: IngestRequest, doc_type: str) -> ExtractionRequest:
        assert request.stored is not None
        return ExtractionRequest(
            document_id=request.stored.document_id,
            source_id=request.source_id,
            source_key=request.stored.source_key,
            regulator=request.regulator,
            doc_type=DocumentType(doc_type),
            own_ref=request.stored.external_ref,
        )


@contextmanager
def product(pipeline: Pipeline, gateway: dict[str, Any]) -> Iterator[httpx2.Client]:
    """The app on its memory stores with knowledge and extraction on, its internal listener."""
    services = {
        **MEMORY_SERVICES,
        "pipeline": {
            **MEMORY_SERVICES["pipeline"],
            "pipeline_knowledge_enabled": True,
            "pipeline_extraction_enabled": True,
            "rulebook_write_token": TOKEN,
        },
        "rulebook": {**MEMORY_SERVICES["rulebook"], "rulebook_write_token": TOKEN},
    }
    builds = {"pipeline": pipeline.overrides(), "llm-gateway": gateway}
    with (
        running_app(service_overrides=services, build_overrides=builds) as app,
        httpx2.Client(base_url=internal_url(app), timeout=30.0) as internal,
    ):
        yield internal


def internal_url(app: CombinedApp) -> str:
    return app.settings.mvp_internal_url


def upload(internal: httpx2.Client) -> Any:
    return ok(
        internal.post(
            f"{PIPELINE}/sources/cbic_notifications/uploads",
            headers=WRITE,
            files={"file": ("notification.pdf", recorded_notification(), "application/pdf")},
            data={
                "actor_id": ACTOR,
                "reason": "The recorded notification for the extraction journey",
                "title": "Seeks to extend the due date for furnishing FORM GSTR-3B",
                "external_ref": "01/2026-Central Tax",
            },
        ),
        202,
    )


def schema_check(event: Any) -> dict[str, Any]:
    """The event as a message, checked against its published schema and generated model."""
    message = to_message(event)
    spec = TOPICS[message.topic]
    assert message.schema_version == spec.version
    schema = json.loads((SCHEMAS / spec.schema_file).read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(
        message.payload
    )
    spec.model.model_validate(message.payload)
    return message.payload


async def test_a_recorded_notification_becomes_a_classified_extracted_candidate() -> None:
    assert CASE.expected is not None
    assert CASE.label_status == "draft"
    scripted = ScriptedProvider({str(CASE.document.document_id): json.dumps(CASE.expected)})
    pipeline = Pipeline()
    with product(pipeline, {"completion_provider": scripted}) as internal:
        uploaded = upload(internal)
        document_id = uploaded["document"]["document_id"]
        assert document_id == str(CASE.document.document_id)
        request, classified = await pipeline.ingest(internal)
        assert (classified.route, classified.doc_type, classified.confidence) == (
            "extract",
            "notification",
            "certain",
        )
        stored = ok(internal.get(f"{RULEBOOK}/documents/{document_id}"))
        assert (stored["doc_type"], stored["parser_version"]) == ("notification", "pdf@1")

        extraction = pipeline.extraction_request(request, classified.doc_type)
        answer = await pipeline.extract(internal).run(extraction)
        assert (answer.outcome, answer.attempts, answer.needs_review) == ("extracted", 1, False)
        assert [r.prompt_version for r in scripted.requests] == ["extraction.rule_candidate@1"]
        written = await StoreExtraction(pipeline.store).run(answer)
        assert (written.created, written.outcome) == (True, "extracted")
        again = await pipeline.extract(internal).run(extraction)
        assert again.stored, "a second extraction finds the first and asks no model"
        assert len(scripted.requests) == 1
        document = ok(internal.get(f"{PIPELINE}/documents/{document_id}"))
        assert document["status"] == "extracted"

    topics = [type(event).topic for event in pipeline.store.events]
    assert topics == [
        "document.discovered",
        "document.parsed",
        "document.classified",
        "rule.candidate.created",
    ]
    payloads = [schema_check(event) for event in pipeline.store.events]
    classified_payload, candidate = payloads[2], payloads[3]
    assert (classified_payload["relevance"], classified_payload["confidence"]) == (
        "relevant",
        "certain",
    )
    assert candidate["candidate"] == CASE.expected
    assert (candidate["outcome"], candidate["needs_review"], candidate["doc_type"]) == (
        "extracted",
        False,
        "notification",
    )
    assert candidate["suggested_rule_key"] == "gstr3b_monthly"
    assert candidate["clause_ids"] == [
        str(clause_id_for(DocumentId(UUID(document_id)), ref)) for ref in ("en.p3", "en.p4")
    ]
    record = pipeline.store.documents[DocumentId(UUID(document_id))]
    assert record.status is DocumentStatus.EXTRACTED


async def test_the_gateways_budget_refusal_and_its_fake_model_reach_the_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = Pipeline()
    with product(pipeline, {}) as internal:
        upload(internal)
        request, classified = await pipeline.ingest(internal)
        extraction = pipeline.extraction_request(request, classified.doc_type)

        def used_up(self: BudgetGuard, **_: Any) -> None:
            raise BudgetExceededError(
                "feature budget for extraction is used up for 2026-10",
                scope="feature",
                resets_at=datetime(2099, 1, 1, tzinfo=UTC),
            )

        with monkeypatch.context() as patched:
            patched.setattr(BudgetGuard, "check", used_up)
            with pytest.raises(ApplicationError) as refused:
                await pipeline.extract(internal).run(extraction)
        assert refused.value.type == BUDGET_ERROR
        (retry_after,) = refused.value.details
        assert isinstance(retry_after, float)
        assert retry_after > 86_400, "the gateway's Retry-After: until the budget resets"
        assert pipeline.store.extractions == {}

        answer = await pipeline.extract(internal).run(extraction)
        assert (answer.outcome, answer.attempts, answer.needs_review) == ("unparseable", 2, True)
        assert [issue.detail for issue in answer.issues] == [
            "citations must cite at least one clause"
        ]
        written = await StoreExtraction(pipeline.store).run(answer)
        assert written.created
    candidate = schema_check(pipeline.store.events[-1])
    assert (candidate["outcome"], candidate["candidate"], candidate["clause_ids"]) == (
        "unparseable",
        None,
        [],
    )
