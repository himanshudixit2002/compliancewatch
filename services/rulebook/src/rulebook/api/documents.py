"""Regulator documents: the pipeline registers them, anyone reads them back."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from domain_kernel.ids import DocumentId
from py_common.problems import problem_responses
from rulebook.api.deps import PipelineAccess, Wired
from rulebook.api.schemas import DocumentIn, DocumentOut, RegisteredOut

router = APIRouter(tags=["documents"])


@router.put(
    "/documents/{document_id}",
    summary="Register a parsed regulator document; idempotent for the same clauses",
    dependencies=[PipelineAccess],
    responses={
        status.HTTP_201_CREATED: {"model": RegisteredOut, "description": "Stored now"},
        **problem_responses(401, 403, 409, 422, 503),
    },
)
def register_document(
    document_id: UUID, body: DocumentIn, wired: Wired, response: Response
) -> RegisteredOut:
    registration = wired.register_document.run(
        body.to_document(document_id), [clause.to_clause() for clause in body.clauses]
    )
    if registration.created:
        response.status_code = status.HTTP_201_CREATED
    return RegisteredOut.from_registration(registration)


@router.get(
    "/documents/{document_id}",
    summary="A stored document with its clauses in order",
    responses=problem_responses(404),
)
def read_document(document_id: UUID, wired: Wired) -> DocumentOut:
    document, clauses = wired.read_document.run(DocumentId(document_id))
    return DocumentOut.from_stored(document, clauses)
