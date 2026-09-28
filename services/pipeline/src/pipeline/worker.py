"""The pipeline worker: ``python -m pipeline.worker`` (locally ``make worker SERVICE=pipeline``).

Registers the ingest workflow and its activities on the ``pipeline`` task queue against
``CW_TEMPORAL_ADDRESS``. Activities run on the in-memory fakes until the source adapters land.
Registration with the rulebook, clause embedding and knowledge extraction are wired to
``CW_RULEBOOK_URL`` and ``CW_LLM_GATEWAY_URL`` and only call them when
``CW_PIPELINE_KNOWLEDGE_ENABLED`` is on.
"""

import asyncio
from typing import Any, Protocol

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
from py_common.logging import configure_logging
from py_common.telemetry import configure_telemetry
from py_common.temporal import ActivityBase, WorkerConfig, run_worker

SERVICE_NAME = "pipeline-worker"


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
    token = settings.rulebook_write_token
    rulebook: Rulebook = sink or HttpRulebook(
        settings.rulebook_url, token=None if token is None else token.get_secret_value()
    )
    enabled = settings.pipeline_knowledge_enabled
    relations = stage
    if relations is None and enabled:
        prompt = load_prompt(
            "extraction.rule_relations", "1", settings.pipeline_prompts_dir or PROMPTS_DIR
        )
        relations = RelationStage(
            LlmRelationExtractor(GatewayProvider(settings.llm_gateway_url), prompt)
        )
    embedding = None
    if enabled:
        embedding = EmbeddingStage(embedder or GatewayEmbedder(settings.llm_gateway_url), rulebook)
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


async def serve(settings: PipelineSettings) -> None:
    telemetry = configure_telemetry(
        service_name=SERVICE_NAME, version=__version__, settings=settings
    )
    try:
        await run_worker(
            settings,
            WorkerConfig(task_queue=TASK_QUEUE),
            workflows=[IngestDocumentWorkflow, ExtractKnowledgeWorkflow],
            activities=activities(settings),
        )
    finally:
        telemetry.shutdown()


def main() -> None:
    settings = PipelineSettings(service_name=SERVICE_NAME)
    configure_logging(
        service_name=SERVICE_NAME, log_level=settings.log_level, json_output=settings.log_json
    )
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
