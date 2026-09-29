"""Problem details (RFC 9457) for every error a service returns.

A ``DomainError`` becomes ``application/problem+json`` whose ``type`` is the error's ``type_uri``.
The service passes the status each of its errors maps to; the kernel's defaults apply underneath.
Request validation errors, HTTP errors and unhandled exceptions get the same shape, so a client
parses one error format. An error may carry extra response headers in ``problem_headers``
(the gateway's budget error sets ``Retry-After`` that way). A required header listed in
``MISSING_HEADER_ERRORS`` that a request leaves out is answered with its own problem rather than
request-invalid: a creating request without ``Idempotency-Key`` is a 428.
"""

import json
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from domain_kernel.errors import (
    PROBLEM_TYPE_PREFIX,
    DomainError,
    InvariantViolationError,
    UnknownAttributeError,
)
from py_common.auth.errors import (
    AuthForbiddenError,
    AuthKeysUnavailableError,
    AuthTenantMismatchError,
    AuthTokenInvalidError,
    AuthTokenRequiredError,
    ServiceTokenUnavailableError,
)
from py_common.flags import UnknownFlagError
from py_common.idempotency.errors import (
    IDEMPOTENCY_KEY_HEADER,
    IdempotencyKeyRequiredError,
    IdempotencyKeyReusedError,
    IdempotencyRequestInFlightError,
)
from py_common.logging import get_logger
from py_common.pagination import InvalidCursorError
from py_common.request_context import REQUEST_ID_HEADER, correlation_id_of

PROBLEM_MEDIA_TYPE = "application/problem+json"
PROBLEM_SCHEMA_REF = "#/components/schemas/Problem"
VALIDATION_TYPE = PROBLEM_TYPE_PREFIX + "request-invalid"
INTERNAL_TYPE = PROBLEM_TYPE_PREFIX + "internal-error"
DEFAULT_STATUS_BY_ERROR: Mapping[type[DomainError], int] = {
    InvariantViolationError: 422,
    UnknownAttributeError: 404,
    InvalidCursorError: 422,
    IdempotencyKeyRequiredError: 428,
    IdempotencyKeyReusedError: 422,
    IdempotencyRequestInFlightError: 409,
    UnknownFlagError: 500,
    AuthTokenRequiredError: 401,
    AuthTokenInvalidError: 401,
    AuthForbiddenError: 403,
    AuthTenantMismatchError: 403,
    AuthKeysUnavailableError: 503,
    ServiceTokenUnavailableError: 503,
}
MISSING_HEADER_ERRORS: Mapping[str, type[DomainError]] = {
    IDEMPOTENCY_KEY_HEADER.lower(): IdempotencyKeyRequiredError,
}
"""Required headers, by lower-case name, whose absence is the given error."""

log = get_logger(__name__)


class ValidationIssue(BaseModel):
    """One failed check on the request. The submitted value is not echoed back."""

    loc: list[str | int]
    msg: str
    type: str


class Problem(BaseModel):
    """The body of every error response."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    correlation_id: str | None = None
    errors: list[ValidationIssue] | None = None


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries declaring the problem shape for the given statuses."""
    entries: dict[int | str, dict[str, Any]] = {
        status: {
            "description": _phrase(status),
            "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": PROBLEM_SCHEMA_REF}}},
        }
        for status in statuses
    }
    return entries


def install_problem_handlers(
    app: FastAPI,
    status_by_error: Mapping[type[DomainError], int],
    default_status: int = 400,
) -> None:
    """Register the handlers and publish the ``Problem`` schema in the app's OpenAPI components."""
    statuses: dict[type[DomainError], int] = {**DEFAULT_STATUS_BY_ERROR, **status_by_error}

    def domain_error(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, DomainError):  # pragma: no cover - registered for DomainError
            raise exc
        headers = getattr(exc, "problem_headers", None)
        return _respond(
            request,
            status=_status_for(exc, statuses, default_status),
            type_uri=exc.type_uri,
            title=exc.title,
            detail=exc.detail,
            headers=dict(headers) if headers else None,
        )

    def validation_error(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, RequestValidationError):  # pragma: no cover
            raise exc
        missing = _missing_header_error(exc.errors())
        if missing is not None:
            return domain_error(request, missing())
        issues = [
            ValidationIssue(loc=[*error["loc"]], msg=error["msg"], type=error["type"])
            for error in exc.errors()
        ]
        return _respond(
            request,
            status=422,
            type_uri=VALIDATION_TYPE,
            title="Request is invalid",
            detail="One or more request fields failed validation",
            errors=issues,
        )

    def http_error(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, HTTPException):  # pragma: no cover
            raise exc
        return _respond(
            request,
            status=exc.status_code,
            type_uri="about:blank",
            title=_phrase(exc.status_code),
            detail=str(exc.detail),
            headers=exc.headers,
        )

    def unhandled(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = correlation_id_of(request)
        # Starlette runs a sync handler in a thread with no active exception, so pass it along.
        log.exception(
            "unhandled_exception",
            path=request.url.path,
            correlation_id=correlation_id,
            exc_info=exc,
        )
        headers = {REQUEST_ID_HEADER: correlation_id} if correlation_id else None
        return _respond(
            request,
            status=500,
            type_uri=INTERNAL_TYPE,
            title="Internal error",
            detail="The request could not be completed",
            headers=headers,
        )

    app.add_exception_handler(DomainError, domain_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(Exception, unhandled)
    _publish_problem_schema(app)


def _missing_header_error(errors: Sequence[Any]) -> type[DomainError] | None:
    """The error for the first missing header that has one of its own."""
    for error in errors:
        loc = tuple(error.get("loc", ()))
        if error.get("type") == "missing" and len(loc) == 2 and loc[0] == "header":
            found = MISSING_HEADER_ERRORS.get(str(loc[1]).lower())
            if found is not None:
                return found
    return None


def _status_for(exc: DomainError, statuses: Mapping[type[DomainError], int], default: int) -> int:
    """The status mapped for the most specific class in the error's MRO."""
    mro = type(exc).__mro__
    ranked = [(mro.index(cls), status) for cls, status in statuses.items() if isinstance(exc, cls)]
    return min(ranked)[1] if ranked else default


def _phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def _respond(
    request: Request,
    *,
    status: int,
    type_uri: str,
    title: str,
    detail: str | None,
    headers: Mapping[str, str] | None = None,
    errors: list[ValidationIssue] | None = None,
) -> JSONResponse:
    problem = Problem(
        type=type_uri,
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        correlation_id=correlation_id_of(request),
        errors=errors,
    )
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=status,
        headers=headers,
        media_type=PROBLEM_MEDIA_TYPE,
    )


def _publish_problem_schema(app: FastAPI) -> None:
    """Add ``Problem`` and ``ValidationIssue`` to ``components.schemas`` once, for ``$ref`` use,
    and document the problem responses every route can return (``_document_problems``)."""
    original = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original()
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        if "Problem" not in components:
            problem = Problem.model_json_schema(ref_template="#/components/schemas/{model}")
            components.update(problem.pop("$defs", {}))
            components["Problem"] = problem
            _document_problems(schema)
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def _document_problems(schema: dict[str, Any]) -> None:
    """Make every operation document the problems the handlers above actually return.

    FastAPI documents a 422 as its own ``HTTPValidationError`` in ``application/json`` unless the
    route declares it, but ``validation_error`` answers with a ``Problem``. And a request body
    that cannot be decoded (bytes that are not UTF-8) is a 400 before validation runs, on every
    operation that takes a body.
    """
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            responses = operation.get("responses", {})
            if _is_fastapi_validation_response(responses.get("422")):
                responses["422"] = problem_responses(422)[422]
            if "requestBody" in operation and "400" not in responses:
                responses["400"] = problem_responses(400)[400]
    components = schema.get("components", {}).get("schemas", {})
    for name in ("HTTPValidationError", "ValidationError"):
        others = {key: value for key, value in components.items() if key != name}
        if f'/{name}"' not in json.dumps([schema.get("paths", {}), others]):
            components.pop(name, None)


def _is_fastapi_validation_response(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    body = response.get("content", {}).get("application/json", {}).get("schema", {})
    return str(body.get("$ref", "")).endswith("/HTTPValidationError")
