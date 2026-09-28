import json
from uuid import UUID

import httpx2
import pytest

from domain_kernel.documents import Clause, DocumentType, ExtractionContext, ParsedDocument
from domain_kernel.ids import DocumentId
from domain_kernel.llm import CompletionRequest
from ontology import load
from pipeline.application.extractor import LlmRuleExtractor, issues_summary, render_document
from pipeline.domain.candidate import CANDIDATE_SCHEMA
from pipeline.domain.prompt import PromptText
from pipeline.infrastructure.gateway import GatewayError, GatewayProvider
from pipeline.infrastructure.prompts import load_prompt, prompt_digest
from pipeline.testing import ScriptedProvider

DOC = ParsedDocument(
    DocumentId(UUID(int=9)),
    DocumentType.NOTIFICATION,
    "Notification 01/2026",
    (Clause("en.p1", "The due date is extended till the 21st April, 2026."),),
)
CTX = ExtractionContext("cbic", "extraction.rule_candidate@1", "scripted", "0.2.0")
ANSWER = {
    "title": "Extension",
    "summary": "Extended.",
    "doc_kind": "notification",
    "change_kind": "extension",
    "effective_from": None,
    "effective_to": None,
    "references": [],
    "applies_to": [],
    "obligation": None,
    "recurrence": None,
    "amounts": [],
    "citations": [{"clause_ref": "en.p1", "quote": "extended till the 21st April, 2026"}],
    "confidence": 0.85,
}
PROMPT = PromptText("extraction.rule_candidate", "1", "regulatory-intelligence", "Extract.")


def test_extractor_sends_the_registered_prompt_and_schema_and_validates() -> None:
    provider = ScriptedProvider({str(DOC.document_id): json.dumps(ANSWER)})
    outcome = LlmRuleExtractor(provider, PROMPT, load()).run(DOC, CTX)
    request = provider.requests[0]
    assert request.feature == "extraction"
    assert request.prompt_version == "extraction.rule_candidate@1"
    assert request.system == "Extract."
    assert request.json_schema is not None
    assert request.json_schema["title"] == CANDIDATE_SCHEMA["title"]
    assert request.metadata["document_id"] == str(DOC.document_id)
    assert "[en.p1] The due date" in request.user
    assert outcome.fields is not None
    assert outcome.report.ok
    assert not outcome.needs_review
    payload = dict(outcome.candidate.payload)
    assert payload["prompt"] == "extraction.rule_candidate@1"
    validation = payload["validation"]
    assert isinstance(validation, dict)
    assert validation["citation_count"] == 1
    assert outcome.candidate.confidence.value == 0.85
    assert outcome.candidate.model == "scripted/golden"


def test_unparseable_output_becomes_a_candidate_that_needs_review() -> None:
    provider = ScriptedProvider(default='{"doc_kind": "placeholder"}')
    outcome = LlmRuleExtractor(provider, PROMPT, load()).run(DOC, CTX)
    assert outcome.fields is None
    assert outcome.needs_review
    assert outcome.report.codes() == ("output_unparseable",)
    assert outcome.candidate.confidence.value == 0.0
    assert issues_summary([outcome.report]) == {"output_unparseable": 1}


def test_render_document_truncates() -> None:
    long = ParsedDocument(
        DOC.document_id, DOC.doc_type, "t", tuple(Clause(f"en.p{i}", "x" * 50) for i in range(1, 6))
    )
    text = render_document(long, limit=120)
    assert "[truncated" in text
    assert text.count("[en.p") == 2


def test_prompt_file_loads_and_matches_the_gateway_registry() -> None:
    prompt = load_prompt("extraction.rule_candidate", "1")
    assert prompt.ref == "extraction.rule_candidate@1"
    assert prompt.owner == "regulatory-intelligence"
    assert "Answer with the JSON object only" in prompt.system
    assert len(prompt_digest("extraction.rule_candidate", "1")) == 64


def test_gateway_provider_posts_and_reads_the_completion() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path != "/v1/llm-gateway/completions":
            return httpx2.Response(404)
        body = json.loads(request.content)
        assert body["prompt"] == "extraction.rule_candidate@1"
        assert body["json_schema"]["title"] == "RuleCandidateFields"
        assert body["metadata"] == {"document_id": "d"}
        return httpx2.Response(
            200,
            json={
                "text": "{}",
                "model_served": "fake/echo",
                "input_tokens": 3,
                "output_tokens": 1,
                "cached": False,
                "trace_id": "t1",
            },
        )

    client = httpx2.Client(base_url="http://gateway.test", transport=httpx2.MockTransport(handler))
    provider = GatewayProvider(client=client, tenant_id="00000000-0000-0000-0000-000000000001")
    response = provider.complete(
        CompletionRequest(
            feature="extraction",
            prompt_version="extraction.rule_candidate@1",
            system="s",
            user="u",
            json_schema=CANDIDATE_SCHEMA,
            metadata={"document_id": "d"},
        )
    )
    assert (response.text, response.model, response.trace_id) == ("{}", "fake/echo", "t1")
    assert seen[0].headers["x-tenant-id"].endswith("0001")
    provider.close()


def test_gateway_errors_are_raised_with_the_problem_body() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(422, json={"title": "LLM prompt not registered"})

    client = httpx2.Client(base_url="http://gateway.test", transport=httpx2.MockTransport(handler))
    provider = GatewayProvider(client=client)
    with pytest.raises(GatewayError, match=r"422.*not registered"):
        provider.complete(CompletionRequest("extraction", "x.y@1", "s", "u"))
