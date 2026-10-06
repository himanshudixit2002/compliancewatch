"""Ingest one document: discover, fetch and store, parse, and with ``knowledge`` register it in
the rulebook, embed its clauses for search and extract its knowledge in a child workflow.

A crawl (``workflows.crawl_source``) starts one ingest per new document it listed and hands it
the document as listed (``IngestRequest.discovered``): that ingest skips the discovery, behind
``workflow.patched(GIVEN_PATCH)``. A request without it discovers the first document since
``since``, as before. An upload, and a manual parse's resolution, start an ingest of a document
stored already (``IngestRequest.stored``): it skips the discovery and the fetch and parses at
once, behind ``workflow.patched(STORED_PATCH)``; the resolution's ingest names the analyst's
transcript (``transcript_key``), which is parsed instead of the bytes.

A stored document no parser of the chain reads (``UnparsedDocumentError``, or
``UnsupportedDocumentError`` for a media type no parser takes) no longer fails the ingest, behind
``workflow.patched(PARSE_PATCH)``: ``pipeline.open_manual_parse`` sets the document ``failed``
and opens its manual-parse task, and the ingest ends there with ``parse_failed``, so nothing of
it is registered. A workflow that failed on its parse before the patch replays as it ran.

After its parse, a stored document is classified, behind ``workflow.patched(CLASSIFY_PATCH)``
(``pipeline.classify_document``, ``application.classify``): its type, how sure that is, and
whether it is a regulatory document, recorded with its status and its ``document.classified``.
An irrelevant document is set aside and a conflict (its text names another type than its source
publishes) waits for a person's ``triage`` task; the ingest ends there for both, so nothing of
them is registered. Everything else is registered as the type it was classified as.

Statutes are registered and their clauses embedded like any document, so rules can cite them,
but nothing is extracted from them (``domain.candidate.is_extracted``): the extraction child is
not started for one.

A notification, circular or act amendment that was classified and registered gets its rule
candidate extracted, behind ``workflow.patched(EXTRACTION_PATCH)`` and while the worker's
``CW_PIPELINE_EXTRACTION_ENABLED`` is on (``Classified.extracts``): the ingest starts the child
``pipeline.extract_rules`` (``workflows.extract_rules``) under the id
``pipeline-extract-<document>-<prompt>``, which may be reused only after a failure, and leaves it
running (``ParentClosePolicy.ABANDON``), so neither the ingest nor a crawl waits for a model or
for a used-up budget. A press release and a statute are kept for reference and not extracted.

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
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    ChildWorkflowError,
    WorkflowAlreadyStartedError,
)

with workflow.unsafe.imports_passed_through():
    from pydantic import Field, model_validator

    from domain_kernel.documents import DocumentType
    from pipeline.application.activities import (
        DiscoverDocument,
        Discovered,
        DiscoverRequest,
        FetchAndStore,
        FetchDocument,
        Frozen,
        OpenManualParse,
        ParseDocument,
        ParseFailure,
        ParseRequest,
        Stored,
        document_id_for,
    )
    from pipeline.application.classify import Classified, ClassifyDocument, ClassifyRequest
    from pipeline.application.extraction import RULE_PROMPT_REF, ExtractionRequest
    from pipeline.application.knowledge_activities import (
        EmbedClauses,
        EmbedRequest,
        RegisterDocument,
        RegisterRequest,
    )
    from pipeline.domain.candidate import is_extracted
    from pipeline.domain.classification import Route
    from pipeline.domain.tasks import MAX_REASON_CHARS
    from pipeline.workflows.extract_knowledge import (
        ExtractKnowledgeWorkflow,
        KnowledgeRequest,
        KnowledgeResult,
    )
    from pipeline.workflows.extract_rules import (
        EXTRACTION_TIMEOUT,
        ExtractRulesWorkflow,
        extraction_workflow_id,
    )

from datetime import datetime
from uuid import UUID

TASK_QUEUE = "pipeline"
STORE_PATCH = "pipeline-store-v1"
GIVEN_PATCH = "pipeline-crawl-v1"
STORED_PATCH = "pipeline-stored-v1"
PARSE_PATCH = "pipeline-parse-v1"
CLASSIFY_PATCH = "pipeline-classify-v1"
EXTRACTION_PATCH = "pipeline-extraction-v1"
REGISTER_PATCH = "kag-register-v1"
EMBED_PATCH = "kag-embed-v1"
EXTRACT_PATCH = "kag-extract-v1"
PARSE_FAILURES = frozenset({"UnparsedDocumentError", "UnsupportedDocumentError"})
"""What a parse fails with when no parser of the chain reads the document."""


def failure_text(error: BaseException) -> str:
    """What failed, as ``Type: message``: the first cause below the activity and child workflow
    wrappers, which is the error the activity or the child raised (a timeout, say, or the
    application error its exception became)."""
    cause: BaseException = error
    while isinstance(cause, ActivityError | ChildWorkflowError) and cause.cause is not None:
        cause = cause.cause
    if isinstance(cause, ApplicationError) and cause.type:
        text = f"{cause.type}: {cause.message}"
    else:
        text = f"{type(cause).__name__}: {cause}"
    return text.strip()


def unparsed(error: ActivityError) -> bool:
    """Whether the parse failed because no parser reads the document."""
    cause = error.cause
    return isinstance(cause, ApplicationError) and cause.type in PARSE_FAILURES


class IngestRequest(Frozen):
    """The document to ingest: ``discovered``, as a crawl listed it; ``stored``, stored already
    (an upload, a manual parse's resolution), with ``transcript_key`` naming the analyst's
    transcript to parse it from; or neither, and the ingest discovers the first document the
    source lists since ``since``."""

    source_id: UUID
    since: datetime | None = None
    discovered: Discovered | None = None
    stored: Stored | None = None
    transcript_key: str = Field(default="", max_length=1_024)
    knowledge: bool = False
    regulator: str = ""

    @model_validator(mode="after")
    def _regulator_with_knowledge(self) -> Self:
        if self.knowledge and not self.regulator.strip():
            raise ValueError("regulator is required when knowledge is on")
        return self

    @model_validator(mode="after")
    def _a_document_or_a_time(self) -> Self:
        if self.since is None and self.discovered is None and self.stored is None:
            raise ValueError("an ingest request names the document, or a time to discover since")
        if self.discovered is not None and self.stored is not None:
            raise ValueError("an ingest request names its document once: listed or stored")
        given = self.discovered or self.stored
        if given is not None and given.source_id != self.source_id:
            raise ValueError("the document belongs to another source")
        if self.transcript_key and self.stored is None:
            raise ValueError("a transcript is parsed for a stored document only")
        return self

    def discover_since(self) -> datetime:
        if self.since is None:
            raise ValueError("this request names its document and discovers nothing")
        return self.since


class IngestResult(Frozen):
    """``storage_key`` is where the raw store keeps the bytes (empty for a workflow started
    before the store); ``duplicate`` says they were stored by an earlier fetch.
    ``parser_version`` names the parser of the clauses. ``parse_failed`` says no parser read the
    document: its manual-parse task is ``task_id`` (None when none opened), and it has no
    clauses and was not registered. ``classification`` is the classify step's route
    (``extract``, ``reference``, ``irrelevant``, ``triage``; empty before the step) and
    ``doc_type`` the type it placed the document as; a document held for triage names its task
    in ``task_id``, and neither it nor an irrelevant one is registered. ``extraction`` says what
    became of its rule extraction: ``started`` (``extraction_workflow_id`` names the child),
    ``running`` (a child of that id runs or has completed), ``off`` (the worker's extraction is
    off), ``not_registered`` (the extraction reads the document from the rulebook), or empty when
    there is none to make (a reference document, a workflow from before the step)."""

    document_id: UUID
    sha256: str
    url: str
    clause_count: int
    clause_refs: list[str]
    storage_key: str = ""
    duplicate: bool = False
    parser_version: str = ""
    parse_failed: bool = False
    task_id: UUID | None = None
    classification: str = ""
    doc_type: str = ""
    registered: bool = False
    registration_error: str = ""
    clauses_embedded: int = 0
    embedding_error: str = ""
    mentions_queued: int = 0
    relations_outcome: str = "disabled"
    relations_staged: int = 0
    knowledge_error: str = ""
    extraction: str = ""
    extraction_workflow_id: str = ""


@workflow.defn(name="pipeline.ingest_document")
class IngestDocumentWorkflow:
    @workflow.run
    async def run(self, request: IngestRequest) -> IngestResult:
        if request.stored is not None and workflow.patched(STORED_PATCH):
            parse_request = ParseRequest(
                document_id=request.stored.document_id,
                stored=request.stored,
                title=request.stored.title,
                published_at=request.stored.published_at,
                transcript_key=request.transcript_key,
            )
        else:
            parse_request = await self._fetch(request)
        storage_key = "" if parse_request.stored is None else parse_request.stored.storage_key
        duplicate = parse_request.stored is not None and parse_request.stored.duplicate
        try:
            parsed = await ParseDocument.schedule(parse_request)
        except ActivityError as error:
            if (
                parse_request.stored is None
                or not unparsed(error)
                or not workflow.patched(PARSE_PATCH)
            ):
                raise
            reason = failure_text(error)[:MAX_REASON_CHARS]
            workflow.logger.warning("no parser reads the document: %s", reason)
            opened = await OpenManualParse.schedule(
                ParseFailure(document_id=parse_request.document_id, reason=reason)
            )
            return IngestResult(
                document_id=parse_request.document_id,
                sha256=parse_request.sha256,
                url=parse_request.url,
                clause_count=0,
                clause_refs=[],
                storage_key=storage_key,
                duplicate=duplicate,
                parse_failed=True,
                task_id=opened.task_id,
            )
        classified: Classified | None = None
        if parse_request.stored is not None and workflow.patched(CLASSIFY_PATCH):
            classified = await ClassifyDocument.schedule(ClassifyRequest(parse=parse_request))
            if classified.stops:
                workflow.logger.info(
                    "the document stops at its classification: %s", classified.route
                )
                return IngestResult(
                    document_id=parsed.document_id,
                    sha256=parse_request.sha256,
                    url=parse_request.url,
                    clause_count=parsed.clause_count,
                    clause_refs=parsed.clause_refs,
                    storage_key=storage_key,
                    duplicate=duplicate,
                    parser_version=parsed.parser_version,
                    task_id=classified.task_id if classified.route == Route.TRIAGE else None,
                    classification=classified.route,
                    doc_type=classified.doc_type,
                )
        doc_type = parsed.doc_type if classified is None else classified.doc_type
        registered, registration_error = False, ""
        if request.knowledge and workflow.patched(REGISTER_PATCH):
            try:
                outcome = await RegisterDocument.schedule(
                    RegisterRequest(
                        parse=parse_request,
                        regulator=request.regulator,
                        doc_type=None if classified is None else DocumentType(doc_type),
                    )
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
        # A statute is registered and embedded, never extracted (domain.candidate.is_extracted).
        if registered and is_extracted(doc_type) and workflow.patched(EXTRACT_PATCH):
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
        extraction, extraction_workflow_id = "", ""
        if classified is not None and classified.route == Route.EXTRACT:
            extraction, extraction_workflow_id = await self._extract(
                request, classified, registered, parse_request
            )
        return IngestResult(
            document_id=parsed.document_id,
            sha256=parse_request.sha256,
            url=parse_request.url,
            clause_count=parsed.clause_count,
            clause_refs=parsed.clause_refs,
            storage_key=storage_key,
            duplicate=duplicate,
            parser_version=parsed.parser_version,
            classification="" if classified is None else classified.route,
            doc_type="" if classified is None else classified.doc_type,
            registered=registered,
            registration_error=registration_error,
            clauses_embedded=clauses_embedded,
            embedding_error=embedding_error,
            mentions_queued=knowledge.mentions_queued,
            relations_outcome=knowledge.relations_outcome,
            relations_staged=knowledge.relations_staged,
            knowledge_error=knowledge_error,
            extraction=extraction,
            extraction_workflow_id=extraction_workflow_id,
        )

    async def _extract(
        self,
        request: IngestRequest,
        classified: Classified,
        registered: bool,
        parse_request: ParseRequest,
    ) -> tuple[str, str]:
        """Start the rule extraction of a classified, registered rule kind and leave it running;
        what became of it and the child's id."""
        if not classified.extraction_enabled:
            return "off", ""
        if not registered or parse_request.stored is None:
            return "not_registered", ""
        if not workflow.patched(EXTRACTION_PATCH):
            return "", ""
        workflow_id = extraction_workflow_id(classified.document_id, RULE_PROMPT_REF)
        try:
            await workflow.start_child_workflow(
                ExtractRulesWorkflow.run,
                ExtractionRequest(
                    document_id=classified.document_id,
                    source_id=request.source_id,
                    source_key=parse_request.stored.source_key,
                    regulator=request.regulator,
                    doc_type=DocumentType(classified.doc_type),
                    own_ref=parse_request.external_ref,
                ),
                id=workflow_id,
                task_queue=workflow.info().task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                execution_timeout=EXTRACTION_TIMEOUT,
            )
        except WorkflowAlreadyStartedError:
            return "running", workflow_id
        return "started", workflow_id

    async def _fetch(self, request: IngestRequest) -> ParseRequest:
        """The listed (or discovered) document, fetched and stored (or, in a workflow from
        before the store, fetched and carried), as the request of its parse."""
        discovered: Discovered
        if request.discovered is not None and workflow.patched(GIVEN_PATCH):
            discovered = request.discovered
        else:
            discovered = await DiscoverDocument.schedule(
                DiscoverRequest(source_id=request.source_id, since=request.discover_since())
            )
        if workflow.patched(STORE_PATCH):
            stored = await FetchAndStore.schedule(discovered)
            return ParseRequest(
                document_id=stored.document_id,
                stored=stored,
                title=discovered.title,
                published_at=discovered.published_at,
            )
        fetched = await FetchDocument.schedule(discovered)
        return ParseRequest(
            document_id=document_id_for(fetched).value,
            fetched=fetched,
            title=discovered.title,
            published_at=discovered.published_at,
        )
