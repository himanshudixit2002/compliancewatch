"""The crawl, ingest and backlog workflows on Temporal, as the pipeline's ``CrawlStarter`` (and
``CrawlWatcher``), ``IngestStarter`` and ``BacklogStarter``.

``TemporalCrawls.start`` starts ``pipeline.crawl_source`` on the ``pipeline`` task queue with the
start's workflow id, the id reuse policy ``REJECT_DUPLICATE`` (an id is used once, ever: a second
start, running or finished, is refused and answers False) and the crawl's execution timeout
(``schedule.CRAWL_TIMEOUT``). ``TemporalIngests.start`` starts ``pipeline.ingest_document`` of a
stored document (an upload's, a manual parse's resolution's) the same way, with the policy
``ALLOW_DUPLICATE_FAILED_ONLY`` (a failed ingest may run again under its id) and the ingest's
timeout (``schedule.INGEST_TIMEOUT``). The workflows are named, not imported, and their inputs are
built here in the shape of ``CrawlRequest`` and ``IngestRequest``, since infrastructure imports no
application code; tests check the shapes against those models.

``TemporalIngests.running`` describes each workflow id it is given and names those whose
workflow runs, so a retry refuses to start while an ingest of its document runs; an id Temporal
does not know is not running. ``TemporalCrawls.wait`` waits for a crawl's result (a backfill's
rounds run one after the other). ``TemporalBacklog.start`` starts ``pipeline.extract_backlog``
(``REJECT_DUPLICATE``, the extraction's timeout).

Starts come from synchronous code on a thread (a route, the worker's tick, a command), so each
runs on an event loop of its own (``asyncio.run``) with a client connected for it
(``py_common.temporal.connect``: the settings' address, namespace and credentials, the pydantic
data converter). A start is rare, so the connection is not kept. A start that fails or takes
longer than ``TIMEOUT_SECONDS`` is a ``CrawlUnavailableError`` or an ``IngestUnavailableError``.
"""

import asyncio
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from datetime import timedelta
from typing import Any, Final

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from domain_kernel.errors import DomainError
from pipeline.domain.errors import CrawlUnavailableError, IngestUnavailableError
from pipeline.domain.ports import CrawlOutcome, CrawlStart, IngestStart
from pipeline.domain.schedule import CRAWL_TIMEOUT, INGEST_TIMEOUT
from py_common.settings import Settings
from py_common.temporal import connect

CRAWL_WORKFLOW: Final = "pipeline.crawl_source"
INGEST_WORKFLOW: Final = "pipeline.ingest_document"
BACKLOG_WORKFLOW: Final = "pipeline.extract_backlog"
CRAWL_TASK_QUEUE: Final = "pipeline"
TIMEOUT_SECONDS: Final = 10.0
BACKLOG_TIMEOUT: Final = timedelta(days=45)
"""The backlog sweep's execution timeout: as long as one extraction may wait out its budget."""
CRAWL_WAIT_SECONDS: Final = CRAWL_TIMEOUT.total_seconds() + 60

Connect = Callable[[Settings], Awaitable[Client]]


def crawl_payload(start: CrawlStart) -> dict[str, object]:
    """The workflow's input: ``CrawlRequest``'s fields as JSON values; a backfill's listing
    window, references and limit only when it names them."""
    payload: dict[str, object] = {
        "source_key": start.source_key,
        "run_id": str(start.run_id),
        "trigger": start.trigger.value,
    }
    if start.since is not None:
        payload["since"] = start.since.isoformat()
    if start.until is not None:
        payload["until"] = start.until.isoformat()
    if start.refs:
        payload["refs"] = list(start.refs)
    if start.limit is not None:
        payload["limit"] = start.limit
    return payload


def crawl_outcome(workflow_id: str, result: Mapping[str, Any]) -> CrawlOutcome:
    """A crawl workflow's result (``CrawlResult`` as JSON) as the backfill reads it."""

    def count(name: str) -> int:
        value = result.get(name, 0)
        return int(value) if isinstance(value, int | float) else 0

    return CrawlOutcome(
        workflow_id=workflow_id,
        status=str(result.get("status", "")),
        listed=count("listed"),
        stored=count("stored"),
        duplicates=count("duplicates"),
        failed=count("failed"),
        deferred=count("deferred"),
        error=str(result.get("error", "") or ""),
    )


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
    if start.reclassify:
        payload["reclassify"] = True
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

    def _ask[T](
        self,
        work: Callable[[Client], Awaitable[T]],
        *,
        timeout: float,
        unavailable: Callable[[str], DomainError],
        what: str,
    ) -> T:
        """``work`` on a client connected for it, within ``timeout`` seconds."""

        async def asked() -> T:
            client = await self._connect(self._settings)
            return await work(client)

        try:
            return asyncio.run(asyncio.wait_for(asked(), timeout))
        except DomainError:
            raise
        except Exception as exc:
            raise unavailable(
                f"Temporal at {self._settings.temporal_address} did not answer {what}: "
                f"{type(exc).__name__}: {exc}"
            ) from exc


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

    def wait(self, workflow_id: str) -> CrawlOutcome:
        async def result(client: Client) -> CrawlOutcome:
            found = await client.get_workflow_handle(workflow_id).result()
            return crawl_outcome(workflow_id, found if isinstance(found, Mapping) else {})

        return self._ask(
            result,
            timeout=CRAWL_WAIT_SECONDS,
            unavailable=CrawlUnavailableError,
            what=f"the crawl {workflow_id}",
        )


async def running_of(client: Client, workflow_ids: Collection[str]) -> frozenset[str]:
    """Those of ``workflow_ids`` whose workflow runs; an unknown id is not running."""
    found: set[str] = set()
    for workflow_id in sorted(set(workflow_ids)):
        try:
            described = await client.get_workflow_handle(workflow_id).describe()
        except RPCError as exc:
            if exc.status is RPCStatusCode.NOT_FOUND:
                continue
            raise
        if described.status is WorkflowExecutionStatus.RUNNING:
            found.add(workflow_id)
    return frozenset(found)


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

    def running(self, workflow_ids: Collection[str]) -> frozenset[str]:
        if not workflow_ids:
            return frozenset()
        return self._ask(
            lambda client: running_of(client, workflow_ids),
            timeout=self._timeout,
            unavailable=IngestUnavailableError,
            what="which ingests run",
        )


class TemporalBacklog(_TemporalStarter):
    """Starts the backlog sweep (``pipeline.extract_backlog``) with its documents."""

    def start(self, workflow_id: str, payload: Mapping[str, object]) -> bool:
        return self._run(
            BACKLOG_WORKFLOW,
            dict(payload),
            workflow_id,
            policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            timeout=BACKLOG_TIMEOUT,
            unavailable=IngestUnavailableError,
            what="the backlog sweep",
        )


def backlog_payload(
    documents: Sequence[Mapping[str, object]], concurrency: int
) -> dict[str, object]:
    """The sweep's input: ``BacklogRequest``'s fields, each document an ``ExtractionRequest``."""
    return {"documents": [dict(document) for document in documents], "concurrency": concurrency}
