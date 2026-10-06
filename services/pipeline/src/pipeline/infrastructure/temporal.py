"""The crawl and ingest workflows on Temporal, as the pipeline's ``CrawlStarter`` and
``IngestStarter``.

``TemporalCrawls.start`` starts ``pipeline.crawl_source`` on the ``pipeline`` task queue with the
start's workflow id, the id reuse policy ``REJECT_DUPLICATE`` (an id is used once, ever: a second
start, running or finished, is refused and answers False) and the crawl's execution timeout
(``schedule.CRAWL_TIMEOUT``). ``TemporalIngests.start`` starts ``pipeline.ingest_document`` of a
stored document (an upload's, a manual parse's resolution's) the same way, with the policy
``ALLOW_DUPLICATE_FAILED_ONLY`` (a failed ingest may run again under its id) and the ingest's
timeout (``schedule.INGEST_TIMEOUT``). The workflows are named, not imported, and their inputs are
built here in the shape of ``CrawlRequest`` and ``IngestRequest``, since infrastructure imports no
application code; tests check the shapes against those models.

Starts come from synchronous code on a thread (a route, the worker's tick), so each runs on an
event loop of its own (``asyncio.run``) with a client connected for it
(``py_common.temporal.connect``: the settings' address, namespace and credentials, the pydantic
data converter). A start is rare, so the connection is not kept. A start that fails or takes
longer than ``TIMEOUT_SECONDS`` is a ``CrawlUnavailableError`` or an ``IngestUnavailableError``.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Final

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from domain_kernel.errors import DomainError
from pipeline.domain.errors import CrawlUnavailableError, IngestUnavailableError
from pipeline.domain.ports import CrawlStart, IngestStart
from pipeline.domain.schedule import CRAWL_TIMEOUT, INGEST_TIMEOUT
from py_common.settings import Settings
from py_common.temporal import connect

CRAWL_WORKFLOW: Final = "pipeline.crawl_source"
INGEST_WORKFLOW: Final = "pipeline.ingest_document"
CRAWL_TASK_QUEUE: Final = "pipeline"
TIMEOUT_SECONDS: Final = 10.0

Connect = Callable[[Settings], Awaitable[Client]]


def crawl_payload(start: CrawlStart) -> dict[str, object]:
    """The workflow's input: ``CrawlRequest``'s fields as JSON values."""
    return {
        "source_key": start.source_key,
        "run_id": str(start.run_id),
        "trigger": start.trigger.value,
    }


def ingest_payload(start: IngestStart) -> dict[str, object]:
    """The ingest workflow's input: ``IngestRequest``'s fields, the document as ``Stored``, as
    JSON values."""
    record = start.record
    stored: dict[str, object] = {
        "document_id": str(record.document_id),
        "source_id": str(start.source_id),
        "source_key": record.source_key,
        "regulator": start.regulator,
        "url": record.source_url,
        "external_ref": record.external_ref,
        "media_type": record.content_type,
        "sha256": record.sha256,
        "size": record.size,
        "fetched_at": record.fetched_at.isoformat(),
        "storage_key": record.storage_key,
        "raw_uri": start.raw_uri,
        "duplicate": start.duplicate,
        "title": record.title,
        "published_at": None if record.published_on is None else record.published_on.isoformat(),
    }
    payload: dict[str, object] = {
        "source_id": str(start.source_id),
        "stored": stored,
        "knowledge": start.knowledge,
        "regulator": start.regulator,
    }
    if start.transcript_key:
        payload["transcript_key"] = start.transcript_key
    return payload


class _TemporalStarter:
    def __init__(
        self,
        settings: Settings,
        *,
        connector: Connect = connect,
        timeout_seconds: float = TIMEOUT_SECONDS,
        task_queue: str = CRAWL_TASK_QUEUE,
    ) -> None:
        self._settings = settings
        self._connect = connector
        self._timeout = timeout_seconds
        self._task_queue = task_queue

    def _run(
        self,
        workflow: str,
        payload: dict[str, object],
        workflow_id: str,
        *,
        policy: WorkflowIDReusePolicy,
        timeout: timedelta,
        unavailable: Callable[[str], DomainError],
        what: str,
    ) -> bool:
        start = self._start(workflow, payload, workflow_id, policy, timeout)
        try:
            return asyncio.run(asyncio.wait_for(start, self._timeout))
        except Exception as exc:
            raise unavailable(
                f"Temporal at {self._settings.temporal_address} did not start {what}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    async def _start(
        self,
        workflow: str,
        payload: dict[str, object],
        workflow_id: str,
        policy: WorkflowIDReusePolicy,
        execution_timeout: timedelta,
    ) -> bool:
        client = await self._connect(self._settings)
        try:
            await client.start_workflow(
                workflow,
                payload,
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=policy,
                execution_timeout=execution_timeout,
            )
        except WorkflowAlreadyStartedError:
            return False
        return True


class TemporalCrawls(_TemporalStarter):
    def start(self, start: CrawlStart) -> bool:
        return self._run(
            CRAWL_WORKFLOW,
            crawl_payload(start),
            start.workflow_id,
            policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            timeout=CRAWL_TIMEOUT,
            unavailable=CrawlUnavailableError,
            what="the crawl",
        )


class TemporalIngests(_TemporalStarter):
    def start(self, start: IngestStart) -> bool:
        return self._run(
            INGEST_WORKFLOW,
            ingest_payload(start),
            start.workflow_id,
            policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            timeout=INGEST_TIMEOUT,
            unavailable=IngestUnavailableError,
            what="the ingest",
        )
