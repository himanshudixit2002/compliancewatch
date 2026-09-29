"""The numbers the service delivers by, as values the use cases take."""

from dataclasses import dataclass
from datetime import timedelta

from domain_kernel._validation import require_int
from domain_kernel.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How often a failed delivery is tried again, and after how long.

    ``backoff_seconds[n - 1]`` is the wait after the n-th failed attempt; the last value repeats
    when there are more attempts than values. The attempt numbered ``max_attempts`` is the last.
    """

    max_attempts: int = 3
    backoff_seconds: tuple[int, ...] = (60, 300)

    def __post_init__(self) -> None:
        require_int(self.max_attempts, "max_attempts", minimum=1)
        if not self.backoff_seconds:
            raise InvariantViolationError("backoff_seconds needs at least one value")
        for seconds in self.backoff_seconds:
            require_int(seconds, "backoff_seconds", minimum=1)

    def is_final(self, attempts: int) -> bool:
        """True when ``attempts`` failed attempts leave none to make."""
        return attempts >= self.max_attempts

    def backoff(self, attempts: int) -> timedelta:
        """The wait before the attempt after ``attempts`` failed ones."""
        require_int(attempts, "attempts", minimum=1)
        index = min(attempts, len(self.backoff_seconds)) - 1
        return timedelta(seconds=self.backoff_seconds[index])


DEFAULT_RETRY_POLICY = RetryPolicy()

WORK_LEASE = timedelta(seconds=60)
"""How long a dispatcher holds the work it claimed before another may claim it: long enough for
one delivery, retries of its HTTP call included."""
