"""The pipeline worker: ``python -m pipeline.worker`` (locally ``make worker SERVICE=pipeline``).

Registers the ingest workflow and its activities on the ``pipeline`` task queue against
``CW_TEMPORAL_ADDRESS``. Activities run on the in-memory fakes until the source adapters land.
Registration with the rulebook, clause embedding and knowledge extraction are wired to
``CW_RULEBOOK_URL`` and ``CW_LLM_GATEWAY_URL`` and only call them when
``CW_PIPELINE_KNOWLEDGE_ENABLED`` is on. Both clients carry the worker's own access token once
``CW_SERVICE_CLIENT_SECRET`` is set (client ``CW_SERVICE_CLIENT_ID``, which needs rulebook:write
and llm:call), and the rulebook's writes also carry ``CW_RULEBOOK_WRITE_TOKEN`` while it is set.

``components(settings)`` is what the worker runs (``py_common.runtime.WorkerComponents``): one
Temporal worker on the ``pipeline`` task queue with ``WORKFLOWS`` and ``activities(settings)``.
A process that hosts several services adds it to its own.
"""

from typing import Any, Final, Protocol

from pipeline import __version__
from pipeline.application.activities import DiscoverDocument, FetchDocument, ParseDocument
from pipeline.application.embedding import EmbeddingStage
from pipeline.application.knowledge_activities import (
    EmbedClauses,
    ExtractMentions,
    ProposeRelations,
    RegisterDocument,
    SubmitRelations,
)
from pipeline.application.relations import LlmRelationExtractor, RelationStage
from pipeline.domain.ports import ClauseIndexSink, Embedder, KnowledgeSink, RulebookReader
from pipeline.infrastructure.fakes import FakePlainTextParser, FakeSourceAdapter
from pipeline.infrastructure.gateway import GatewayEmbedder, GatewayProvider
from pipeline.infrastructure.prompts import PROMPTS_DIR, load_prompt
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.settings import PipelineSettings
from pipeline.workflows import TASK_QUEUE, ExtractKnowledgeWorkflow, IngestDocumentWorkflow
from py_common.auth import service_auth_from
from py_common.runtime import TemporalComponent, WorkerComponents, run_worker_process
from py_common.temporal import ActivityBase, WorkerConfig

SERVICE_NAME = "pipeline-worker"
WORKFLOWS: Final[tuple[type[Any], ...]] = (IngestDocumentWorkflow, ExtractKnowledgeWorkflow)


class Rulebook(KnowledgeSink, RulebookReader, ClauseIndexSink, Protocol):
    """The rulebook as the sink, the reader and the search index, the way ``HttpRulebook`` is."""


def activities(
    settings: PipelineSettings | None = None,
    *,
    sink: Rulebook | None = None,
    stage: RelationStage | None = None,
    embedder: Embedder | None = None,
) -> list[ActivityBase[Any, Any]]:
    """The worker's activities. ``sink`` replaces the rulebook client, ``stage`` the relation
    stage and ``embedder`` the gateway's embeddings (tests pass memory ones)."""
    settings = settings or PipelineSettings(_env_file=None, service_name=SERVICE_NAME)
    adapter = FakeSourceAdapter.with_sample()
    parser = FakePlainTextParser()
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
    return [
        DiscoverDocument(adapter),
        FetchDocument(adapter),
        ParseDocument(parser),
        RegisterDocument(parser, rulebook, enabled=enabled),
        EmbedClauses(embedding, enabled=enabled),
        ExtractMentions(rulebook, rulebook, enabled=enabled),
        ProposeRelations(rulebook, relations, enabled=enabled),
        SubmitRelations(rulebook, enabled=enabled),
    ]


def components(settings: PipelineSettings) -> WorkerComponents:
    """The Temporal worker of the ``pipeline`` task queue: every workflow and activity. Its
    activities record what they fetch in Postgres, so it needs ``CW_PIPELINE_STORE=postgres``."""
    if settings.pipeline_store != "postgres":
        raise ValueError("the pipeline worker needs CW_PIPELINE_STORE=postgres")
    return WorkerComponents(
        temporal=(
            TemporalComponent(WorkerConfig(task_queue=TASK_QUEUE), WORKFLOWS, activities(settings)),
        )
    )


def main() -> None:
    run_worker_process(PipelineSettings(service_name=SERVICE_NAME), components, version=__version__)


if __name__ == "__main__":
    main()
