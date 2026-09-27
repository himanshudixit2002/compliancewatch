"""Exact-match cache in process memory: a TTL per entry, least recently used eviction."""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

from domain_kernel._validation import require_finite, require_int
from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.providers import ProviderResponse


class MemoryCache:
    """Thread-safe. One process, one cache: a second replica misses what this one holds."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if require_finite(ttl_seconds, "ttl_seconds") <= 0:
            raise InvariantViolationError(f"ttl_seconds must be positive, got {ttl_seconds}")
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = require_int(max_entries, "max_entries", minimum=1)
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[float, ProviderResponse]] = OrderedDict()

    def get(self, key: str) -> ProviderResponse | None:
        """The cached response, or None when absent or expired. A hit counts as recent use."""
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, response = item
            if expires_at <= self._clock():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return response

    def put(self, key: str, response: ProviderResponse) -> None:
        """Store ``response`` for ``ttl_seconds``; the least recently used entries make room."""
        with self._lock:
            self._items[key] = (self._clock() + self.ttl_seconds, response)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
