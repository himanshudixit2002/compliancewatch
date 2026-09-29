"""Service clients: the other services (and the WhatsApp bot) that get service tokens.

A client has an id, the scopes it may use and the SHA-256 of its secret; the secret itself is
shown once, when the client is created, and never stored. A service exchanges its id and secret
for a short-lived access token (``POST /v1/identity/service-tokens``). Revoking a client stops new
tokens at once; tokens already issued expire within the token lifetime.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Protocol, Self

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.access import MAX_CLIENT_ID_CHARS, Scope
from domain_kernel.errors import InvariantViolationError

SECRET_BYTES: Final = 32
"""A client secret is 32 random bytes, URL-safe base64 encoded."""
MIN_SECRET_CHARS: Final = 32
CLIENT_ID: Final = re.compile(r"[a-z0-9][a-z0-9._-]*")
DIGEST: Final = re.compile(r"[0-9a-f]{64}")


def new_secret() -> str:
    return secrets.token_urlsafe(SECRET_BYTES)


def secret_digest(secret: str) -> str:
    """The SHA-256 of ``secret`` in hex: what the store keeps. A secret is random and long, so a
    plain hash is enough; there is nothing to guess."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def require_client_id(value: object) -> str:
    text = require_text(value, "client_id")
    if len(text) > MAX_CLIENT_ID_CHARS or CLIENT_ID.fullmatch(text) is None:
        raise InvariantViolationError(
            "a client id is lower-case letters, digits, dots, dashes and underscores, "
            f"at most {MAX_CLIENT_ID_CHARS} characters"
        )
    return text


@dataclass(frozen=True, slots=True)
class ServiceClient:
    client_id: str
    secret_sha256: str
    scopes: frozenset[Scope]
    created_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        require_client_id(self.client_id)
        if not isinstance(self.secret_sha256, str) or DIGEST.fullmatch(self.secret_sha256) is None:
            raise InvariantViolationError("secret_sha256 must be 64 lower-case hex digits")
        scopes = require_instance(self.scopes, frozenset, "scopes")
        if not all(isinstance(scope, Scope) for scope in scopes):
            raise InvariantViolationError("scopes must hold Scope members")
        require_aware(self.created_at, "created_at")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, "revoked_at")

    @classmethod
    def with_secret(
        cls, client_id: str, scopes: frozenset[Scope], secret: str, *, at: datetime
    ) -> Self:
        """A client whose secret is ``secret``, which must be long enough to be random."""
        if not isinstance(secret, str) or len(secret) < MIN_SECRET_CHARS:
            raise InvariantViolationError(
                f"a client secret has at least {MIN_SECRET_CHARS} characters"
            )
        return cls(client_id, secret_digest(secret), scopes, at)

    @classmethod
    def create(cls, client_id: str, scopes: frozenset[Scope], *, at: datetime) -> tuple[Self, str]:
        """A new client and its secret, which the caller shows once."""
        secret = new_secret()
        return cls.with_secret(client_id, scopes, secret, at=at), secret

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def matches(self, secret: str) -> bool:
        """Whether ``secret`` is this client's, compared in constant time."""
        return hmac.compare_digest(secret_digest(secret), self.secret_sha256)

    def revoked(self, at: datetime) -> Self:
        return self if self.revoked_at is not None else replace(self, revoked_at=at)


class ServiceClientRepository(Protocol):
    def add(self, client: ServiceClient) -> None: ...

    def save(self, client: ServiceClient) -> None: ...

    def get(self, client_id: str) -> ServiceClient | None: ...

    def list(self) -> list[ServiceClient]:
        """Every client, by id."""
        ...
