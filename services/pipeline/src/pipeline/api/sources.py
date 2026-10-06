"""The source manager's routes: the sources, their documents and the stored files.

Every route belongs to the regulatory team (composition class admin): the reads need a
regulatory role a token names, the writes an admin or the shared write token
(``pipeline.api.deps``). Each write names its actor and a reason, and its ``audit.event`` row
(``pipeline.source.add``, ``.edit`` or ``.fetch``, of no tenant) commits with the change it
records.
"""

from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from fastapi import APIRouter, Path, Response, status

from domain_kernel.access import Principal
from domain_kernel.ids import DocumentId
from pipeline.api.deps import SourceRead, SourceWrite, Wired, admin_actor
from pipeline.api.operations_schemas import DocumentDetailOut
from pipeline.api.schemas import (
    AdminWriteIn,
    DocumentCursor,
    DocumentOut,
    FetchIn,
    FetchOut,
    SourceEditIn,
    SourceIn,
    SourceOut,
    SourcesOut,
)
from pipeline.application.crawl import FetchRequest
from pipeline.application.sources import AdminAction, NewSource
from pipeline.domain.sources import SOURCE_KEY_PATTERN
from py_common.audit import current_correlation_id
from py_common.pagination import Page, Pagination, page_of
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"])

SourceKey = Path(pattern=SOURCE_KEY_PATTERN, description="The source's key")
DOCUMENTS_SCOPE: Final = "pipeline.source_documents"
RAW_MEDIA: Final[dict[str, Any]] = {
    "application/pdf": {"schema": {"type": "string", "format": "binary"}},
    "text/html": {"schema": {"type": "string"}},
    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
}
EXTENSIONS: Final = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/json": "json",
    "text/plain": "txt",
}


def _admin(principal: Principal, body: AdminWriteIn) -> AdminAction:
    return AdminAction(
        actor=admin_actor(principal, body.actor_id),
        reason=body.reason,
        correlation_id=current_correlation_id(),
    )


@router.get(
    "/sources",
    summary="List the sources with how each stands",
    dependencies=[SourceRead],
    responses=problem_responses(401, 403),
)
def list_sources(wired: Wired) -> SourcesOut:
    """Every source the pipeline reads, by key: its name, adapter type and parameters, cadence,
    switches, status (healthy, fetching, failing, paused), document count, last listing,
    freshness against its cadence, last error, watermark and latest crawl."""
    return SourcesOut(items=[SourceOut.of(view) for view in wired.list_sources.run()])


@router.post(
    "/sources",
    status_code=status.HTTP_201_CREATED,
    summary="Add a source",
    responses=problem_responses(401, 403, 409, 422, 503),
)
def add_source(body: SourceIn, admin: SourceWrite, wired: Wired) -> SourceOut:
    """Add a source of a registry adapter type with that type's parameters, which it checks
    (422 for an unknown type or parameters it refuses). 409 when the key is taken. Audited as
    pipeline.source.add with the reason. The schedule crawls it at its cadence while crawling is
    on, unless it is added disabled or paused."""
    source = wired.add_source.run(
        NewSource(
            key=body.key,
            name=body.name,
            adapter_type=body.adapter_type,
            parameters=body.parameters,
            cadence=timedelta(seconds=body.cadence_seconds),
            enabled=body.enabled,
            paused=body.paused,
        ),
        _admin(admin, body),
    )
    return SourceOut.of(wired.list_sources.one(source.key))


@router.patch(
    "/sources/{key}",
    summary="Edit a source",
    responses=problem_responses(401, 403, 404, 422, 503),
)
def edit_source(
    body: SourceEditIn, admin: SourceWrite, wired: Wired, key: str = SourceKey
) -> SourceOut:
    """Change a source's name, cadence, enabled or paused switch, or parameters (all of them,
    checked by its adapter type again); what is left out stays. Pausing stops the schedule from
    crawling it; a crawl that runs finishes. Audited as pipeline.source.edit with the source
    before and after, unless nothing changed."""
    wired.edit_source.run(key, body.edit(), _admin(admin, body))
    return SourceOut.of(wired.list_sources.one(key))


@router.post(
    "/sources/{key}/fetch",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a crawl of the source now",
    responses=problem_responses(401, 403, 404, 409, 422, 503),
)
def fetch_source(body: FetchIn, admin: SourceWrite, wired: Wired, key: str = SourceKey) -> FetchOut:
    """Record a crawl run and start its workflow; answers 202 with the run and workflow ids at
    once, and the source reads fetching until the crawl ends. A paused or disabled source may be
    fetched by hand. 409 while a crawl of the source runs, and for an upload-only source
    (pipeline-source-upload-only), which lists nothing; 503 while crawling is off
    (CW_PIPELINE_CRAWL_ENABLED) or when Temporal does not answer, in which case the run is
    closed as failed with why. Audited as pipeline.source.fetch with the reason."""
    action = _admin(admin, body)
    start = wired.start_crawl.run(
        FetchRequest(
            source_key=key,
            actor=action.actor,
            reason=action.reason,
            correlation_id=action.correlation_id,
        )
    )
    return FetchOut.of(start)


@router.get(
    "/sources/{key}/documents",
    summary="List a source's documents, newest first",
    dependencies=[SourceRead],
    responses=problem_responses(401, 403, 404, 422),
)
def list_documents(page: Pagination, wired: Wired, key: str = SourceKey) -> Page[DocumentOut]:
    """The documents stored from the source, a page at a time: the newest publication first
    (undated ones last), then the latest fetch, then the id. 404 for an unknown source."""
    after = page.after(f"{DOCUMENTS_SCOPE}.{key}", DocumentCursor)
    records = wired.list_documents.run(
        key, after=None if after is None else after.key(), limit=page.limit + 1
    )
    kept, cursor = page_of(records, page.limit, f"{DOCUMENTS_SCOPE}.{key}", DocumentCursor.of)
    return Page[DocumentOut](items=[DocumentOut.of(record) for record in kept], next_cursor=cursor)


@router.get(
    "/documents/{document_id}",
    summary="Read one stored document",
    dependencies=[SourceRead],
    responses=problem_responses(401, 403, 404),
)
def read_document(document_id: UUID, wired: Wired) -> DocumentDetailOut:
    """A stored document as its record holds it: where it was listed, what the listing said,
    when it was first fetched, its digest, storage key and status; with the type the pipeline
    reads it as, its classification, its extraction by the current prompt, and the retries
    people asked for."""
    return DocumentDetailOut.of_detail(wired.read_document_view.run(DocumentId(document_id)))


@router.get(
    "/documents/{document_id}/raw",
    summary="The stored bytes of a document",
    dependencies=[SourceRead],
    response_class=Response,
    responses={
        200: {"description": "The bytes, with their content type", "content": RAW_MEDIA},
        **problem_responses(401, 403, 404, 502, 503),
    },
)
def read_raw(document_id: UUID, wired: Wired) -> Response:
    """The bytes the raw store keeps for the document, served with the content type it was
    fetched with once their SHA-256 matches the record's (502 when the stored file is missing or
    altered, 503 when the raw store does not answer). The ETag is the digest; the bytes under it
    never change. The response is served inline, sandboxed and never sniffed."""
    raw = wired.read_raw.run(DocumentId(document_id))
    record = raw.record
    extension = EXTENSIONS.get(record.content_type.split(";")[0].strip(), "bin")
    return Response(
        content=raw.content,
        media_type=record.content_type,
        headers={
            "ETag": f'"{record.sha256}"',
            "Cache-Control": "private, max-age=86400, immutable",
            "Content-Disposition": f'inline; filename="{record.document_id}.{extension}"',
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )
