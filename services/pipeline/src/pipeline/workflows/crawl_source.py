"""Crawl one source: list what is new since its watermark, ingest it, record how it went.

``pipeline.crawl_source`` (``CrawlSourceWorkflow``) runs on the ``pipeline`` task queue, started
by the worker's tick or an admin's fetch with the run their start recorded
(``application.crawl``):

1. ``pipeline.list_new_documents`` lists the source since a week before its watermark and leaves
   out the URLs the store holds;
2. each new document is ingested by a child ``pipeline.ingest_document`` that takes it as listed
   (``IngestRequest.discovered``), at most ``CHILD_CONCURRENCY`` (3) at a time. A child's id
   names the source and the URL (``schedule.ingest_workflow_id``) and may be reused only after a
   failure, so a document two crawls list is ingested once; a child whose id is in use counts as
   deferred. Children are abandoned, not cancelled, when the crawl ends early: what they store
   stays stored;
3. ``pipeline.finish_crawl`` records the run's counts and end and the source's last listing,
   watermark and error.

A backfill's crawl (trigger ``backfill``) lists its own window instead of the watermark's: from a
date below the watermark, up to another, only the references its plan names, behind
``workflow.patched(BACKFILL_PATCH)``; its end records the run only, and the source keeps its
watermark, last listing and error. A crawl that names no window records no marker, so the
histories of every other crawl stay as they were.

A failure is recorded, not raised: a listing that fails ends the run as failed with the error on
the run and (unless the crawl is a backfill) the source, and a child that fails counts as failed.
The workflow does no I/O itself.
"""

import asyncio

from temporalio import workflow
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import (
    ActivityError,
    ChildWorkflowError,
    WorkflowAlreadyStartedError,
)

with workflow.unsafe.imports_passed_through():
    from pipeline.application.activities import Discovered
    from pipeline.application.crawl import (
        MAX_OUTCOME_ERROR_CHARS,
        ChildOutcome,
        CrawlRequest,
        CrawlResult,
        FinishCrawl,
        FinishRequest,
        Listing,
        ListNewDocuments,
        ListRequest,
    )
    from pipeline.domain.crawl import Outcome
    from pipeline.domain.schedule import CHILD_CONCURRENCY, INGEST_TIMEOUT, ingest_workflow_id
    from pipeline.workflows.ingest_document import (
        IngestDocumentWorkflow,
        IngestRequest,
        failure_text,
    )

CRAWL_WORKFLOW = "pipeline.crawl_source"
MAX_ERROR_CHARS = 1_000
BACKFILL_PATCH = "pipeline-backfill-v1"


@workflow.defn(name=CRAWL_WORKFLOW)
class CrawlSourceWorkflow:
    @workflow.run
    async def run(self, request: CrawlRequest) -> CrawlResult:
        listing_request = ListRequest(
            source_key=request.source_key, run_id=request.run_id, limit=request.limit
        )
        if request.window.narrows and workflow.patched(BACKFILL_PATCH):
            listing_request = ListRequest(
                source_key=request.source_key,
                run_id=request.run_id,
                limit=request.limit,
                since=request.since,
                until=request.until,
                refs=request.refs,
            )
        try:
            listing = await ListNewDocuments.schedule(listing_request)
        except ActivityError as error:
            reason = failure_text(error)[:MAX_ERROR_CHARS] or "the listing failed"
            workflow.logger.warning("crawl listing failed: %s", reason)
            return await FinishCrawl.schedule(
                FinishRequest(
                    source_key=request.source_key,
                    run_id=request.run_id,
                    error=reason,
                    trigger=request.trigger,
                )
            )
        gate = asyncio.Semaphore(CHILD_CONCURRENCY)
        outcomes = await asyncio.gather(
            *(self._ingest(listing, document, gate) for document in listing.new)
        )
        return await FinishCrawl.schedule(
            FinishRequest(
                source_key=request.source_key,
                run_id=request.run_id,
                listed=listing.listed,
                known_newest=listing.known_newest,
                deferred_oldest=listing.deferred_oldest,
                outcomes=list(outcomes),
                trigger=request.trigger,
                deferred=listing.deferred,
            )
        )

    async def _ingest(
        self, listing: Listing, document: Discovered, gate: asyncio.Semaphore
    ) -> ChildOutcome:
        async with gate:
            try:
                result = await workflow.execute_child_workflow(
                    IngestDocumentWorkflow.run,
                    IngestRequest(
                        source_id=listing.source_id,
                        discovered=document,
                        knowledge=listing.knowledge,
                        regulator=listing.regulator,
                    ),
                    id=ingest_workflow_id(listing.source_key, document.url),
                    task_queue=workflow.info().task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=INGEST_TIMEOUT,
                )
            except WorkflowAlreadyStartedError:
                return ChildOutcome(
                    url=document.url,
                    published_at=document.published_at,
                    outcome=Outcome.DEFERRED,
                    error="another ingest of the document runs or has run",
                )
            except ChildWorkflowError as error:
                return ChildOutcome(
                    url=document.url,
                    published_at=document.published_at,
                    outcome=Outcome.FAILED,
                    error=failure_text(error)[:MAX_OUTCOME_ERROR_CHARS],
                )
        return ChildOutcome(
            url=document.url,
            published_at=document.published_at,
            outcome=Outcome.DUPLICATE if result.duplicate else Outcome.STORED,
        )
