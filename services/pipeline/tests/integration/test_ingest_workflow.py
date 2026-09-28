"""The ingest workflow end to end on a local Temporal dev server.

``WorkflowEnvironment.start_local`` downloads the Temporal CLI once (native on Apple Silicon;
the time-skipping test server is x86-only and needs Rosetta, so it is not used).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from domain_kernel.ids import DocumentId
from pipeline.settings import PipelineSettings
from pipeline.testing import MemoryRulebook
from pipeline.worker import activities
from pipeline.workflows import IngestDocumentWorkflow, IngestRequest, IngestResult
from py_common.settings import Settings
from py_common.temporal.client import default_interceptors
from py_common.temporal.worker import WorkerConfig, build_worker


@pytest.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(
        data_converter=pydantic_data_converter, interceptors=default_interceptors()
    ) as env:
        yield env


async def test_ingest_workflow_runs_all_three_activities(environment: WorkflowEnvironment) -> None:
    task_queue = f"pipeline-test-{uuid.uuid4().hex[:8]}"
    worker = build_worker(
        environment.client,
        WorkerConfig(task_queue=task_queue),
        workflows=[IngestDocumentWorkflow],
        activities=activities(),
    )
    request = IngestRequest(source_id=uuid.UUID(int=1), since=datetime(2026, 9, 1, tzinfo=UTC))
    async with worker:
        result = await environment.client.execute_workflow(
            IngestDocumentWorkflow.run,
            request,
            id=f"ingest-{uuid.uuid4()}",
            task_queue=task_queue,
        )
    assert isinstance(result, IngestResult)
    assert result.clause_count == 3
    assert result.clause_refs == ["p1", "p2", "p3"]
    assert result.url == "https://example.invalid/notifications/17-2026"
    assert result.document_id == uuid.UUID(result.sha256[:32])
    assert result.registered is False


async def test_with_knowledge_the_document_is_registered_in_the_rulebook(
    environment: WorkflowEnvironment,
) -> None:
    task_queue = f"pipeline-test-{uuid.uuid4().hex[:8]}"
    rulebook = MemoryRulebook()
    settings = PipelineSettings(
        _env_file=None, service_name="pipeline-worker", pipeline_knowledge_enabled=True
    )
    worker = build_worker(
        environment.client,
        WorkerConfig(task_queue=task_queue),
        workflows=[IngestDocumentWorkflow],
        activities=activities(settings, sink=rulebook),
    )
    request = IngestRequest(
        source_id=uuid.UUID(int=1),
        since=datetime(2026, 9, 1, tzinfo=UTC),
        knowledge=True,
        regulator="CBIC",
    )
    async with worker:
        result = await environment.client.execute_workflow(
            IngestDocumentWorkflow.run,
            request,
            id=f"ingest-{uuid.uuid4()}",
            task_queue=task_queue,
        )
    assert result.registered is True
    record = rulebook.records[DocumentId(result.document_id)]
    assert [clause.clause_ref for clause in record.document.clauses] == result.clause_refs
    assert record.regulator == "CBIC"


async def test_settings_default_to_the_dev_stack_temporal() -> None:
    settings = Settings(_env_file=None, service_name="pipeline-worker")
    assert settings.temporal_address == "localhost:7233"
    assert settings.temporal_namespace == "default"
