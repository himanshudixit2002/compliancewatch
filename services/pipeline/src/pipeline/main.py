"""Composition root for the pipeline service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The store picked by ``CW_PIPELINE_STORE`` connects lazily, so importing the module
(``make openapi``) needs no database. The built-in sources are added to the store the app reads:
at once on the memory store, and when the app starts on Postgres (a failure there is logged and
the app serves all the same; the worker adds them too). With telemetry and crawling on, each
source's freshness gauges are registered on the app's meter provider.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError
from domain_kernel.events import utc_now
from pipeline import __version__
from pipeline.api.router import router
from pipeline.api.sources import router as sources_router
from pipeline.application.crawl import StartCrawl
from pipeline.application.sources import (
    AddSource,
    EditSource,
    ListSourceDocuments,
    ListSources,
    ReadDocument,
    ReadRawDocument,
    SyncSources,
)
from pipeline.domain.errors import (
    CrawlDisabledError,
    CrawlRunningError,
    CrawlUnavailableError,
    DocumentNotFoundError,
    RawDocumentUnreadableError,
    RawStoreUnavailableError,
    SourceExistsError,
    SourceInvalidError,
    SourceNotFoundError,
    WritesDisabledError,
    WriteTokenInvalidError,
)
from pipeline.domain.ports import AdapterTypes, CrawlStarter, RawStore
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.domain.sources import Source
from pipeline.infrastructure.adapters import SOURCES, RegistryAdapterTypes
from pipeline.infrastructure.memory import MemoryStore
from pipeline.infrastructure.source_metrics import register_source_gauges
from pipeline.infrastructure.temporal import TemporalCrawls
from pipeline.settings import PipelineSettings
from pipeline.stores import ping_of, raw_store_of, unit_of_work_of
from pipeline.wiring import Wiring
from py_common.app import create_app, module_app
from py_common.auth.fastapi import Authenticator
from py_common.logging import get_logger
from py_common.telemetry import Telemetry

SERVICE_NAME = "pipeline"

log = get_logger(__name__)

PROBLEM_STATUS: dict[type[DomainError], int] = {
    SourceNotFoundError: 404,
    SourceExistsError: 409,
    SourceInvalidError: 422,
    DocumentNotFoundError: 404,
    RawDocumentUnreadableError: 502,
    RawStoreUnavailableError: 503,
    CrawlDisabledError: 503,
    CrawlRunningError: 409,
    CrawlUnavailableError: 503,
    WriteTokenInvalidError: 401,
    WritesDisabledError: 503,
}


def build_wiring(
    settings: PipelineSettings,
    *,
    units: UnitOfWorkFactory | None = None,
    raw_store: RawStore | None = None,
    starter: CrawlStarter | None = None,
    adapter_types: AdapterTypes | None = None,
) -> Wiring:
    """The use cases on the stores the settings pick; the keywords replace them (tests pass
    memory ones, a recording starter and adapter types with a recorded one)."""
    store = units or unit_of_work_of(settings)
    ping: Callable[[], bool] = ping_of(store)
    types = adapter_types or RegistryAdapterTypes()
    raw = raw_store or raw_store_of(settings)

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        units=store,
        store_ready=store_ready,
        sync_sources=SyncSources(store, [spec.definition() for spec in SOURCES.values()]),
        list_sources=ListSources(store, types),
        add_source=AddSource(store, types),
        edit_source=EditSource(store, types),
        start_crawl=StartCrawl(
            store, starter or TemporalCrawls(settings), enabled=settings.pipeline_crawl_enabled
        ),
        list_documents=ListSourceDocuments(store),
        read_document=ReadDocument(store),
        read_raw=ReadRawDocument(store, raw),
    )


def sync_sources(wiring: Wiring) -> bool:
    """Add the built-in sources the store lacks; whether it could."""
    try:
        wiring.sync_sources.run()
    except Exception as exc:
        log.warning("pipeline.sources_sync_failed", error=f"{type(exc).__name__}: {exc}")
        return False
    return True


def install_source_metrics(app: FastAPI, wiring: Wiring) -> bool:
    """Register the freshness gauges when telemetry and crawling are on; whether it did."""
    telemetry: Telemetry = app.state.telemetry
    if not (telemetry.enabled and telemetry.meter_provider is not None):
        return False
    if not wiring.settings.pipeline_crawl_enabled:
        return False

    def read() -> list[Source]:
        with wiring.units() as unit:
            return list(unit.sources.list())

    register_source_gauges(
        read,
        utc_now,
        telemetry.meter_provider.get_meter(SERVICE_NAME, __version__),
    )
    return True


def build_app(
    settings: PipelineSettings | None = None,
    *,
    authenticator: Authenticator | None = None,
    units: UnitOfWorkFactory | None = None,
    raw_store: RawStore | None = None,
    starter: CrawlStarter | None = None,
    adapter_types: AdapterTypes | None = None,
) -> FastAPI:
    """``authenticator`` replaces the one ``CW_AUTH_MODE`` describes; a process that hosts
    identity passes identity's own. The other keywords replace the stores, the Temporal starter
    and the adapter types (``build_wiring``)."""
    settings = settings or PipelineSettings(service_name=SERVICE_NAME)
    wiring = build_wiring(
        settings, units=units, raw_store=raw_store, starter=starter, adapter_types=adapter_types
    )
    in_memory = isinstance(wiring.units, MemoryStore)
    if in_memory:
        sync_sources(wiring)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not in_memory:
            await run_in_threadpool(sync_sources, wiring)
        yield

    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router, sources_router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        lifespan=lifespan,
        problem_status=PROBLEM_STATUS,
        authenticator=authenticator,
    )
    app.state.wiring = wiring
    install_source_metrics(app, wiring)
    return app


def __getattr__(name: str) -> FastAPI:
    """``app`` is built on first access, so importing this module builds nothing."""
    return module_app(name, build_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pipeline.main:app", host="127.0.0.1", port=8010, reload=True)
