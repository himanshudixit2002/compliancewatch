"""Ingest one document: discover, fetch and store, parse, and with ``knowledge`` register it in
the rulebook, embed its clauses for search and extract its knowledge in a child workflow.

A crawl (``workflows.crawl_source``) starts one ingest per new document it listed and hands it
the document as listed (``IngestRequest.discovered``): that ingest skips the discovery, behind
``workflow.patched(GIVEN_PATCH)``. A request without it discovers the first document since
``since``, as before.

Each step is an activity with its own retries and timeouts; the workflow itself does no I/O.
The fetch is ``FetchAndStore``: the bytes go to the raw store, the document's row and its
``document.discovered`` to the pipeline's store in one transaction, and the workflow passes on the
storage key, never the bytes. It sits behind ``workflow.patched(STORE_PATCH)``: a workflow
started before it replays its ``FetchDocument``, whose result carries the bytes, unchanged. The
registration, embedding and extraction steps sit behind patches of their own for the same
reason, and a failed registration, embedding or extraction is reported in the result rather
than failing the ingest.
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
        FetchAndStore,
        FetchDocument,
        Frozen,
        ParseDocument,
        ParseRequest,
        document_id_for,
    )
    from pipeline.application.knowledge_activities import (
        EmbedClauses,
        EmbedRequest,
        RegisterDocument,
        RegisterRequest,
    )
    from pipeline.workflows.extract_knowledge import (
        ExtractKnowledgeWorkflow,
        KnowledgeRequest,
        KnowledgeResult,
    )

from datetime import datetime
from uuid import UUID

TASK_QUEUE = "pipeline"
STORE_PATCH = "pipeline-store-v1"
GIVEN_PATCH = "pipeline-crawl-v1"
REGISTER_PATCH = "kag-register-v1"
EMBED_PATCH = "kag-embed-v1"
EXTRACT_PATCH = "kag-extract-v1"


class IngestRequest(Frozen):
    """``discovered``: the document a crawl listed, to ingest as it is; without it the ingest
    discovers the first document the source lists since ``since``."""

    source_id: UUID
    since: datetime | None = None
    discovered: Discovered | None = None
    knowledge: bool = False
    regulator: str = ""

    @model_validator(mode="after")
    def _regulator_with_knowledge(self) -> Self:
        if self.knowledge and not self.regulator.strip():
            raise ValueError("regulator is required when knowledge is on")
        return self

    @model_validator(mode="after")
    def _a_document_or_a_time(self) -> Self:
        if self.since is None and self.discovered is None:
            raise ValueError("an ingest request names the document, or a time to discover since")
        if self.discovered is not None and self.discovered.source_id != self.source_id:
            raise ValueError("the document belongs to another source")
        return self

    def discover_since(self) -> datetime:
        if self.since is None:
            raise ValueError("this request names its document and discovers nothing")
        return self.since


class IngestResult(Frozen):
    """``storage_key`` is where the raw store keeps the bytes (empty for a workflow started
    before the store); ``duplicate`` says they were stored by an earlier fetch."""

    document_id: UUID
    sha256: str
    url: str
    clause_count: int
    clause_refs: list[str]
    storage_key: str = ""
    duplicate: bool = False
    registered: bool = False
    registration_error: str = ""
    clauses_embedded: int = 0
    embedding_error: str = ""
    mentions_queued: int = 0
    relations_outcome: str = "disabled"
    relations_staged: int = 0
    knowledge_error: str = ""


@workflow.defn(name="pipeline.ingest_document")
class IngestDocumentWorkflow:
    @workflow.run
    async def run(self, request: IngestRequest) -> IngestResult:
        discovered: Discovered
        if request.discovered is not None and workflow.patched(GIVEN_PATCH):
            discovered = request.discovered
        else:
            discovered = await DiscoverDocument.schedule(
                DiscoverRequest(source_id=request.source_id, since=request.discover_since())
            )
        storage_key, duplicate = "", False
        if workflow.patched(STORE_PATCH):
            stored = await FetchAndStore.schedule(discovered)
            parse_request = ParseRequest(
                document_id=stored.document_id,
                stored=stored,
                title=discovered.title,
                published_at=discovered.published_at,
            )
            storage_key, duplicate = stored.storage_key, stored.duplicate
        else:
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
        clauses_embedded, embedding_error = 0, ""
        if registered and workflow.patched(EMBED_PATCH):
            try:
                embedded = await EmbedClauses.schedule(
                    EmbedRequest(document_id=parsed.document_id, regulator=request.regulator)
                )
                clauses_embedded = embedded.embedded
            except ActivityError as error:
                embedding_error = str(error.cause or error)[:500]
                workflow.logger.warning("clause embedding failed: %s", embedding_error)
        knowledge, knowledge_error = KnowledgeResult(relations_outcome="disabled"), ""
        if registered and workflow.patched(EXTRACT_PATCH):
            try:
                knowledge = await workflow.execute_child_workflow(
                    ExtractKnowledgeWorkflow.run,
                    KnowledgeRequest(
                        document_id=parsed.document_id,
                        own_ref=parse_request.external_ref,
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
            sha256=parse_request.sha256,
            url=parse_request.url,
            clause_count=parsed.clause_count,
            clause_refs=parsed.clause_refs,
            storage_key=storage_key,
            duplicate=duplicate,
            registered=registered,
            registration_error=registration_error,
            clauses_embedded=clauses_embedded,
            embedding_error=embedding_error,
            mentions_queued=knowledge.mentions_queued,
            relations_outcome=knowledge.relations_outcome,
            relations_staged=knowledge.relations_staged,
            knowledge_error=knowledge_error,
        )
