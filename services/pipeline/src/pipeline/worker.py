"""The pipeline worker: ``python -m pipeline.worker`` (locally ``make worker SERVICE=pipeline``).

Registers the ingest workflow and its activities on the ``pipeline`` task queue against
``CW_TEMPORAL_ADDRESS``. Activities run on the in-memory fakes until the source adapters land.
"""

import asyncio
from typing import Any

from pipeline import __version__
from pipeline.application.activities import DiscoverDocument, FetchDocument, ParseDocument
from pipeline.infrastructure.fakes import FakePlainTextParser, FakeSourceAdapter
from pipeline.workflows import TASK_QUEUE, IngestDocumentWorkflow
from py_common.logging import configure_logging
from py_common.settings import Settings
from py_common.telemetry import configure_telemetry
from py_common.temporal import ActivityBase, WorkerConfig, run_worker

SERVICE_NAME = "pipeline-worker"


def activities() -> list[ActivityBase[Any, Any]]:
    adapter = FakeSourceAdapter.with_sample()
    return [DiscoverDocument(adapter), FetchDocument(adapter), ParseDocument(FakePlainTextParser())]


async def serve(settings: Settings) -> None:
    telemetry = configure_telemetry(
        service_name=SERVICE_NAME, version=__version__, settings=settings
    )
    try:
        await run_worker(
            settings,
            WorkerConfig(task_queue=TASK_QUEUE),
            workflows=[IngestDocumentWorkflow],
            activities=activities(),
        )
    finally:
        telemetry.shutdown()


def main() -> None:
    settings = Settings(service_name=SERVICE_NAME)
    configure_logging(
        service_name=SERVICE_NAME, log_level=settings.log_level, json_output=settings.log_json
    )
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
