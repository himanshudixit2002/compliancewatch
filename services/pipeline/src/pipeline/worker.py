"""The pipeline worker: ``python -m pipeline.worker`` (locally ``make worker SERVICE=pipeline``).

Registers the ingest workflow and its activities on the ``pipeline`` task queue against
``CW_TEMPORAL_ADDRESS``. Activities run on the in-memory fakes until the source adapters land.
Registration with the rulebook is wired to ``CW_RULEBOOK_URL`` and only calls it when
``CW_PIPELINE_KNOWLEDGE_ENABLED`` is on.
"""

import asyncio
from typing import Any

from pipeline import __version__
from pipeline.application.activities import DiscoverDocument, FetchDocument, ParseDocument
from pipeline.application.knowledge_activities import RegisterDocument
from pipeline.domain.ports import KnowledgeSink
from pipeline.infrastructure.fakes import FakePlainTextParser, FakeSourceAdapter
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.settings import PipelineSettings
from pipeline.workflows import TASK_QUEUE, IngestDocumentWorkflow
from py_common.logging import configure_logging
from py_common.telemetry import configure_telemetry
from py_common.temporal import ActivityBase, WorkerConfig, run_worker

SERVICE_NAME = "pipeline-worker"


def activities(
    settings: PipelineSettings | None = None, *, sink: KnowledgeSink | None = None
) -> list[ActivityBase[Any, Any]]:
    """The worker's activities. ``sink`` replaces the rulebook client (tests pass a memory one)."""
    settings = settings or PipelineSettings(_env_file=None, service_name=SERVICE_NAME)
    adapter = FakeSourceAdapter.with_sample()
    parser = FakePlainTextParser()
    token = settings.rulebook_write_token
    rulebook = sink or HttpRulebook(
        settings.rulebook_url, token=None if token is None else token.get_secret_value()
    )
    return [
        DiscoverDocument(adapter),
        FetchDocument(adapter),
        ParseDocument(parser),
        RegisterDocument(parser, rulebook, enabled=settings.pipeline_knowledge_enabled),
    ]


async def serve(settings: PipelineSettings) -> None:
    telemetry = configure_telemetry(
        service_name=SERVICE_NAME, version=__version__, settings=settings
    )
    try:
        await run_worker(
            settings,
            WorkerConfig(task_queue=TASK_QUEUE),
            workflows=[IngestDocumentWorkflow],
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
