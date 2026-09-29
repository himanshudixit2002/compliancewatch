"""The numbers the service delivers by, as values the use cases take: how often a delivery is
retried, how notifications are gathered into a summary, when the daily digest goes out, and how
long notifications are kept."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from domain_kernel._validation import require_aware, require_instance, require_int
from domain_kernel.errors import InvariantViolationError
from notification.domain.preferences import IST


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

DIGEST_AT = time(9, 0)
"""09:00 IST: the start of the working day, after the default quiet hours end."""


@dataclass(frozen=True, slots=True)
class DigestPolicy:
    """When the daily digest goes out: once a day at ``at``, a wall-clock time in IST.

    A notification for a recipient who hears by digest waits for the next digest time after it
    was queued (``next_at``), and every notification waiting for that recipient then goes out as
    one message.
    """

    at: time = DIGEST_AT

    def __post_init__(self) -> None:
        require_instance(self.at, time, "at")
        if self.at.tzinfo is not None:
            raise InvariantViolationError("the digest time is a wall-clock time in IST")

    @classmethod
    def parse(cls, at: str) -> "DigestPolicy":
        """The policy of an ``HH:MM`` text; anything else is an invariant violation."""
        try:
            return cls(time.fromisoformat(at))
        except ValueError as exc:
            raise InvariantViolationError(f"the digest time must be HH:MM, got {at!r}") from exc

    def next_at(self, now: datetime) -> datetime:
        """The first digest time after ``now``: today's in IST, or tomorrow's once it passed."""
        local = require_aware(now, "now").astimezone(IST)
        due = local.replace(
            hour=self.at.hour, minute=self.at.minute, second=self.at.second, microsecond=0
        )
        if due <= local:
            due += timedelta(days=1)
        return due.astimezone(now.tzinfo)


DEFAULT_DIGEST_POLICY = DigestPolicy()


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """How long notifications are kept (guide section 9, docs/legal/data-map.md).

    The record of a notification (who, which occasion, on which channel, when it was sent,
    delivered or read, and its dedupe key) is kept for ``keep_days``, two years, so that a
    dispute about a missed reminder can be answered. The values its message was filled with (a
    title, a date, a business's label) are emptied after ``params_days``, 30, once the
    notification has gone out or ended; a notification still waiting keeps them, since it
    cannot go out without them.
    """

    keep_days: int = 730
    params_days: int = 30

    def __post_init__(self) -> None:
        require_int(self.keep_days, "keep_days", minimum=1)
        require_int(self.params_days, "params_days", minimum=1)
        if self.params_days > self.keep_days:
            raise InvariantViolationError("params_days cannot be longer than keep_days")

    def purge_before(self, now: datetime) -> datetime:
        """Notifications created before this moment are deleted."""
        return require_aware(now, "now") - timedelta(days=self.keep_days)

    def strip_before(self, now: datetime) -> datetime:
        """Notifications created before this moment lose their template values."""
        return require_aware(now, "now") - timedelta(days=self.params_days)


DEFAULT_RETENTION_POLICY = RetentionPolicy()

WORK_LEASE = timedelta(seconds=60)
"""How long a dispatcher holds the work it claimed before another may claim it. The dispatcher
renews it just before each message it sends, so it has to cover one delivery: the channels'
client timeouts (20 seconds for SMTP, 30 for the Graph API) stay below it."""
