"""Ingest one document: discover, fetch, parse. The sample workflow of the pipeline worker.

The real ingest adds the detector, the extractor, the outbox write of ``document.discovered``
and ``document.parsed``, and a store for the raw file; this one shows the shape: each step is an
activity with its own retries and timeouts, the workflow itself does no I/O.
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from pipeline.application.activities import (
        DiscoverDocument,
        Discovered,
        DiscoverRequest,
        FetchDocument,
        Frozen,
        ParseDocument,
        ParseRequest,
        document_id_for,
    )

from datetime import datetime
from uuid import UUID

TASK_QUEUE = "pipeline"


class IngestRequest(Frozen):
    source_id: UUID
    since: datetime


class IngestResult(Frozen):
    document_id: UUID
    sha256: str
    url: str
    clause_count: int
    clause_refs: list[str]


@workflow.defn(name="pipeline.ingest_document")
class IngestDocumentWorkflow:
    @workflow.run
    async def run(self, request: IngestRequest) -> IngestResult:
        discovered: Discovered = await DiscoverDocument.schedule(
            DiscoverRequest(source_id=request.source_id, since=request.since)
        )
        fetched = await FetchDocument.schedule(discovered)
        parsed = await ParseDocument.schedule(
            ParseRequest(
                document_id=document_id_for(fetched).value,
                fetched=fetched,
                title=discovered.title,
                published_at=discovered.published_at,
            )
        )
        return IngestResult(
            document_id=parsed.document_id,
            sha256=fetched.sha256,
            url=fetched.url,
            clause_count=parsed.clause_count,
            clause_refs=parsed.clause_refs,
        )
