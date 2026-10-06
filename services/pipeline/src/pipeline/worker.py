"""The pipeline worker: ``python -m pipeline.worker`` (locally ``make worker SERVICE=pipeline``).

Registers the crawl, ingest, extraction and backlog workflows and their activities on the
``pipeline`` task queue against ``CW_TEMPORAL_ADDRESS``. The activities read the sources the
store holds (``StoreCatalog``: each adapter built from its row's adapter type and parameters)
over one polite client, parse each document through the parser chain as its source's document
type (``ParserChain``: text-layer PDF, table-aware PDF, HTML, table-aware HTML), keep the
fetched files in the raw store ``CW_PIPELINE_RAW_STORE`` names and record them, with their
document.discovered, in the store ``CW_PIPELINE_STORE`` names, which must be postgres:
``pipeline.stores``. The outbox relay that publishes the events runs on its own
(``make relay SERVICE=pipeline``), or in the combined worker.

When it starts, the worker adds the built-in sources the store lacks (``SyncSources``, a startup
hook). With ``CW_PIPELINE_CRAWL_ENABLED`` on it also runs the crawl's tick every 60 seconds
(``pipeline-crawl-tick``, ``ScheduleCrawls``): a crawl of every enabled, unpaused source whose
cadence has passed, started on Temporal under an id per source and cadence slot.

Registration with the rulebook, clause embedding and knowledge extraction are wired to
``CW_RULEBOOK_URL`` and ``CW_LLM_GATEWAY_URL`` and only call them when
``CW_PIPELINE_KNOWLEDGE_ENABLED`` is on; the rule extraction (``pipeline.extract_rules``, the
registered prompt ``extraction.rule_candidate@1``) only when ``CW_PIPELINE_EXTRACTION_ENABLED`` is
on, which is also when the worker reads that prompt. Both clients carry the worker's own access
token once ``CW_SERVICE_CLIENT_SECRET`` is set (client ``CW_SERVICE_CLIENT_ID``, which needs
rulebook:write and llm:call), and the rulebook's writes also carry ``CW_RULEBOOK_WRITE_TOKEN`` while
it is set.

``components(settings)`` is what the worker runs (``py_common.runtime.WorkerComponents``): one
Temporal worker on the ``pipeline`` task queue with ``WORKFLOWS`` and ``activities(settings)``,
the source sync at start, and the tick while crawling is on. A process that hosts several
services adds them to its own.
"""

from collections.abc import Callable
from typing import Any, Final, Protocol

from ontology import load as load_ontology
from pipeline import __version__
from pipeline.application.activities import (
    DiscoverDocument,
    FetchAndStore,
    FetchDocument,
    OpenManualParse,
    ParseDocument,
)
from pipeline.application.classify import ClassifyDocument
from pipeline.application.crawl import FinishCrawl, ListNewDocuments, ScheduleCrawls
from pipeline.application.embedding import EmbeddingStage
from pipeline.application.extraction import (
    RULE_PROMPT,
    ExtractRules,
    RuleExtractionStage,
    StoreExtraction,
)
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.application.knowledge_activities import (
    EmbedClauses,
    ExtractMentions,
    ProposeRelations,
    RegisterDocument,
    SubmitRelations,
)
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.application.sources import SyncSources
from pipeline.application.store_document import StoreDocument
from pipeline.domain.ports import (
    ClauseIndexSink,
    CrawlStarter,
    DocumentParsers,
    Embedder,
    KnowledgeSink,
    RawStore,
    RulebookReader,
    SourceCatalog,
)
from pipeline.domain.repository import UnitOfWorkFactory
from pipeline.infrastructure.adapters import SOURCES, RegistryAdapterTypes, StoreCatalog
from pipeline.infrastructure.gateway import GatewayEmbedder, GatewayProvider
from pipeline.infrastructure.http import PoliteClient
from pipeline.infrastructure.parsers import ParserChain
from pipeline.infrastructure.prompts import PROMPTS_DIR, load_prompt
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.infrastructure.temporal import TemporalCrawls
from pipeline.settings import PipelineSettings
from pipeline.stores import raw_store_of, unit_of_work_of
from pipeline.workflows import (
    TASK_QUEUE,
    CrawlSourceWorkflow,
    ExtractBacklogWorkflow,
    ExtractKnowledgeWorkflow,
    ExtractRulesWorkflow,
    IngestDocumentWorkflow,
)
from py_common.auth import service_auth_from
from py_common.runtime import (
    LifecycleHook,
    PeriodicComponent,
    TemporalComponent,
    WorkerComponents,
    run_worker_process,
)
from py_common.temporal import ActivityBase, WorkerConfig

SERVICE_NAME = "pipeline-worker"
WORKFLOWS: Final[tuple[type[Any], ...]] = (
    IngestDocumentWorkflow,
    ExtractKnowledgeWorkflow,
    ExtractRulesWorkflow,
    CrawlSourceWorkflow,
    ExtractBacklogWorkflow,
)
TICK_JOB: Final = "pipeline-crawl-tick"
TICK_SECONDS: Final = 60.0
SYNC_HOOK: Final = "pipeline-sources-sync"


class Rulebook(KnowledgeSink, RulebookReader, ClauseIndexSink, Protocol):
    """The rulebook as the sink, the reader and the search index, the way ``HttpRulebook`` is."""


def activities(
    settings: PipelineSettings | None = None,
    *,
    sink: Rulebook | None = None,
    stage: RelationStage | None = None,
    embedder: Embedder | None = None,
    sources: SourceCatalog | None = None,
    parser: DocumentParsers | None = None,
    units: UnitOfWorkFactory | None = None,
    raw_store: RawStore | None = None,
    extraction: RuleExtractionStage | None = None,
) -> list[ActivityBase[Any, Any]]:
    """The worker's activities. The keywords replace what the settings would build: ``sink``
    the rulebook client, ``stage`` the relation stage, ``embedder`` the gateway's embeddings,
    ``sources`` the store's sources, ``parser`` the parser chain, ``units`` the store,
    ``raw_store`` the raw store and ``extraction`` the rule extraction's stage (tests pass memory
    ones, the sample source and scripted models)."""
    settings = settings or PipelineSettings(_env_file=None, service_name=SERVICE_NAME)
    records = units or unit_of_work_of(settings)
    catalog = sources or StoreCatalog(records, PoliteClient())
    parsers = parser or ParserChain(catalog)
    raw = raw_store or raw_store_of(settings)
    store = StoreDocument(catalog, records, raw)
    auth = service_auth_from(settings)
    token = settings.rulebook_write_token
    rulebook: Rulebook = sink or HttpRulebook(
        settings.rulebook_url,
        token=None if token is None else token.get_secret_value(),
        auth=auth,
    )
    enabled = settings.pipeline_knowledge_enabled
    relations = stage
    if relations is None and enabled:
        prompt = load_prompt(
            "extraction.rule_relations", "1", settings.pipeline_prompts_dir or PROMPTS_DIR
        )
        relations = RelationStage(
            LlmRelationExtractor(GatewayProvider(settings.llm_gateway_url, auth=auth), prompt)
        )
    embedding = None
    if enabled:
        embedding = EmbeddingStage(
            embedder or GatewayEmbedder(settings.llm_gateway_url, auth=auth), rulebook
        )
    extracting = settings.pipeline_extraction_enabled
    rules = extraction
    if rules is None and extracting:
        prompt = load_prompt(*RULE_PROMPT, settings.pipeline_prompts_dir or PROMPTS_DIR)
        rules = RuleExtractionStage(
            LlmRuleExtractor(
                GatewayProvider(settings.llm_gateway_url, auth=auth), prompt, load_ontology()
            )
        )
    return [
        DiscoverDocument(catalog),
        FetchDocument(catalog),
        FetchAndStore(store),
        ParseDocument(parsers, raw, units=records),
        OpenManualParse(records),
        ClassifyDocument(parsers, raw, records, extraction=settings.pipeline_extraction_enabled),
        RegisterDocument(parsers, rulebook, enabled=enabled, raw_store=raw, units=records),
        EmbedClauses(embedding, enabled=enabled),
        ExtractMentions(rulebook, rulebook, enabled=enabled),
        ProposeRelations(rulebook, relations, enabled=enabled),
        SubmitRelations(rulebook, enabled=enabled),
        ExtractRules(rulebook, rules, records, enabled=extracting),
        StoreExtraction(records),
        ListNewDocuments(records, catalog, knowledge=enabled),
        FinishCrawl(records),
    ]


def tick_job(schedule: ScheduleCrawls) -> Callable[[], None]:
    """One tick: a crawl of every source that is due."""

    def run() -> None:
        schedule.run()

    return run


def components(
    settings: PipelineSettings,
    *,
    units: UnitOfWorkFactory | None = None,
    starter: CrawlStarter | None = None,
) -> WorkerComponents:
    """The Temporal worker of the ``pipeline`` task queue (every workflow and activity), the
    sync of the built-in sources at start, and, while ``CW_PIPELINE_CRAWL_ENABLED`` is on, the
    crawl's 60-second tick. Its activities record what they fetch in Postgres, so it needs
    ``CW_PIPELINE_STORE=postgres``; ``units`` and ``starter`` replace the store and the Temporal
    starter in tests."""
    if settings.pipeline_store != "postgres":
        raise ValueError("the pipeline worker needs CW_PIPELINE_STORE=postgres")
    records = units or unit_of_work_of(settings)
    sync = SyncSources(records, [spec.definition() for spec in SOURCES.values()])
    periodic: tuple[PeriodicComponent, ...] = ()
    if settings.pipeline_crawl_enabled:
        schedule = ScheduleCrawls(
            records,
            starter or TemporalCrawls(settings),
            types=RegistryAdapterTypes(),
            enabled=True,
        )
        periodic = (PeriodicComponent(TICK_JOB, tick_job(schedule), interval_seconds=TICK_SECONDS),)
    return WorkerComponents(
        periodic=periodic,
        temporal=(
            TemporalComponent(
                WorkerConfig(task_queue=TASK_QUEUE),
                WORKFLOWS,
                activities(settings, units=records),
            ),
        ),
        startup=(LifecycleHook(SYNC_HOOK, sync.run),),
    )


def main() -> None:
    run_worker_process(PipelineSettings(service_name=SERVICE_NAME), components, version=__version__)


if __name__ == "__main__":
    main()
