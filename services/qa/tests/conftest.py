"""Fixtures: a small world of rule versions, clauses, entities, relations, a business and its
obligations in the memory fakes, and the question use case built over it.

Every document here is a test notice, not a regulator's text.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import ClassVar
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.ontology import Ontology
from ontology import load as load_ontology
from qa.application.answerer import Answerer
from qa.application.ask import AskQuestion
from qa.application.context import AskContext, AskRequest
from qa.application.kag import KagLayer
from qa.application.planner import Planner
from qa.application.retrieval import HybridLayer
from qa.application.solver import Budget, Solver
from qa.application.structured import StructuredLayer
from qa.domain.flags import KagTargeting
from qa.domain.prompt import PromptText
from qa.domain.records import ClauseRecord, Entity, RuleVersion
from qa.main import app
from qa.testing import (
    FakeEmbedder,
    MemoryObligations,
    MemoryProfiles,
    MemoryRulebook,
    RecordingTracer,
    ScriptedProvider,
    tenant_id,
)

TENANT = tenant_id(1)
OTHER_TENANT = tenant_id(2)
BUSINESS = BusinessId(UUID(int=10))
AS_OF = date(2026, 4, 10)
PLAN = PromptText("qa.plan", "1", "ai-platform", "Plan the question.")
ANSWER = PromptText("qa.answer", "1", "ai-platform", "Answer from the evidence.")
MONTHLY_RULE = "gstr3b_monthly"
EXTENSION_RULE = "gstr3b_extension"
MONTHLY_QUOTE = "furnish the return in FORM GSTR-3B for a month by the 20th day"
EXTENSION_QUOTE = "for the month of March, 2026 may be furnished till the 24th day of April, 2026"
MONTHLY_SPEC = {
    "all_of": [
        {"attribute": "registration_type", "operator": "eq", "value": "regular"},
        {"attribute": "filing_scheme", "operator": "eq", "value": "regular_monthly"},
    ]
}


@dataclass
class World:
    TENANT: ClassVar[TenantId] = TENANT
    OTHER_TENANT: ClassVar[TenantId] = OTHER_TENANT
    BUSINESS: ClassVar[BusinessId] = BUSINESS
    AS_OF: ClassVar[date] = AS_OF
    PLAN: ClassVar[str] = PLAN.ref
    ANSWER: ClassVar[str] = ANSWER.ref
    MONTHLY_RULE: ClassVar[str] = MONTHLY_RULE
    EXTENSION_RULE: ClassVar[str] = EXTENSION_RULE
    MONTHLY_QUOTE: ClassVar[str] = MONTHLY_QUOTE
    EXTENSION_QUOTE: ClassVar[str] = EXTENSION_QUOTE

    rulebook: MemoryRulebook
    profiles: MemoryProfiles
    obligations: MemoryObligations
    embedder: FakeEmbedder
    provider: ScriptedProvider
    tracer: RecordingTracer
    ontology: Ontology
    monthly: RuleVersion
    extension: RuleVersion
    draft: RuleVersion
    monthly_clause: ClauseRecord
    extension_clause: ClauseRecord
    draft_clause: ClauseRecord
    form: Entity
    notice: Entity

    def request(
        self,
        question: str,
        *,
        question_id: str = "q1",
        business: BusinessId | None = BUSINESS,
        as_of: date = AS_OF,
        tenant: int = 1,
    ) -> AskRequest:
        return AskRequest(tenant_id(tenant), question, as_of, question_id, business)

    def context(
        self,
        question: str = "a question",
        *,
        business: BusinessId | None = BUSINESS,
        as_of: date = AS_OF,
    ) -> AskContext:
        request = self.request(question, business=business, as_of=as_of)
        return AskContext(request, self.rulebook, self.profiles)

    def answerer(self) -> Answerer:
        return Answerer(self.provider, ANSWER)

    def solver(self, budget: Budget | None = None) -> Solver:
        return Solver(
            rulebook=self.rulebook,
            search=self.rulebook,
            embedder=self.embedder,
            obligations=self.obligations,
            ontology=self.ontology,
            tracer=self.tracer,
            budget=budget or Budget(),
        )

    def ask(
        self, targeting: KagTargeting | None = None, budget: Budget | None = None
    ) -> AskQuestion:
        answerer = self.answerer()
        return AskQuestion(
            rulebook=self.rulebook,
            profiles=self.profiles,
            structured=StructuredLayer(self.rulebook, self.obligations),
            kag=KagLayer(Planner(self.provider, PLAN), self.solver(budget), answerer),
            hybrid=HybridLayer(self.rulebook, self.embedder, answerer, self.tracer),
            targeting=targeting or KagTargeting(enabled=True),
            tracer=self.tracer,
        )


@pytest.fixture(scope="session")
def ontology() -> Ontology:
    return load_ontology()


@pytest.fixture
def world(ontology: Ontology) -> World:
    rulebook = MemoryRulebook()
    monthly_clause = rulebook.add_clause(
        "A registered person shall " + MONTHLY_QUOTE + " of the month succeeding that month.",
        clause_ref="en.p1",
        external_ref="TEST-01",
        published_at=date(2026, 1, 5),
    )
    extension_clause = rulebook.add_clause(
        "The return in FORM GSTR-3B " + EXTENSION_QUOTE + ".",
        clause_ref="en.p3",
        external_ref="TEST-02",
        published_at=date(2026, 3, 30),
    )
    draft_clause = rulebook.add_clause(
        "A draft test notice that amends nothing yet.",
        clause_ref="en.p1",
        external_ref="TEST-03",
        published_at=date(2026, 4, 2),
    )
    monthly = rulebook.add_version(
        MONTHLY_RULE,
        effective_from=date(2026, 4, 1),
        title="File FORM GSTR-3B every month",
        specification=MONTHLY_SPEC,
    )
    rulebook.cite(monthly, monthly_clause, MONTHLY_QUOTE)
    extension = rulebook.add_version(
        EXTENSION_RULE, effective_from=date(2026, 3, 30), title="GSTR-3B March 2026 extension"
    )
    rulebook.cite(extension, extension_clause, EXTENSION_QUOTE)
    draft = rulebook.add_version(
        "gstr3b_draft", effective_from=date(2026, 4, 1), title="Draft", status="draft"
    )
    rulebook.relate(
        extension,
        RelationKind.EXTENDS_DEADLINE,
        monthly,
        extension_clause,
        period_label="2026-03",
        new_due_on=date(2026, 4, 24),
    )
    rulebook.relate(draft, RelationKind.AMENDS, monthly, draft_clause)
    form = rulebook.add_entity(
        EntityType.FORM, "GSTR-3B", mentioned_in=[monthly_clause, extension_clause]
    )
    notice = rulebook.add_entity(EntityType.NOTIFICATION, "TEST-01", mentioned_in=[monthly_clause])
    rulebook.relate(extension, RelationKind.REFERS_TO, notice, extension_clause)
    profiles = MemoryProfiles()
    profiles.add(
        TENANT,
        BUSINESS,
        {"registration_type": "regular", "filing_scheme": "regular_monthly", "state_codes": ["29"]},
    )
    obligations = MemoryObligations()
    obligations.add(
        TENANT,
        BUSINESS,
        monthly,
        "File GSTR-3B for the month (2026-04)",
        date(2026, 5, 20),
        period_label="2026-04",
    )
    obligations.add(
        TENANT,
        BUSINESS,
        monthly,
        "File GSTR-3B for the month (2026-03)",
        date(2026, 4, 20),
        period_label="2026-03",
    )
    return World(
        rulebook=rulebook,
        profiles=profiles,
        obligations=obligations,
        embedder=FakeEmbedder(),
        provider=ScriptedProvider(),
        tracer=RecordingTracer(),
        ontology=ontology,
        monthly=monthly,
        extension=extension,
        draft=draft,
        monthly_clause=monthly_clause,
        extension_clause=extension_clause,
        draft_clause=draft_clause,
        form=form,
        notice=notice,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
