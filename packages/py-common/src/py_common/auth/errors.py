"""The problems authentication answers with. py-common maps them for every service
(``DEFAULT_STATUS_BY_ERROR``): 401, 401, 403, 403 and 503.

A 401 carries ``WWW-Authenticate: Bearer`` (RFC 6750), with ``error="invalid_token"`` when a
token came but failed verification.
"""

from collections.abc import Mapping
from typing import ClassVar

from domain_kernel.errors import DomainError


class AuthTokenRequiredError(DomainError):
    """The request needs a bearer access token and carries none (401)."""

    type_slug = "auth-token-required"
    title = "Access token is required"
    problem_headers: ClassVar[Mapping[str, str]] = {"WWW-Authenticate": "Bearer"}

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail
            or "Send an access token from the identity service as Authorization: Bearer <token>"
        )


class AuthTokenInvalidError(DomainError):
    """The bearer token failed verification: signature, algorithm, issuer, audience, expiry or
    claims (401)."""

    type_slug = "auth-token-invalid"
    title = "Access token is invalid"
    problem_headers: ClassVar[Mapping[str, str]] = {
        "WWW-Authenticate": 'Bearer error="invalid_token"'
    }


class AuthForbiddenError(DomainError):
    """The caller is known but lacks the role or scope the route needs (403)."""

    type_slug = "auth-forbidden"
    title = "Caller lacks the role or scope for this request"


class AuthTenantMismatchError(DomainError):
    """``x-tenant-id`` names a tenant other than the one the user's token is for (403)."""

    type_slug = "auth-tenant-mismatch"
    title = "Tenant header does not match the access token"

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            detail or "x-tenant-id names another tenant than the access token; drop the header"
        )


class AuthKeysUnavailableError(DomainError):
    """The identity service's signing keys could not be fetched and none are cached, so no
    token can be verified (503)."""

    type_slug = "auth-keys-unavailable"
    title = "Token signing keys are unavailable"
