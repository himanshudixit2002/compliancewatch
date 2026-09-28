"""Composition root of the llm-gateway service: settings in, wired app out.

Interfaces meet their implementations here and nowhere inside the layers.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError
from domain_kernel.protocols import LLMProvider
from llm_gateway import __version__
from llm_gateway.api.router import router
from llm_gateway.application.complete import Complete
from llm_gateway.application.embed import Embed
from llm_gateway.application.metering import BudgetGuard
from llm_gateway.application.usage import Usage
from llm_gateway.domain.breaker import CircuitBreaker
from llm_gateway.domain.budgets import BudgetLimits
from llm_gateway.domain.cache import ResponseCache
from llm_gateway.domain.config import GatewayConfig
from llm_gateway.domain.embeddings import EmbeddingProvider
from llm_gateway.domain.errors import (
    BudgetExceededError,
    FeatureMismatchError,
    ProviderResponseError,
    ProviderUnavailableError,
    UnknownFeatureError,
    UnknownPromptError,
)
from llm_gateway.domain.routing import RoutingTable
from llm_gateway.domain.tracing import Tracer
from llm_gateway.infrastructure.cache.memory import MemoryCache
from llm_gateway.infrastructure.events.log import LogPublisher
from llm_gateway.infrastructure.ledger.memory import MemoryLedger
from llm_gateway.infrastructure.ledger.sqlalchemy import SqlAlchemyLedger
from llm_gateway.infrastructure.prompts.toml import TomlPromptRegistry
from llm_gateway.infrastructure.providers.fake import FakeProvider
from llm_gateway.infrastructure.providers.vercel import VercelGatewayProvider
from llm_gateway.infrastructure.tracing.composite import CompositeTracer
from llm_gateway.infrastructure.tracing.langfuse import LangfuseTracer
from llm_gateway.infrastructure.tracing.log import LogTracer
from llm_gateway.settings import GatewaySettings
from llm_gateway.wiring import GatewayWiring
from py_common.app import create_app
from py_common.logging import get_logger

SERVICE_NAME = "llm-gateway"
VERCEL_CLIENT_TIMEOUT_SECONDS = 60.0
"""The SDK client's default; every call overrides it with its route's timeout."""
PROBLEM_STATUS: Mapping[type[DomainError], int] = {
    BudgetExceededError: 429,
    ProviderUnavailableError: 503,
    ProviderResponseError: 502,
    UnknownPromptError: 422,
    UnknownFeatureError: 422,
    FeatureMismatchError: 422,
}
log = get_logger(__name__)


def wire(settings: GatewaySettings) -> GatewayWiring:
    """Build every adapter and use case from settings. Fails fast on a bad route override."""
    routing = RoutingTable.default().with_overrides(settings.llm_routes)
    registry = TomlPromptRegistry.load(settings.llm_prompt_registry_path)
    config = GatewayConfig(
        routes=routing.mapping,
        budgets=BudgetLimits(
            settings.llm_tenant_monthly_budget_inr,
            settings.llm_feature_monthly_budget_inr,
            Decimal(str(settings.llm_budget_alarm_ratio)),
        ),
        usd_inr=settings.llm_usd_inr,
        allow_unregistered_prompts=settings.llm_allow_unregistered_prompts,
    )

    fake = FakeProvider()
    providers: dict[str, LLMProvider] = {"fake": fake}
    embedders: dict[str, EmbeddingProvider] = {"fake": fake}
    if settings.llm_provider == "fake":
        # Every route, whatever model it names, is served in process.
        providers["vercel"] = fake
        embedders["vercel"] = fake
    else:
        api_key = settings.ai_gateway_api_key
        if api_key is None:  # settings validation refuses this before wiring
            raise ValueError("CW_AI_GATEWAY_API_KEY is required when CW_LLM_PROVIDER=vercel")
        vercel = VercelGatewayProvider.from_settings(
            base_url=settings.ai_gateway_base_url,
            api_key=api_key.get_secret_value(),
            timeout=VERCEL_CLIENT_TIMEOUT_SECONDS,
            max_retries=settings.ai_gateway_max_retries,
            routes=routing.mapping,
            zero_data_retention=settings.ai_gateway_zero_data_retention,
            embedding_dimensions_param=settings.llm_embedding_dimensions_param,
        )
        providers["vercel"] = vercel
        embedders["vercel"] = vercel

    ledger: MemoryLedger | SqlAlchemyLedger = (
        MemoryLedger()
        if settings.llm_ledger == "memory"
        else SqlAlchemyLedger.from_url(settings.database_url)
    )

    tracers: list[Tracer] = [LogTracer()]
    langfuse = _langfuse_keys(settings)
    if langfuse is not None:
        host, public_key, secret_key = langfuse
        tracers.append(
            LangfuseTracer.from_keys(
                public_key=public_key, secret_key=secret_key, host=host, environment=settings.env
            )
        )
    tracer = CompositeTracer(tracers)

    cache: ResponseCache | None = (
        MemoryCache(
            ttl_seconds=settings.llm_cache_ttl_seconds, max_entries=settings.llm_cache_max_entries
        )
        if settings.llm_cache_ttl_seconds > 0
        else None
    )
    # One breaker and one budget guard for both use cases: a model's circuit is the same
    # whichever route calls it, and a budget alarm fires once per scope and month.
    publisher = LogPublisher()
    breaker = CircuitBreaker(
        threshold=settings.llm_breaker_threshold, open_seconds=settings.llm_breaker_open_seconds
    )
    budgets = BudgetGuard(ledger=ledger, publisher=publisher, config=config)
    complete = Complete(
        registry=registry,
        providers=providers,
        breaker=breaker,
        budgets=budgets,
        cache=cache,
        ledger=ledger,
        tracer=tracer,
        publisher=publisher,
        config=config,
    )
    embed = Embed(
        providers=embedders,
        breaker=breaker,
        budgets=budgets,
        ledger=ledger,
        tracer=tracer,
        publisher=publisher,
        config=config,
    )
    usage = Usage(ledger=ledger, config=config)

    return GatewayWiring(
        settings=settings,
        providers=providers,
        embedders=embedders,
        ledger=ledger,
        registry=registry,
        routing=routing,
        complete=complete,
        embed=embed,
        usage=usage,
        checks=(
            ("ledger", ledger.ping),
            ("prompt_registry", lambda: len(registry.list()) > 0),
            ("provider", lambda: settings.llm_provider in providers),
        ),
        close=tracer.flush,
    )


def build_app(settings: GatewaySettings | None = None) -> FastAPI:
    settings = settings or GatewaySettings(service_name=SERVICE_NAME)
    wiring = wire(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            wiring.close()

    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[(name, _threaded(check)) for name, check in wiring.checks],
        lifespan=lifespan,
        problem_status=PROBLEM_STATUS,
    )
    app.state.gateway = wiring
    # After create_app, which configures logging: the line is JSON and carries the service field.
    log.info(
        "gateway_wired",
        provider=settings.llm_provider,
        ledger=settings.llm_ledger,
        cache=settings.llm_cache_ttl_seconds > 0,
        langfuse=_langfuse_keys(settings) is not None,
        prompts=len(wiring.registry.list()),
        routes=len(wiring.routing.routes()),
        providers=len(wiring.providers),
    )
    return app


def _langfuse_keys(settings: GatewaySettings) -> tuple[str, str, str] | None:
    """Host, public key and secret key when all three are set; Langfuse is off otherwise."""
    host, public_key, secret = (
        settings.langfuse_host,
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
    )
    if host and public_key and secret:
        return host, public_key, secret.get_secret_value()
    return None


def _threaded(check: Callable[[], bool]) -> Callable[[], Awaitable[bool]]:
    async def run() -> bool:
        return await run_in_threadpool(check)

    return run


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("llm_gateway.main:app", host="127.0.0.1", port=8008, reload=True)
