"""The crawl workflow on Temporal, as the pipeline's ``CrawlStarter``.

``TemporalCrawls.start`` starts ``pipeline.crawl_source`` on the ``pipeline`` task queue with the
start's workflow id, the id reuse policy ``REJECT_DUPLICATE`` (an id is used once, ever: a second
start, running or finished, is refused and answers False) and the crawl's execution timeout
(``schedule.CRAWL_TIMEOUT``). The workflow is named, not imported, and its input is built here in
the shape of ``application.crawl.CrawlRequest``, since infrastructure imports no application
code.

Starts come from synchronous code on a thread (a route, the worker's tick), so each runs on an
event loop of its own (``asyncio.run``) with a client connected for it
(``py_common.temporal.connect``: the settings' address, namespace and credentials, the pydantic
data converter). A start is rare, one per source and cadence, so the connection is not kept. A
start that fails or takes longer than ``TIMEOUT_SECONDS`` is a ``CrawlUnavailableError``.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from pipeline.domain.errors import CrawlUnavailableError
from pipeline.domain.ports import CrawlStart
from pipeline.domain.schedule import CRAWL_TIMEOUT
from py_common.settings import Settings
from py_common.temporal import connect

CRAWL_WORKFLOW: Final = "pipeline.crawl_source"
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


class TemporalCrawls:
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

    def start(self, start: CrawlStart) -> bool:
        try:
            return asyncio.run(asyncio.wait_for(self._start(start), self._timeout))
        except CrawlUnavailableError:
            raise
        except Exception as exc:
            raise CrawlUnavailableError(
                f"Temporal at {self._settings.temporal_address} did not start the crawl: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    async def _start(self, start: CrawlStart) -> bool:
        client = await self._connect(self._settings)
        try:
            await client.start_workflow(
                CRAWL_WORKFLOW,
                crawl_payload(start),
                id=start.workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                execution_timeout=CRAWL_TIMEOUT,
            )
        except WorkflowAlreadyStartedError:
            return False
        return True
