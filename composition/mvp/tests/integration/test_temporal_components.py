"""The composed worker serves the Temporal task queues of several services on one client.

``WorkflowEnvironment.start_local`` downloads the Temporal CLI once (native on Apple Silicon;
the time-skipping test server is x86-only and needs Rosetta, so it is not used).
"""

import pytest

pytestmark = pytest.mark.integration

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from cw_mvp.testing import mvp_settings
from cw_mvp.worker import run_worker
from pipeline.settings import PipelineSettings
from pipeline.worker import activities
from pipeline.workflows import IngestDocumentWorkflow, IngestRequest, IngestResult
from py_common.runtime import ComponentRegistry, TemporalComponent, WorkerComponents
from py_common.temporal.client import default_interceptors
from py_common.temporal.liveness import running_queues
from py_common.temporal.worker import WorkerConfig

REQUEST = IngestRequest(source_id=uuid.UUID(int=1), since=datetime(2026, 9, 1, tzinfo=UTC))


@pytest.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter, interceptors=default_interceptors()
    ) as env:
        yield env


def _hosting(task_queue: str) -> WorkerComponents:
    settings = PipelineSettings(_env_file=None, service_name="pipeline")
    worker = TemporalComponent(
        WorkerConfig(task_queue=task_queue), (IngestDocumentWorkflow,), activities(settings)
    )
    return WorkerComponents(temporal=(worker,))


async def test_two_task_queues_are_served_by_one_client(environment: WorkflowEnvironment) -> None:
    first, second = (f"queue-{name}-{uuid.uuid4().hex[:8]}" for name in ("a", "b"))
    root = mvp_settings(mvp_host="127.0.0.1", log_level="WARNING", worker_temporal_enabled=True)
    hosted = (
        ComponentRegistry()
        .register("pipeline", root, _hosting(first))
        .register("rulebook", root, _hosting(second))
    )
    assert hosted.task_queues() == (first, second)
    stop = asyncio.Event()
    worker = asyncio.create_task(
        run_worker(root, stop, hosted=hosted, client=environment.client, health_port=0)
    )
    try:
        results = await asyncio.gather(
            *(
                environment.client.execute_workflow(
                    IngestDocumentWorkflow.run,
                    REQUEST,
                    id=f"ingest-{uuid.uuid4()}",
                    task_queue=queue,
                )
                for queue in (first, second)
            )
        )
        assert {first, second} <= set(running_queues())
    finally:
        stop.set()
        await asyncio.wait_for(worker, timeout=60)
    assert all(isinstance(result, IngestResult) for result in results)
    assert [result.clause_count for result in results] == [3, 3]
    assert not {first, second} & set(running_queues())
