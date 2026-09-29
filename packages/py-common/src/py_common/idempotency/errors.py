"""The problems an idempotent route answers with. py-common maps them for every service
(``DEFAULT_STATUS_BY_ERROR``): 428, 422 and 409."""

from collections.abc import Mapping
from typing import ClassVar, Final

from domain_kernel.errors import DomainError

IDEMPOTENCY_KEY_HEADER: Final = "Idempotency-Key"
"""The request header that carries the key. The spec marks it required; its absence is the 428
problem below rather than request-invalid (``MISSING_HEADER_ERRORS`` in ``py_common.problems``)."""


class IdempotencyKeyRequiredError(DomainError):
    """A creating request came without an ``Idempotency-Key`` header (428)."""

    type_slug = "idempotency-key-required"
    title = "Idempotency key is required"

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail
            or "Send an Idempotency-Key header of 8 to 128 characters, new for each new request"
        )


class IdempotencyKeyReusedError(DomainError):
    """The key was used before for a different request: another method, path or body (422)."""

    type_slug = "idempotency-key-reused"
    title = "Idempotency key was used for another request"

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail or "This Idempotency-Key was sent with a different request; use a new key"
        )


class IdempotencyRequestInFlightError(DomainError):
    """The first request with this key has not finished yet (409); retry shortly."""

    type_slug = "idempotency-request-in-flight"
    title = "Request with this idempotency key is still running"
    problem_headers: ClassVar[Mapping[str, str]] = {"Retry-After": "1"}

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail or "The first request with this Idempotency-Key is still running; retry it"
        )
