"""What an idempotency store keeps and the protocols ``run_idempotent`` works against.

A client sends a creating request with an ``Idempotency-Key`` header. The first request with a
key claims it (``Started``) and runs; its response is then recorded against the key. A retry
with the same key and the same request gets that response back (``Replay``) for
``REPLAY_WINDOW``. The same key with a different request is a client error (``Reused``), and a
retry that arrives while the first request still runs is told to wait (``InFlight``). Keys
belong to a tenant: another tenant's key of the same text is a different key.

A request is its method, its path and its body, reduced to a SHA-256 ``fingerprint``. A claimed
key is held for ``IN_FLIGHT_LEASE``; a request that died without recording anything (a crashed
process) frees its key when the lease runs out, so retries are not refused for a whole day.

``IdempotencyRecorder`` is the part ``run_idempotent`` calls: ``begin``, ``complete`` and
``abandon``. ``IdempotencyStore`` adds ``purge_expired`` for the daily purge. A store runs each
call on its own; a recorder bound to the caller's transaction (``SqlAlchemyIdempotencyRecorder``)
runs them inside it, so the key row commits or rolls back with the business write.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final, Protocol, Self

from domain_kernel.ids import TenantId

REPLAY_WINDOW: Final = timedelta(hours=24)
"""How long a recorded response is replayed, counted from when it was recorded."""
IN_FLIGHT_LEASE: Final = timedelta(minutes=5)
"""How long a claimed key waits for its response before another request may claim it."""
MIN_KEY_LENGTH: Final = 8
MAX_KEY_LENGTH: Final = 128


def fingerprint(method: str, path: str, body: bytes) -> str:
    """The SHA-256 of the method, the path and the body, as 64 hex digits."""
    digest = hashlib.sha256()
    digest.update(method.upper().encode("ascii"))
    digest.update(b"\n")
    digest.update(path.encode("utf-8"))
    digest.update(b"\n")
    digest.update(body)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotencyRequest:
    """A request that carries an idempotency key, as the ``IdempotencyKey`` dependency reads it."""

    key: str
    method: str
    path: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not MIN_KEY_LENGTH <= len(self.key) <= MAX_KEY_LENGTH:
            raise ValueError(
                f"an idempotency key has {MIN_KEY_LENGTH} to {MAX_KEY_LENGTH} characters, "
                f"got {len(self.key)}"
            )
        if len(self.fingerprint) != 64:
            raise ValueError("the fingerprint is a SHA-256 in 64 hex digits")

    @classmethod
    def of(cls, key: str, method: str, path: str, body: bytes) -> Self:
        """The request with the fingerprint of its method, path and body."""
        return cls(key, method.upper(), path, fingerprint(method, path, body))


@dataclass(frozen=True, slots=True)
class StoredResponse:
    """A recorded response: its status, its JSON body and the headers worth replaying."""

    status_code: int
    body: object
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Started:
    """The key is new, or its earlier use expired: this request runs."""


@dataclass(frozen=True, slots=True)
class Replay:
    """The same request finished before: send its response again."""

    response: StoredResponse


@dataclass(frozen=True, slots=True)
class Reused:
    """The key was used for a different request (method, path or body)."""


@dataclass(frozen=True, slots=True)
class InFlight:
    """The same request is still running under this key."""


type Outcome = Started | Replay | Reused | InFlight


class IdempotencyRecorder(Protocol):
    """Claims keys and records what happened to the requests that claimed them."""

    def begin(self, tenant: TenantId, request: IdempotencyRequest) -> Outcome:
        """Claim ``request.key`` for the tenant, or say why this request may not run."""
        ...

    def complete(
        self, tenant: TenantId, request: IdempotencyRequest, response: StoredResponse
    ) -> None:
        """Record the response of a request that claimed its key; it is replayed from now on."""
        ...

    def abandon(self, tenant: TenantId, request: IdempotencyRequest) -> None:
        """Release a claimed key without a response, so the next request with it runs again."""
        ...


class IdempotencyStore(IdempotencyRecorder, Protocol):
    """A recorder that also removes what has expired."""

    def purge_expired(self) -> int:
        """Delete every tenant's expired keys; returns how many went."""
        ...
