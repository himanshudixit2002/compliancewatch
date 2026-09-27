"""A circuit breaker per (provider, model): stop calling a host that keeps failing.

Closed until ``threshold`` failures in a row, then open for ``open_seconds``. After that one
probe call is let through (half open): success closes the circuit, failure reopens it.
"""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from domain_kernel._validation import require_finite, require_int
from domain_kernel.errors import InvariantViolationError

BreakerKey = tuple[str, str]
"""``(provider, model)``."""


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(slots=True)
class _Circuit:
    failures: int = 0
    state: BreakerState = BreakerState.CLOSED
    opened_at: float = 0.0


class CircuitBreaker:
    """Thread-safe; the clock is injectable for tests."""

    def __init__(
        self,
        *,
        threshold: int = 3,
        open_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = require_int(threshold, "threshold", minimum=1)
        if require_finite(open_seconds, "open_seconds") <= 0:
            raise InvariantViolationError(f"open_seconds must be positive, got {open_seconds}")
        self.open_seconds = float(open_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._circuits: dict[BreakerKey, _Circuit] = {}

    def state(self, key: BreakerKey) -> BreakerState:
        """The state a call would see now; an open circuit whose wait is over reads half open."""
        with self._lock:
            circuit = self._circuits.get(key)
            if circuit is None:
                return BreakerState.CLOSED
            if circuit.state is BreakerState.OPEN and self._wait_is_over(circuit):
                return BreakerState.HALF_OPEN
            return circuit.state

    def allows(self, key: BreakerKey) -> bool:
        """True when a call may go out. Admits exactly one probe once the open wait is over."""
        with self._lock:
            circuit = self._circuits.get(key)
            if circuit is None or circuit.state is BreakerState.CLOSED:
                return True
            if circuit.state is BreakerState.OPEN and self._wait_is_over(circuit):
                circuit.state = BreakerState.HALF_OPEN
                return True
            return False

    def retry_after(self, key: BreakerKey) -> int | None:
        """Whole seconds until an open circuit admits its probe; None when a call may go out.

        Half open counts as "may go out": the probe decides, so there is no wait to promise.
        """
        with self._lock:
            circuit = self._circuits.get(key)
            if circuit is None or circuit.state is not BreakerState.OPEN:
                return None
            remaining = circuit.opened_at + self.open_seconds - self._clock()
            if remaining <= 0:
                return None
            return max(1, math.ceil(remaining))

    def record_success(self, key: BreakerKey) -> None:
        with self._lock:
            self._circuits.pop(key, None)

    def record_failure(self, key: BreakerKey) -> None:
        with self._lock:
            circuit = self._circuits.setdefault(key, _Circuit())
            circuit.failures += 1
            if circuit.state is BreakerState.HALF_OPEN or circuit.failures >= self.threshold:
                circuit.state = BreakerState.OPEN
                circuit.opened_at = self._clock()

    def _wait_is_over(self, circuit: _Circuit) -> bool:
        return self._clock() >= circuit.opened_at + self.open_seconds
