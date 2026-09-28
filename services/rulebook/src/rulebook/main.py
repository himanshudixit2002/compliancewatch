"""Composition root for the rulebook service.

Guide section 11: wiring of interfaces to implementations happens here, never inside the layers.
The engine behind the Postgres store connects lazily, so importing the module (``make openapi``)
needs no database.
"""

from collections.abc import Callable

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from domain_kernel.errors import DomainError
from py_common.app import create_app
from rulebook import __version__
from rulebook.api.router import router
from rulebook.application.documents import ReadDocument, RegisterDocument
from rulebook.domain.errors import (
    DocumentConflictError,
    DocumentIdMismatchError,
    UnknownDocumentError,
    WritesDisabledError,
    WriteTokenInvalidError,
)
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.infrastructure.knowledge_repository import PostgresKnowledgeUnitOfWorkFactory
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.settings import RulebookSettings
from rulebook.wiring import Wiring

SERVICE_NAME = "rulebook"

PROBLEM_STATUS: dict[type[DomainError], int] = {
    DocumentIdMismatchError: 422,
    DocumentConflictError: 409,
    UnknownDocumentError: 404,
    WriteTokenInvalidError: 401,
    WritesDisabledError: 503,
}


def build_wiring(settings: RulebookSettings) -> Wiring:
    unit_of_work: KnowledgeUnitOfWorkFactory
    ping: Callable[[], bool]
    if settings.rulebook_store == "memory":
        memory = MemoryKnowledgeStore()
        unit_of_work, ping = memory, memory.ping
    else:
        postgres = PostgresKnowledgeUnitOfWorkFactory.from_url(settings.database_url)
        unit_of_work, ping = postgres, postgres.ping

    async def store_ready() -> bool:
        return await run_in_threadpool(ping)

    return Wiring(
        settings=settings,
        unit_of_work=unit_of_work,
        store_ready=store_ready,
        register_document=RegisterDocument(unit_of_work),
        read_document=ReadDocument(unit_of_work),
    )


def build_app(settings: RulebookSettings | None = None) -> FastAPI:
    settings = settings or RulebookSettings(service_name=SERVICE_NAME)
    wiring = build_wiring(settings)
    app = create_app(
        service_name=SERVICE_NAME,
        version=__version__,
        routers=[router],
        settings=settings,
        readiness_checks=[("store", wiring.store_ready)],
        problem_status=PROBLEM_STATUS,
    )
    app.state.wiring = wiring
    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("rulebook.main:app", host="127.0.0.1", port=8003, reload=True)
