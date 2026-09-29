"""Composition root for the qa service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The answers are built from the rulebook, profile and obligation services and the llm-gateway,
over HTTP; tests and evals pass their own ``Ports`` (memory fakes and a scripted model). Both
prompt files are read when the app is built, from ``CW_QA_PROMPTS_DIR`` or the source tree, and
the ``prompts`` readiness check reads them again. The ontology is the packaged one.
"""

from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError
from domain_kernel.ids import TenantId
from domain_kernel.ontology import Ontology
from ontology import load as load_ontology
from py_common.app import create_app
from qa import __version__
from qa.api.router import router
from qa.application.answerer import Answerer
from qa.application.ask import AskQuestion
from qa.application.kag import KagLayer
from qa.application.planner import Planner
from qa.application.retrieval import HybridLayer
from qa.application.solver import Solver
from qa.application.structured import StructuredLayer
from qa.domain.errors import (
    BusinessNotFoundError,
    DependencyUnavailableError,
    ModelBudgetExceededError,
    QaTenantRequiredError,
    QuestionInvalidError,
)
from qa.domain.flags import KagTargeting
from qa.domain.records import INDIA
from qa.infrastructure.gateway import GatewayProvider, HttpEmbedder
from qa.infrastructure.obligation_client import HttpObligations
from qa.infrastructure.profile_client import HttpProfiles
from qa.infrastructure.prompts import PROMPTS_DIR, load_prompt
from qa.infrastructure.rulebook_client import HttpRulebook
from qa.infrastructure.tracing import OtelTracer
from qa.settings import QaSettings
from qa.wiring import Ports, Wiring

SERVICE_NAME = "qa"
PLAN_PROMPT = ("qa.plan", "1")
ANSWER_PROMPT = ("qa.answer", "1")
PROBLEM_STATUS: dict[type[DomainError], int] = {
    QaTenantRequiredError: 401,
    BusinessNotFoundError: 404,
    QuestionInvalidError: 422,
    ModelBudgetExceededError: 429,
    DependencyUnavailableError: 503,
}


def http_ports(settings: QaSettings) -> Ports:
    reads = settings.qa_http_timeout_seconds
    completions = settings.qa_llm_timeout_seconds
    embeddings = settings.qa_embedding_timeout_seconds
    rulebook = HttpRulebook(settings.rulebook_url, timeout_seconds=reads)
    return Ports(
        rulebook=rulebook,
        search=rulebook,
        profiles=HttpProfiles(settings.profile_url, timeout_seconds=reads),
        obligations=HttpObligations(settings.obligation_url, timeout_seconds=reads),
        embedder=HttpEmbedder(settings.llm_gateway_url, timeout_seconds=embeddings),
        provider=GatewayProvider(settings.llm_gateway_url, timeout_seconds=completions),
        tracer=OtelTracer(),
    )


def wire(
    settings: QaSettings, ports: Ports | None = None, ontology: Ontology | None = None
) -> Wiring:
    ports = ports or http_ports(settings)
    ontology = ontology or load_ontology()
    directory = settings.qa_prompts_dir or PROMPTS_DIR
    answerer = Answerer(ports.provider, load_prompt(*ANSWER_PROMPT, directory))
    planner = Planner(ports.provider, load_prompt(*PLAN_PROMPT, directory))
    solver = Solver(
        rulebook=ports.rulebook,
        search=ports.search,
        embedder=ports.embedder,
        obligations=ports.obligations,
        ontology=ontology,
        tracer=ports.tracer,
    )
    targeting = KagTargeting(
        enabled=settings.qa_kag_enabled,
        tenants=frozenset(TenantId(tenant) for tenant in settings.qa_kag_tenants),
    )
    ask = AskQuestion(
        rulebook=ports.rulebook,
        profiles=ports.profiles,
        structured=StructuredLayer(ports.rulebook, ports.obligations),
        kag=KagLayer(planner, solver, answerer),
        hybrid=HybridLayer(ports.search, ports.embedder, answerer, ports.tracer),
        targeting=targeting,
        tracer=ports.tracer,
    )

    async def prompts_ready() -> bool:
        return await run_in_threadpool(_prompts_load, directory)

    return Wiring(settings=settings, ask=ask, prompts_ready=prompts_ready, today=_today_in_india)


def _prompts_load(directory: Path) -> bool:
    try:
        load_prompt(*PLAN_PROMPT, directory)
        load_prompt(*ANSWER_PROMPT, directory)
    except (OSError, ValueError):
        return False
    return True


def _today_in_india() -> date:
    return datetime.now(INDIA).date()


def build_app(
    settings: QaSettings | None = None,
    *,
    ports: Ports | None = None,
    ontology: Ontology | None = None,
) -> FastAPI:
    settings = settings or QaSettings(service_name=SERVICE_NAME)
    wiring = wire(settings, ports, ontology)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("prompts", wiring.prompts_ready)],
        problem_status=PROBLEM_STATUS,
    )
    app.state.wiring = wiring
    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("qa.main:app", host="127.0.0.1", port=8007, reload=True)
