"""Ingest one document: discover, fetch, parse, and with ``knowledge`` register it in the
rulebook and extract its knowledge in a child workflow. The sample workflow of the pipeline
worker.

The real ingest adds the detector, the extractor, the outbox write of ``document.discovered``
and ``document.parsed``, and a store for the raw file; this one shows the shape: each step is an
activity with its own retries and timeouts, the workflow itself does no I/O. The registration
and extraction steps sit behind ``workflow.patched`` so histories recorded before them replay
unchanged, and a failed registration or extraction is reported in the result rather than
failing the ingest.
"""

from typing import Self

from temporalio import workflow
from temporalio.exceptions import ActivityError, ChildWorkflowError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from pydantic import model_validator

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
    from pipeline.application.knowledge_activities import RegisterDocument, RegisterRequest
    from pipeline.workflows.extract_knowledge import (
        ExtractKnowledgeWorkflow,
        KnowledgeRequest,
        KnowledgeResult,
    )

from datetime import datetime
from uuid import UUID

TASK_QUEUE = "pipeline"
REGISTER_PATCH = "kag-register-v1"
EXTRACT_PATCH = "kag-extract-v1"


class IngestRequest(Frozen):
    source_id: UUID
    since: datetime
    knowledge: bool = False
    regulator: str = ""

    @model_validator(mode="after")
    def _regulator_with_knowledge(self) -> Self:
        if self.knowledge and not self.regulator.strip():
            raise ValueError("regulator is required when knowledge is on")
        return self


class IngestResult(Frozen):
    document_id: UUID
    sha256: str
    url: str
    clause_count: int
    clause_refs: list[str]
    registered: bool = False
    registration_error: str = ""
    mentions_queued: int = 0
    relations_outcome: str = "disabled"
    relations_staged: int = 0
    knowledge_error: str = ""


@workflow.defn(name="pipeline.ingest_document")
class IngestDocumentWorkflow:
    @workflow.run
    async def run(self, request: IngestRequest) -> IngestResult:
        discovered: Discovered = await DiscoverDocument.schedule(
            DiscoverRequest(source_id=request.source_id, since=request.since)
        )
        fetched = await FetchDocument.schedule(discovered)
        parse_request = ParseRequest(
            document_id=document_id_for(fetched).value,
            fetched=fetched,
            title=discovered.title,
            published_at=discovered.published_at,
        )
        parsed = await ParseDocument.schedule(parse_request)
        registered, registration_error = False, ""
        if request.knowledge and workflow.patched(REGISTER_PATCH):
            try:
                outcome = await RegisterDocument.schedule(
                    RegisterRequest(parse=parse_request, regulator=request.regulator)
                )
                registered = not outcome.skipped
            except ActivityError as error:
                registration_error = str(error.cause or error)[:500]
                workflow.logger.warning("document registration failed: %s", registration_error)
        knowledge, knowledge_error = KnowledgeResult(relations_outcome="disabled"), ""
        if registered and workflow.patched(EXTRACT_PATCH):
            try:
                knowledge = await workflow.execute_child_workflow(
                    ExtractKnowledgeWorkflow.run,
                    KnowledgeRequest(
                        document_id=parsed.document_id,
                        own_ref=fetched.external_ref,
                        regulator=request.regulator,
                    ),
                    id=f"extract-knowledge-{parsed.document_id}",
                    task_queue=workflow.info().task_queue,
                )
            except (ChildWorkflowError, WorkflowAlreadyStartedError) as error:
                knowledge_error = str(error.cause or error)[:500]
                workflow.logger.warning("knowledge extraction failed: %s", knowledge_error)
        return IngestResult(
            document_id=parsed.document_id,
            sha256=fetched.sha256,
            url=fetched.url,
            clause_count=parsed.clause_count,
            clause_refs=parsed.clause_refs,
            registered=registered,
            registration_error=registration_error,
            mentions_queued=knowledge.mentions_queued,
            relations_outcome=knowledge.relations_outcome,
            relations_staged=knowledge.relations_staged,
            knowledge_error=knowledge_error,
        )
