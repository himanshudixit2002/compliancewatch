"""The operations routes: every source's crawl runs and documents, a retry of a stored document,
and the outbox's dead rows with their requeue.

The routes belong to the regulatory team (composition class admin), with the source manager's
guards (``pipeline.api.deps``): the reads need a regulatory role a token names; the retry and
the requeue an admin, or the shared write token in ``header`` and ``dual`` mode. Each write names
its actor and a reason, and writes its ``audit.event`` row (``pipeline.document.retry``,
``pipeline.outbox.requeue``, of no tenant) in the transaction of the change. A retry takes an
``Idempotency-Key``: the same request sent again replays its answer.
"""

from datetime import date
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from domain_kernel.access import Principal
from domain_kernel.documents import DocumentType
from domain_kernel.ids import DocumentId
from pipeline.api.deps import SourceRead, SourceWrite, Wired, admin_actor
from pipeline.api.operations_schemas import (
    DeadCursor,
    FetchCursor,
    OutboxEventOut,
    PipelineDocumentOut,
    RequeueIn,
    RequeueOut,
    RetryAcceptedOut,
    RetryIn,
    RunCursor,
    RunOut,
)
from pipeline.api.schemas import AdminWriteIn
from pipeline.application.operations import RetryRequest
from pipeline.application.sources import AdminAction
from pipeline.domain.crawl import CrawlStatus, CrawlTrigger
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.repository import DocumentQuery, RunQuery
from pipeline.domain.sources import SOURCE_KEY_PATTERN
from py_common.audit import current_correlation_id
from py_common.idempotency.fastapi import (
    IDEMPOTENCY_RESPONSES,
    REPLAYED_HEADER,
    IdempotencyKey,
)
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])

RUNS_SCOPE: Final = "pipeline.runs"
DOCUMENTS_SCOPE: Final = "pipeline.documents"
DEAD_SCOPE: Final = "pipeline.outbox.dead"
TOPIC_PATTERN: Final = r"^[a-z][a-z0-9_.-]{0,119}$"

SourceFilter = Annotated[
    str | None, Query(pattern=SOURCE_KEY_PATTERN, description="Only this source's")
]


def _admin(principal: Principal, body: AdminWriteIn) -> AdminAction:
    return AdminAction(
        actor=admin_actor(principal, body.actor_id),
        reason=body.reason,
        correlation_id=current_correlation_id(),
    )


def _scope(name: str, *parts: object) -> str:
    return ".".join([name, *("any" if part is None else str(part) for part in parts)])


@router.get(
    "/runs",
    summary="List the crawl runs, the latest first",
    dependencies=[SourceRead],
    responses=problem_responses(401, 403, 422),
)
def list_runs(
    page: Pagination,
    wired: Wired,
    source_key: SourceFilter = None,
    status: Annotated[
        CrawlStatus | None, Query(description="Only runs that are running, completed or failed")
    ] = None,
    trigger: Annotated[
        CrawlTrigger | None,
        Query(description="Only runs the schedule's tick, an admin's fetch or a backfill started"),
    ] = None,
) -> Page[RunOut]:
    """Every source's crawl runs, a page at a time, the latest started first (then by id):
    when each ran, why (its trigger and workflow; null on runs recorded before they were
    kept), what its listing found (listed; stored, duplicates and failed of the new documents)
    and how it ended."""
    scope = _scope(RUNS_SCOPE, source_key, status, trigger)
    after = page.after(scope, RunCursor)
    runs = wired.list_runs.run(
        RunQuery(
            source_key=source_key,
            status=status,
            trigger=trigger,
            after=None if after is None else after.key(),
            limit=page.limit + 1,
        )
    )
    kept, cursor = page_of(runs, page.limit, scope, RunCursor.of)
    return Page[RunOut](items=[RunOut.of_run(run) for run in kept], next_cursor=cursor)


@router.get(
    "/documents",
    summary="List every source's documents, the latest fetch first",
    dependencies=[SourceRead],
    responses=problem_responses(401, 403, 422),
)
def list_every_document(
    page: Pagination,
    wired: Wired,
    status: Annotated[
        DocumentStatus | None,
        Query(
            description=(
                "Only documents of this status: discovered, parsed, failed (no parser reads it), "
                "irrelevant (set aside), classified (waiting for its extraction), triage, "
                "reference, extracted"
            )
        ),
    ] = None,
    source_key: SourceFilter = None,
    doc_type: Annotated[
        DocumentType | None,
        Query(
            description=(
                "Only documents the pipeline reads as this type: its classification's, else its "
                "uploader's, else its source's"
            )
        ),
    ] = None,
    published_from: Annotated[
        date | None, Query(description="Only documents published on or after this day")
    ] = None,
    published_to: Annotated[
        date | None, Query(description="Only documents published on or before this day")
    ] = None,
) -> Page[PipelineDocumentOut]:
    """Every source's stored documents, a page at a time, the latest first fetch first (then by
    id), each with the type the pipeline reads it as, its classification and its extraction by
    the current prompt. A date filter leaves undated documents out."""
    scope = _scope(DOCUMENTS_SCOPE, status, source_key, doc_type, published_from, published_to)
    after = page.after(scope, FetchCursor)
    views = wired.list_every_document.run(
        DocumentQuery(
            status=status,
            source_key=source_key,
            doc_type=doc_type,
            published_from=published_from,
            published_to=published_to,
            after=None if after is None else after.key(),
            limit=page.limit + 1,
        )
    )
    kept, cursor = page_of(views, page.limit, scope, FetchCursor.of)
    return Page[PipelineDocumentOut](
        items=[PipelineDocumentOut.of_view(view) for view in kept], next_cursor=cursor
    )


@router.post(
    "/documents/{document_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run a stored document again from a stage",
    response_model=RetryAcceptedOut,
    responses={
        **problem_responses(401, 403, 404, 409, 422, 503),
        **IDEMPOTENCY_RESPONSES,
    },
)
def retry_document(
    document_id: UUID,
    body: RetryIn,
    admin: SourceWrite,
    key: IdempotencyKey,
    wired: Wired,
) -> JSONResponse:
    """Start the stored document's ingest again from ``stage``, without a new fetch, under the
    workflow ``pipeline-retry-<document>-<attempt>``, and answer 202 with the attempt.

    - ``parse``: the whole ingest of the stored bytes (parse, classify, register while knowledge
      is on, extract a notification, circular or act amendment while the extraction is on); a
      document no parser read is parsed again;
    - ``classify``: the same, the detector reading the document again (a person's decision
      stands);
    - ``extract``: the rule extraction of a document classified on its way to it whose extraction
      failed or never started.

    A ``doc_type`` reclassifies the document first: relevant, of that type, certain, by retry,
    with its status and a document.classified. It beats the detector and is the way back for a
    document set aside as irrelevant or whose triage was dismissed. Audited as
    pipeline.document.retry. The same request with its Idempotency-Key again answers its attempt
    (``Idempotent-Replayed: true``) and starts its ingest only if it did not start; the key with
    another body is a 422. 409 while an ingest of the document runs (an earlier retry's, its
    crawl's, a task resolution's, its rule extraction's), while a triage task holds it, or when
    there is nothing to extract; 422 for an extraction of a type no rule is extracted from; 503
    when Temporal does not answer (the attempt stays recorded: send the same request again)."""
    outcome = wired.retry_document.run(
        RetryRequest(
            document_id=DocumentId(document_id),
            stage=body.stage,
            doc_type=body.doc_type,
            idempotency_key=key.key,
            fingerprint=key.fingerprint,
            admin=_admin(admin, body),
        )
    )
    answer = RetryAcceptedOut.of(outcome)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=answer.model_dump(mode="json"),
        headers={REPLAYED_HEADER: "true"} if outcome.replayed else None,
    )


@router.get(
    "/outbox/dead",
    summary="List the outbox's dead rows, the newest dead first",
    dependencies=[SourceRead],
    responses=problem_responses(401, 403, 422),
)
def list_dead_events(
    page: Pagination,
    wired: Wired,
    topic: Annotated[
        str | None,
        Query(
            pattern=TOPIC_PATTERN, description="Only rows of this topic, such as document.parsed"
        ),
    ] = None,
) -> Page[OutboxEventOut]:
    """The pipeline's outbox rows the relay marked dead after its eight sends failed (their
    message is on <topic>.dlq), a page at a time, the newest dead first: the topic, key,
    attempts, last error, when each went dead, and a summary of the payload without its body."""
    scope = _scope(DEAD_SCOPE, topic)
    after = page.after(scope, DeadCursor)
    events = wired.list_dead_events.run(
        topic=topic, after=None if after is None else after.key(), limit=page.limit + 1
    )
    kept, cursor = page_of(events, page.limit, scope, DeadCursor.of)
    return Page[OutboxEventOut](
        items=[OutboxEventOut.of(event) for event in kept], next_cursor=cursor
    )


@router.post(
    "/outbox/{event_id}/requeue",
    summary="Put a dead outbox row back to pending",
    responses=problem_responses(401, 403, 404, 422, 503),
)
def requeue_event(event_id: UUID, body: RequeueIn, admin: SourceWrite, wired: Wired) -> RequeueOut:
    """Put the dead row back to pending with its attempts reset, due at once, so the relay sends
    it again on its next pass; its last error stays until a send succeeds. Audited as
    pipeline.outbox.requeue. A row that is not dead (pending, published) is answered as it
    stands, with requeued false and nothing written, so the request is safe to send again. 404
    for an id the outbox does not hold."""
    return RequeueOut.of(wired.requeue_event.run(event_id, _admin(admin, body)))
