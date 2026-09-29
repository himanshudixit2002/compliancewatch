"""What the service needs from outside itself, other than its store: the rulebook's facts of a
rule version, and a place to count deliveries.

- ``RuleVersionReader.get(rule_version_id)``: the published facts a message states about a rule
  (its title, plain-language summary, the date it is in force from, the steps and the source it
  cites); None when the rulebook has no such version. A rulebook that cannot answer raises
  ``DependencyUnavailableError``, and the dispatcher tries again later without spending an
  attempt.
- ``DeliveryMetrics``: the counters and the lag the alerts read. ``NO_METRICS`` counts nothing.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from domain_kernel._validation import require_date, require_instance, require_text
from domain_kernel.channels import Channel
from domain_kernel.ids import RuleVersionId


@dataclass(frozen=True, slots=True)
class RuleVersionFacts:
    title: str
    summary: str
    effective_from: date
    steps: tuple[str, ...] = ()
    source_ref: str = ""
    """What the rule cites, such as 'CGST Rules, 2017, rule 61(1)'; '' when it cites nothing."""

    def __post_init__(self) -> None:
        require_text(self.title, "title")
        require_instance(self.summary, str, "summary")
        require_date(self.effective_from, "effective_from")
        steps: Sequence[object] = tuple(self.steps)
        for step in steps:
            require_text(step, "steps")
        object.__setattr__(self, "steps", steps)
        require_instance(self.source_ref, str, "source_ref")


class RuleVersionReader(Protocol):
    def get(self, rule_version_id: RuleVersionId) -> RuleVersionFacts | None: ...


class AttemptResult(StrEnum):
    """What one attempt made of a notification, as ``notification_sends_total`` counts it."""

    SENT = "sent"
    RETRY = "retry"
    """The attempt failed and another follows."""
    FAILED = "failed"
    """The last attempt failed."""
    SUPPRESSED = "suppressed"
    """Not sent: the address was closed after the notification was queued."""


class QueueResult(StrEnum):
    QUEUED = "queued"
    DUPLICATE = "duplicate"
    """The occasion already has its notification; nothing was queued."""


class DeliveryMetrics(Protocol):
    def enqueued(self, channel: Channel, result: QueueResult) -> None: ...

    def attempted(self, channel: Channel, result: AttemptResult) -> None: ...

    def delivery_lag(self, channel: Channel, seconds: float) -> None:
        """Seconds from the moment a notification was due to the moment the channel took it."""
        ...

    def duplicate_sent(self, channel: Channel) -> None:
        """A delivery of a notification that had already been sent, such as after a
        dispatcher's lease ran out while it was still sending."""
        ...


class NoMetrics:
    def enqueued(self, channel: Channel, result: QueueResult) -> None:
        return None

    def attempted(self, channel: Channel, result: AttemptResult) -> None:
        return None

    def delivery_lag(self, channel: Channel, seconds: float) -> None:
        return None

    def duplicate_sent(self, channel: Channel) -> None:
        return None


NO_METRICS = NoMetrics()
