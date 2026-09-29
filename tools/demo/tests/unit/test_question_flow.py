"""A question from end to end: rulebook, profile, obligation, gateway and qa in one process.

The recorded 01/2026-Central Tax notification is registered through the pipeline's rulebook
client, its extension of GSTR-3B is staged from a scripted relation answer and approved from
the extension's version to the monthly rule's, both versions are cited, submitted, approved and
published through the rulebook API (publishing on, memory store). The profile service holds
the demo business (entity, registration, attributes), the obligation store materialises the
published monthly rule for it and applies the deadline change the extension announced, and the
gateway embeds every clause with its fake provider. qa then asks over HTTP clients bound to
those apps, its model calls going through the gateway to a scripted model, with the KAG layer
on for the demo tenant only. Seed values stay the seed's; the published versions live in memory
for this test alone.
"""

import asyncio
import base64
import dataclasses
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from cw_demo import tenant as demo
from domain_kernel.documents import DocumentRef, RawDocument
from domain_kernel.ids import BusinessId, DecisionId, RuleId, RuleVersionId, SourceId, TenantId
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import (
    Applicability,
    specification_from_mapping,
    specification_to_mapping,
)
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate, RuleVersionSnapshot
from llm_gateway.main import build_app as build_gateway
from llm_gateway.settings import GatewaySettings
from obligation.application.changes import ApplyDeadlineChange, DeadlineChange
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.domain.events import RescheduleReason
from obligation.main import build_app as build_obligation
from obligation.settings import ObligationSettings
from ontology import load as load_ontology
from pipeline.application.embedding import EmbeddingStage
from pipeline.application.knowledge_activities import (
    ExtractMentions,
    MentionsRequest,
    ProposeRelations,
    RelationsRequest,
    SubmitRelations,
)
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.domain.knowledge import DocumentRecord
from pipeline.infrastructure.gateway import GatewayEmbedder
from pipeline.infrastructure.parsers import PdfParser
from pipeline.infrastructure.prompts import load_prompt
from pipeline.infrastructure.rulebook_client import HttpRulebook as PipelineRulebook
from pipeline.testing import ScriptedProvider as RelationScript
from profile_service.main import build_app as build_profile
from profile_service.settings import ProfileSettings
from qa.infrastructure.gateway import GatewayProvider, HttpEmbedder
from qa.infrastructure.obligation_client import HttpObligations
from qa.infrastructure.profile_client import HttpProfiles
from qa.infrastructure.rulebook_client import HttpRulebook as QaRulebook
from qa.main import build_app as build_qa
from qa.testing import RecordingTracer, answer_text, plan_step, plan_text, qa_settings
from qa.wiring import Ports
from rulebook.application.seed_loader import load_calendar
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app as build_rulebook
from rulebook.testing import WRITE_TOKEN, rulebook_settings

FIXTURES = Path(__file__).resolve().parents[4] / "services" / "pipeline" / "tests" / "fixtures"
RULEBOOK: Final = "/v1/rulebook"
PROFILE: Final = "/v1/profile"
ASK: Final = "/v1/qa/ask"
AUTH: Final = {"x-cw-write-token": WRITE_TOKEN}
OWN_REF: Final = "01/2026-Central Tax"
PUBLISHED_ON: Final = date(2026, 4, 21)
"""The date the notification bears (en.p2: "dated the 21st April, 2026")."""
MONTHLY: Final = "gstr3b_monthly"
EXTENSION: Final = "gstr3b_extension_2026_03"
EXTENSION_TITLE: Final = (
    "01/2026-Central Tax: Seeks to extends the due date for furnishing the return in FORM GSTR-3B "
    "for the month of March, 2026 till the twenty-first day of April, 2026"
)
"""The notification's number and its title in the CBIC listing."""
EXTENSION_FROM: Final = date(2026, 4, 20)
"""The date of effect en.p4 states."""
EXTENDS: Final = (
    "hereby extends the due  date for furnishing the return in FORM GSTR-3B for the month of "
    "March, 2026 till the twenty -first day of April, 2026"
)
WHO_FILES: Final = (
    "for the registered persons who are required to furnish return under sub-section (1) of "
    "section 39 read with clause (i) of sub -rule (1) of  rule 61 of the Central Goods and "
    "Services Tax Rules, 2017"
)
CITATIONS: Final[Mapping[str, Mapping[str, str]]] = {
    MONTHLY: {"en.p3": WHO_FILES},
    EXTENSION: {
        "en.p2": (
            "NOTIFICATION No. 01/2026 \u2013 Central Tax New Delhi, dated the 21st April, 2026"
        ),
        "en.p3": EXTENDS,
        "en.p4": "This notification shall come into effect from 20th day of April, 2026.",
    },
}
RELATION_ANSWER: Final = json.dumps(
    {
        "relations": [
            {
                "relation": "extends_deadline",
                "target_mention": "M2",
                "rule_key": MONTHLY,
                "evidence_clause_ref": "en.p3",
                "evidence_quote": EXTENDS,
                "period": "2026-03",
                "new_due_date": "2026-04-21",
                "confidence": 0.9,
            }
        ]
    }
)
ACME: Final = TenantId(UUID(int=0xF10A))
OTHER: Final = TenantId(UUID(int=0xF10B))
"""A tenant the KAG layer is not on for."""
ANALYST: Final = {"actor_id": str(UUID(int=0xA1))}
MATERIALISE_FROM: Final = date(2026, 4, 1)
MONTHS_AHEAD: Final = 12
PLAN_REF: Final = "qa.plan@1"
ANSWER_REF: Final = "qa.answer@1"
LAST_MARCH: Final = "When was Acme Bengaluru's GSTR-3B for March 2026 due?"
EXTENDED_TILL: Final = (
    "Till what date did notification 01/2026-Central Tax extend the due date for furnishing "
    "FORM GSTR-3B for March 2026?"
)
AFTER_EXTENSION: Final = date(2026, 4, 22)


class ScriptedModel:
    """The model behind the gateway, scripted per question id (the request's ``x-request-id``,
    which qa sends as ``question_id``): a plan, and an answer quoting one clause. The answer
    cites the label the evidence in the prompt gives that clause, as a model reading the prompt
    would. A call nobody scripted fails the question. Not a model."""

    MODEL = "scripted/question-flow"

    def __init__(self) -> None:
        self.plans: dict[str, str] = {}
        self.answers: dict[str, tuple[str, str, str]] = {}
        self.requests: list[CompletionRequest] = []

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        self.requests.append(req)
        question = req.metadata.get("question_id", "")
        if req.prompt_version == PLAN_REF and question in self.plans:
            text = self.plans[question]
        elif req.prompt_version == ANSWER_REF and question in self.answers:
            answer, clause_ref, quote = self.answers[question]
            text = answer_text(answer, (_label(req.user, clause_ref), quote))
        else:
            raise LookupError(f"no scripted reply for {question} {req.prompt_version}")
        return CompletionResponse(text=text, model=self.MODEL, input_tokens=0, output_tokens=0)

    def calls(self, question: str) -> list[tuple[str, dict[str, str]]]:
        return [
            (req.prompt_version, dict(req.metadata))
            for req in self.requests
            if req.metadata.get("question_id") == question
        ]


def _label(prompt: str, clause_ref: str) -> str:
    found = re.search(rf"^\[(C[0-9]+)\] {re.escape(clause_ref)} \(", prompt, re.MULTILINE)
    return found.group(1) if found else f"not-in-evidence/{clause_ref}"


@dataclass(frozen=True, slots=True)
class Flow:
    rulebook: TestClient
    profile: TestClient
    obligation: TestClient
    gateway: TestClient
    model: ScriptedModel
    document_id: str
    business: BusinessId
    versions: Mapping[str, RuleVersionId]
    deadline_changes: Sequence[Mapping[str, Any]]


@contextmanager
def question_flow(*, publish: Sequence[str]) -> Iterator[Flow]:
    """The five apps, seeded; the versions in ``publish`` are published in that order, the
    others stay draft."""
    model = ScriptedModel()
    rulebook_app = build_rulebook(rulebook_settings(rulebook_publish_enabled=True))
    obligation_app = build_obligation(
        ObligationSettings(_env_file=None, service_name="obligation", obligation_store="memory")
    )
    with (
        TestClient(build_gateway(_gateway_settings(), completion_provider=model)) as gateway,
        TestClient(rulebook_app) as rulebook,
        TestClient(
            build_profile(
                ProfileSettings(_env_file=None, service_name="profile", profile_store="memory")
            )
        ) as profile,
        TestClient(obligation_app) as obligation,
    ):
        writer = PipelineRulebook(token=WRITE_TOKEN, client=rulebook)
        record = _recorded()
        document_id = str(writer.register_document(record).document_id)
        clauses = _clause_ids(rulebook, document_id)
        versions = _drafts(rulebook_app.state.wiring.unit_of_work)
        _stage_and_approve(rulebook, writer, record, versions)
        for rule_key, quotes in CITATIONS.items():
            citations = [
                {"clause_id": clauses[ref], "quote": quote} for ref, quote in quotes.items()
            ]
            _ok(
                rulebook.put(
                    f"{RULEBOOK}/rule-versions/{versions[rule_key]}/citations",
                    json={"citations": citations},
                    headers=AUTH,
                )
            )
        changes: list[dict[str, Any]] = []
        for rule_key in publish:
            for step in ("submit", "approve", "publish"):
                answer = _ok(
                    rulebook.post(
                        f"{RULEBOOK}/rule-versions/{versions[rule_key]}/{step}",
                        json=ANALYST,
                        headers=AUTH,
                    )
                )
            changes.extend(answer["deadline_changes"])
        EmbeddingStage(GatewayEmbedder(client=gateway), writer).embed_missing(None)
        business = _register_business(profile)
        _materialise(
            obligation_app.state.wiring.unit_of_work,
            rulebook,
            profile,
            business,
            versions[MONTHLY],
            changes,
        )
        yield Flow(
            rulebook, profile, obligation, gateway, model, document_id, business, versions, changes
        )


def _gateway_settings() -> GatewaySettings:
    return GatewaySettings(
        _env_file=None,
        service_name="llm-gateway",
        llm_provider="fake",
        llm_ledger="memory",
        llm_cache_ttl_seconds=0,
        llm_feature_monthly_budget_inr=Decimal("100000"),
        llm_tenant_monthly_budget_inr=Decimal("100000"),
        langfuse_host=None,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )


def _recorded() -> DocumentRecord:
    name = "gst-ct-01-2026.pdf"
    wrapper = json.loads((FIXTURES / "cbic" / f"{name}.json").read_text(encoding="utf-8"))
    source = SourceId(UUID(int=11))
    ref = DocumentRef(source, f"https://example.invalid/{name}", OWN_REF)
    raw = RawDocument.from_bytes(
        ref, base64.b64decode(wrapper["data"]), "application/pdf", datetime(2026, 9, 28, tzinfo=UTC)
    )
    document = dataclasses.replace(PdfParser().parse(raw), published_at=PUBLISHED_ON)
    return DocumentRecord(
        document=document,
        source_id=source,
        sha256=raw.sha256,
        regulator="CBIC",
        url=ref.url,
        media_type=raw.media_type,
        fetched_at=raw.fetched_at,
        external_ref=OWN_REF,
    )


def _clause_ids(rulebook: TestClient, document_id: str) -> dict[str, str]:
    stored = _ok(rulebook.get(f"{RULEBOOK}/documents/{document_id}"))
    return {clause["clause_ref"]: clause["clause_id"] for clause in stored["clauses"]}


def _drafts(store: MemoryKnowledgeStore) -> dict[str, RuleVersionId]:
    """The monthly rule as the seed command writes it, and the extension's version: drafts."""
    seed = next(r for r in load_calendar(load_ontology()).rules if r.rule_key == MONTHLY)
    _, monthly = store.add_rule(
        seed.rule_key,
        title=seed.title,
        regulator=seed.regulator,
        level=seed.level,
        effective_from=seed.effective_from,
        summary=seed.summary,
        specification=specification_to_mapping(seed.specification),
        obligation_template=seed.obligation_template.to_mapping(),
        recurrence=None if seed.recurrence is None else seed.recurrence.to_mapping(),
    )
    _, extension = store.add_rule(
        EXTENSION, title=EXTENSION_TITLE, regulator="cbic", effective_from=EXTENSION_FROM
    )
    return {MONTHLY: monthly, EXTENSION: extension}


def _stage_and_approve(
    rulebook: TestClient,
    writer: PipelineRulebook,
    record: DocumentRecord,
    versions: Mapping[str, RuleVersionId],
) -> None:
    """Mentions aligned or queued, the relation staged from the scripted answer, the form's
    entity created by an analyst, the candidate approved from the extension to the monthly
    rule."""
    document_id = record.document.document_id.value
    asyncio.run(
        ExtractMentions(writer, writer, enabled=True).run(
            MentionsRequest(document_id=document_id, own_ref=OWN_REF)
        )
    )
    stage = RelationStage(
        LlmRelationExtractor(
            RelationScript({}, default=RELATION_ANSWER),
            load_prompt("extraction.rule_relations", "1"),
        )
    )
    batch = asyncio.run(
        ProposeRelations(writer, stage, enabled=True).run(
            RelationsRequest(document_id=document_id, own_ref=OWN_REF, regulator="CBIC")
        )
    )
    asyncio.run(SubmitRelations(writer, enabled=True).run(batch))
    _ok(
        rulebook.post(
            f"{RULEBOOK}/review/entities/decisions",
            json={
                "entity_type": "form",
                "proposed_name": "GSTR-3B",
                "decision": "create_entity",
                "decided_by": "analyst",
            },
            headers=AUTH,
        )
    )
    (candidate,) = _ok(rulebook.get(f"{RULEBOOK}/review/relations"))
    _ok(
        rulebook.post(
            f"{RULEBOOK}/review/relations/{candidate['candidate_id']}/approve",
            json={
                "from_rule_version_id": str(versions[EXTENSION]),
                "target_rule_version_id": str(versions[MONTHLY]),
                "decided_by": "analyst",
            },
            headers=AUTH,
        )
    )


def _register_business(profile: TestClient) -> BusinessId:
    """The demo business: its entity by PAN, the registration under it, the owner's answers."""
    headers = {"x-tenant-id": str(ACME)}
    _ok(
        profile.post(
            f"{PROFILE}/entities",
            json={"pan": demo.GSTIN[2:12], "name": demo.ENTITY_NAME},
            headers=headers,
        )
    )
    node = _ok(
        profile.post(
            f"{PROFILE}/registrations",
            json={"gstin": demo.GSTIN, "name": demo.REGISTRATION_NAME},
            headers=headers,
        )
    )
    ontology = load_ontology()
    fy = "2026-27"
    changes: dict[str, list[dict[str, object]]] = {}
    for key, value in {"registration_type": "regular", **demo.ATTRIBUTES}.items():
        definition = ontology.require(key)
        target = node["id"] if definition.level.value == "registration" else node["parent_id"]
        change: dict[str, object] = {"key": key, "value": value}
        if definition.per_financial_year:
            change["as_of_fy"] = fy
        changes.setdefault(str(target), []).append(change)
    for target, items in changes.items():
        _ok(
            profile.put(
                f"{PROFILE}/nodes/{target}/attributes",
                json={"changes": items, "source": "user_input"},
                headers=headers,
            )
        )
    return BusinessId(UUID(str(node["id"])))


def _materialise(
    unit_of_work: Any,
    rulebook: TestClient,
    profile: TestClient,
    business: BusinessId,
    monthly: RuleVersionId,
    changes: Sequence[Mapping[str, Any]],
) -> None:
    """The obligations the published monthly rule implies for the business, then the deadline
    changes the publications announced."""
    data = _ok(rulebook.get(f"{RULEBOOK}/rule-versions/{monthly}"))
    if data["status"] != "published":
        return
    version = RuleVersionSnapshot(
        rule_id=RuleId(UUID(str(data["rule_id"]))),
        rule_version_id=monthly,
        version=int(data["version"]),
        regulator=str(data["regulator"]),
        title=str(data["title"]),
        specification=specification_from_mapping(dict(data["specification"])),
        effective=EffectivePeriod(date.fromisoformat(str(data["effective_from"])), None),
        obligation_template=ObligationTemplate.from_mapping(data["obligation_template"]),
        recurrence=Recurrence.from_mapping(data["recurrence"]),
    )
    snapshot = _ok(
        profile.get(
            f"{PROFILE}/nodes/{business}/snapshot",
            params={"fy": "2026-27"},
            headers={"x-tenant-id": str(ACME)},
        )
    )
    attributes = {
        key: frozenset(value) if isinstance(value, list) else value
        for key, value in dict(snapshot["attributes"]).items()
    }
    assert version.specification.evaluate(attributes, load_ontology()) is Applicability.APPLIES
    MaterialiseObligations(unit_of_work, window=MONTHS_AHEAD).run(
        MaterialiseRequest(ACME, business, DecisionId.new(), version, MATERIALISE_FROM)
    )
    for change in changes:
        ApplyDeadlineChange(unit_of_work).run(
            DeadlineChange(
                tenant_id=ACME,
                rule_version_id=RuleVersionId(UUID(str(change["rule_version_id"]))),
                period_label=change["period_label"],
                new_due_on=date.fromisoformat(str(change["new_due_on"])),
                reason=RescheduleReason.DEADLINE_EXTENDED,
            )
        )


def _ok(response: Any) -> Any:
    assert response.status_code in (200, 201), response.text
    return response.json()


@contextmanager
def qa_client(flow: Flow) -> Iterator[tuple[TestClient, RecordingTracer]]:
    """qa on HTTP clients bound to the flow's apps, the KAG layer on for the demo tenant only."""
    rulebook = QaRulebook(client=flow.rulebook)
    tracer = RecordingTracer()
    ports = Ports(
        rulebook=rulebook,
        search=rulebook,
        profiles=HttpProfiles(client=flow.profile),
        obligations=HttpObligations(client=flow.obligation),
        embedder=HttpEmbedder(client=flow.gateway),
        provider=GatewayProvider(client=flow.gateway),
        tracer=tracer,
    )
    settings = qa_settings(qa_kag_enabled=True, qa_kag_tenants=frozenset({ACME.value}))
    with TestClient(build_qa(settings, ports=ports)) as client:
        yield client, tracer


def ask(
    client: TestClient,
    question_id: str,
    question: str,
    as_of: date,
    *,
    tenant: TenantId = ACME,
    business: BusinessId | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"question": question, "as_of": as_of.isoformat()}
    if business is not None:
        body["business_node_id"] = str(business)
    headers = {"x-tenant-id": str(tenant), "x-request-id": question_id}
    answer: dict[str, Any] = _ok(client.post(ASK, json=body, headers=headers))
    return answer


def layers(answer: Mapping[str, Any]) -> list[tuple[str, str, str | None]]:
    return [(item["layer"], item["result"], item["reason"]) for item in answer["layers"]]


def cited(answer: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [(c["clause_ref"], c["document_id"]) for c in answer["citations"]]


def gstr3b_plan() -> str:
    """The monthly rule, whether it applies to the business, and what extends its deadline."""
    return plan_text(
        plan_step(1, "rules_in_force", rule_key=MONTHLY),
        plan_step(2, "evaluate_applicability", source="s1"),
        plan_step(
            3, "follow", source="s1", relations=["extends_deadline"], direction="in", depth=1
        ),
        plan_step(4, "answer", sources=["s2", "s3"]),
    )


@pytest.fixture(scope="module")
def flow() -> Iterator[Flow]:
    with question_flow(publish=(MONTHLY, EXTENSION)) as built:
        yield built


def test_publishing_the_extension_announces_the_new_due_date(flow: Flow) -> None:
    ((change),) = flow.deadline_changes
    assert (change["rule_version_id"], change["period_label"], change["new_due_on"]) == (
        str(flow.versions[MONTHLY]),
        "2026-03",
        "2026-04-21",
    )
    in_force = _ok(flow.rulebook.get(f"{RULEBOOK}/rule-versions", params={"as_of": "2026-04-22"}))
    assert [item["rule_key"] for item in in_force] == [EXTENSION, MONTHLY]


def test_the_structured_layer_answers_from_the_obligations(flow: Flow) -> None:
    with qa_client(flow) as (client, _):
        answer = ask(
            client,
            "flow-structured",
            "When is my GSTR-3B due?",
            date(2026, 9, 28),
            business=flow.business,
        )
    assert (answer["outcome"], answer["layer"]) == ("answered", "structured")
    assert layers(answer) == [("structured", "answered", None)]
    assert "due on 20 October 2026" in answer["answer"]
    assert cited(answer) == [("en.p3", flow.document_id)]
    assert answer["plan"] is None
    assert flow.model.calls("flow-structured") == []


def test_the_kag_layer_follows_the_extension_and_cites_it(flow: Flow) -> None:
    flow.model.plans["flow-kag"] = gstr3b_plan()
    flow.model.answers["flow-kag"] = (
        "Acme Bengaluru files FORM GSTR-3B every month, and notification No. 01/2026-Central "
        "Tax extended the due date for March 2026 till 21 April 2026.",
        "en.p3",
        EXTENDS,
    )
    with qa_client(flow) as (client, tracer):
        answer = ask(client, "flow-kag", LAST_MARCH, AFTER_EXTENSION, business=flow.business)
    assert (answer["outcome"], answer["layer"]) == ("answered", "kag")
    assert layers(answer) == [("structured", "passed", None), ("kag", "answered", None)]
    assert cited(answer) == [("en.p3", flow.document_id)]
    assert [step["id"] for step in answer["plan"]["steps"]] == ["s1", "s2", "s3", "s4"]
    steps = tracer.named("qa.solve.step")
    assert [(s.attributes["qa.step.id"], s.attributes["qa.step.op"]) for s in steps] == [
        ("s1", "rules_in_force"),
        ("s2", "evaluate_applicability"),
        ("s3", "follow"),
        ("s4", "answer"),
    ]
    assert steps[2].attributes["qa.step.items"] == 1
    assert [(ref, meta["stage"], meta["layer"]) for ref, meta in flow.model.calls("flow-kag")] == [
        (PLAN_REF, "plan", "kag"),
        (ANSWER_REF, "answer", "kag"),
    ]


def test_a_tenant_the_flag_does_not_target_goes_to_hybrid_without_a_plan(flow: Flow) -> None:
    flow.model.answers["flow-other"] = (
        "Notification No. 01/2026-Central Tax extended the due date for March 2026 till "
        "21 April 2026.",
        "en.p3",
        EXTENDS,
    )
    with qa_client(flow) as (client, tracer):
        answer = ask(client, "flow-other", EXTENDED_TILL, date(2026, 9, 28), tenant=OTHER)
    assert (answer["outcome"], answer["layer"]) == ("answered", "hybrid")
    assert layers(answer) == [("structured", "passed", None), ("hybrid", "answered", None)]
    assert cited(answer) == [("en.p3", flow.document_id)]
    assert answer["plan"] is None
    assert [ref for ref, _ in flow.model.calls("flow-other")] == [ANSWER_REF]
    assert tracer.named("qa.solve.step") == []


def test_the_gateway_serves_both_qa_prompts_from_its_registry(flow: Flow) -> None:
    listed = {
        (item["name"], item["version"]): item["owner"]
        for item in _ok(flow.gateway.get("/v1/llm-gateway/prompts"))
    }
    assert listed[("qa.plan", "1")] == listed[("qa.answer", "1")] == "ai-platform"
    unknown = flow.gateway.post(
        "/v1/llm-gateway/completions",
        json={"feature": "qa", "prompt": "qa.plan@9", "user": LAST_MARCH},
        headers={"x-tenant-id": str(ACME)},
    )
    assert unknown.status_code == 422
    assert all(req.prompt_version in (PLAN_REF, ANSWER_REF) for req in flow.model.requests)


def test_a_version_still_in_draft_is_hidden_so_the_question_falls_back() -> None:
    with question_flow(publish=(MONTHLY,)) as draft:
        in_force = _ok(
            draft.rulebook.get(f"{RULEBOOK}/rule-versions", params={"as_of": "2026-04-22"})
        )
        assert [item["rule_key"] for item in in_force] == [MONTHLY]
        draft.model.plans["flow-draft"] = gstr3b_plan()
        draft.model.answers["flow-draft"] = (
            "Notification No. 01/2026-Central Tax extended the due date for March 2026 till "
            "21 April 2026.",
            "en.p3",
            EXTENDS,
        )
        with qa_client(draft) as (client, tracer):
            answer = ask(client, "flow-draft", LAST_MARCH, AFTER_EXTENSION, business=draft.business)
    assert layers(answer) == [
        ("structured", "passed", None),
        ("kag", "fallback", "no_evidence"),
        ("hybrid", "answered", None),
    ]
    assert answer["layer"] == "hybrid"
    assert answer["plan"] is not None
    follow = tracer.named("qa.solve.step")[2]
    assert (follow.attributes["qa.step.op"], follow.attributes["qa.step.items"]) == ("follow", 0)
    assert [ref for ref, _ in draft.model.calls("flow-draft")] == [PLAN_REF, ANSWER_REF]
