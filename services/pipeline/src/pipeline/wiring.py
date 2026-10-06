"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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
from pipeline.domain.ports import AdapterTypes
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.settings import PipelineSettings


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: PipelineSettings
    units: UnitOfWorkFactory
    adapter_types: AdapterTypes
    store_ready: Callable[[], Awaitable[bool]]
    sync_sources: SyncSources
    list_sources: ListSources
    add_source: AddSource
    edit_source: EditSource
    start_crawl: StartCrawl
    list_documents: ListSourceDocuments
    read_document: ReadDocument
    read_raw: ReadRawDocument
