"""Idempotency keys in memory, for tests, demos and the services' memory mode.

Every call holds one lock, so two routes running in the threadpool cannot both claim a key.
There is no transaction to join: used as a recorder, the store keeps what it was told even if
the caller's own work failed afterwards.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from py_common.idempotency.store import (
    IN_FLIGHT_LEASE,
    REPLAY_WINDOW,
    IdempotencyRequest,
    InFlight,
    Outcome,
    Replay,
    Reused,
    Started,
    StoredResponse,
)


@dataclass(frozen=True, slots=True)
class _Entry:
    request: IdempotencyRequest
    response: StoredResponse | None
    expires_at: datetime


class MemoryIdempotencyStore:
    """An ``IdempotencyStore`` over a dict keyed by tenant and key; ``clock`` decides expiry."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        lease: timedelta = IN_FLIGHT_LEASE,
        window: timedelta = REPLAY_WINDOW,
    ) -> None:
        self._clock = clock
        self._lease = lease
        self._window = window
        self._entries: dict[tuple[TenantId, str], _Entry] = {}
        self._lock = threading.Lock()

    def begin(self, tenant: TenantId, request: IdempotencyRequest) -> Outcome:
        now = self._clock()
        with self._lock:
            entry = self._entries.get((tenant, request.key))
            if entry is None or entry.expires_at <= now:
                self._entries[tenant, request.key] = _Entry(request, None, now + self._lease)
                return Started()
            if entry.request.fingerprint != request.fingerprint:
                return Reused()
            if entry.response is None:
                return InFlight()
            return Replay(entry.response)

    def complete(
        self, tenant: TenantId, request: IdempotencyRequest, response: StoredResponse
    ) -> None:
        with self._lock:
            entry = self._claimed(tenant, request)
            if entry is not None:
                self._entries[tenant, request.key] = replace(
                    entry, response=response, expires_at=self._clock() + self._window
                )

    def abandon(self, tenant: TenantId, request: IdempotencyRequest) -> None:
        with self._lock:
            if self._claimed(tenant, request) is not None:
                del self._entries[tenant, request.key]

    def purge_expired(self) -> int:
        now = self._clock()
        with self._lock:
            expired = [name for name, entry in self._entries.items() if entry.expires_at < now]
            for name in expired:
                del self._entries[name]
        return len(expired)

    def __len__(self) -> int:
        return len(self._entries)

    def _claimed(self, tenant: TenantId, request: IdempotencyRequest) -> _Entry | None:
        """The entry ``request`` claimed and has not recorded yet; None once another request
        took the key over after the lease ran out."""
        entry = self._entries.get((tenant, request.key))
        if entry is None or entry.response is not None:
            return None
        if entry.request.fingerprint != request.fingerprint:
            return None
        return entry
