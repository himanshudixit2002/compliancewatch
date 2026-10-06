"""An analyst's upload of a document to a source: a PDF or an HTML page and what it is.

The route belongs to the regulatory team (composition class admin) and takes the source writes'
guard (``pipeline.api.deps``): an admin a token names, or the shared write token in ``header``
and ``dual`` mode. The body is ``multipart/form-data``: the file and the fields. It is refused
(413) before it is parsed once it passes the upload limit (``CW_PIPELINE_UPLOAD_MAX_BYTES``,
plus room for the fields): by its ``Content-Length`` when it gives one, else as it arrives. The
upload is audited as ``pipeline.document.upload`` with the reason.
"""

from collections.abc import Callable, Coroutine
from datetime import date
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, File, Form, Path, Request, Response, UploadFile, status
from fastapi.routing import APIRoute
from starlette.types import Message

from domain_kernel.documents import DocumentType
from pipeline.api.deps import SourceWrite, Wired, admin_actor
from pipeline.api.schemas import ACTOR_ID, REASON, UploadOut
from pipeline.application.sources import MAX_REASON_CHARS, MIN_REASON_CHARS, AdminAction
from pipeline.application.uploads import MAX_REF_CHARS, MAX_TITLE_CHARS, Upload
from pipeline.domain.errors import UploadTooLargeError
from pipeline.domain.sources import SOURCE_KEY_PATTERN
from pipeline.wiring import Wiring
from py_common.audit import current_correlation_id
from py_common.problems import problem_responses

FORM_ALLOWANCE: Final = 64 * 1024
"""Room in the body for the form's fields and boundaries beside the file."""


def body_limit(request: Request) -> int:
    wiring: Wiring = request.app.state.wiring
    return wiring.settings.pipeline_upload_max_bytes + FORM_ALLOWANCE


class UploadRoute(APIRoute):
    """A route whose body is read, up to the upload limit, before the form is parsed; a body
    past the limit is a 413 ``pipeline-upload-too-large``."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def capped(request: Request) -> Response:
            limit = body_limit(request)
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit:
                raise UploadTooLargeError(f"the body has {declared} bytes; at most {limit}")
            body = bytearray()
            async for chunk in request.stream():
                body += chunk
                if len(body) > limit:
                    raise UploadTooLargeError(f"the body passes {limit} bytes")
            delivered = False
            receive = request.receive

            async def replay() -> Message:
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            return await handler(Request(request.scope, replay))

        return capped


router = APIRouter(prefix="/v1/pipeline", tags=["pipeline"], route_class=UploadRoute)


@router.post(
    "/sources/{key}/uploads",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document to a source",
    responses=problem_responses(401, 403, 404, 413, 415, 422, 503),
)
def upload_document(
    admin: SourceWrite,
    wired: Wired,
    file: Annotated[UploadFile, File(description="The document: a PDF or an HTML page")],
    actor_id: Annotated[UUID, Form(description=ACTOR_ID)],
    reason: Annotated[
        str,
        Form(min_length=MIN_REASON_CHARS, max_length=MAX_REASON_CHARS, description=REASON),
    ],
    title: Annotated[str, Form(max_length=MAX_TITLE_CHARS, description="Its title")] = "",
    published_on: Annotated[date | None, Form(description="When it was published")] = None,
    external_ref: Annotated[
        str,
        Form(
            max_length=MAX_REF_CHARS,
            description="Its own reference, such as a notification number or the Act's name",
        ),
    ] = "",
    document_type: Annotated[
        DocumentType | None,
        Form(description="What it is; the source's document type when left out"),
    ] = None,
    key: str = Path(pattern=SOURCE_KEY_PATTERN, description="The source's key"),
) -> UploadOut:
    """Store the file under the source, record it with its document.discovered and start its
    ingest, which parses it and, while knowledge is on, registers it in the rulebook. Answers
    202 at once with the stored document and the ingest's workflow id; a document no parser
    reads opens a manual-parse task (GET /v1/pipeline/tasks). Bytes stored before are a
    duplicate: nothing is recorded again and the ingest runs again. 413 past the upload limit,
    415 for a file that is not a PDF or an HTML page, 404 for an unknown source, 503 when
    Temporal does not answer (the document stays stored: upload it again). Audited as
    pipeline.document.upload with the reason."""
    content = file.file.read()
    outcome = wired.upload_document.run(
        Upload(
            source_key=key,
            content=content,
            media_type=file.content_type or "",
            title=title,
            published_on=published_on,
            external_ref=external_ref,
            document_type=document_type,
        ),
        AdminAction(
            actor=admin_actor(admin, actor_id),
            reason=reason,
            correlation_id=current_correlation_id(),
        ),
    )
    return UploadOut.of(outcome)
