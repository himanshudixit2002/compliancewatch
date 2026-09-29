"""The numbers the service delivers by, as values the use cases take: how often a delivery is
retried, and how notifications are gathered into a summary."""

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


MIN_PARAM_CHARS = 40
"""Room for one short line and its 'and N more' tail."""


@dataclass(frozen=True, slots=True)
class BatchPolicy:
    """How notifications to one person are gathered into one message.

    A notification waits ``window_seconds`` before it goes out, and the ones queued for the same
    person, channel and business meanwhile go with it as one summary. A summary lists at most
    ``max_lines`` lines, and its list stays within ``max_param_chars`` characters, below the
    size Meta accepts for one template parameter; what does not fit is counted as
    'and N more'.
    """

    window_seconds: int = 300
    max_lines: int = 10
    max_param_chars: int = 900

    def __post_init__(self) -> None:
        require_int(self.window_seconds, "window_seconds", minimum=0)
        require_int(self.max_lines, "max_lines", minimum=1)
        require_int(self.max_param_chars, "max_param_chars", minimum=MIN_PARAM_CHARS)

    @property
    def window(self) -> timedelta:
        return timedelta(seconds=self.window_seconds)


DEFAULT_BATCH_POLICY = BatchPolicy()

WORK_LEASE = timedelta(seconds=60)
"""How long a dispatcher holds the work it claimed before another may claim it: long enough for
one delivery, retries of its HTTP call included."""
