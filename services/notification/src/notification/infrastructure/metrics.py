"""OpenTelemetry instruments of delivery, the series the notification alerts read
(``docs/runbooks/notification-delivery.md``):

- ``notification_sends_total{channel, outcome}``: one per notification each time the
  dispatcher takes it up, by what it made of it: ``sent``, ``retry`` (failed, another follows),
  ``failed`` (the last one failed), ``suppressed`` (the address closed before it went out) or
  ``rescheduled`` (the rulebook could not fill it: due again a minute later, no attempt spent);
- ``notification_delivery_lag_seconds{channel}``: seconds from the moment a notification was
  planned to go out to the moment the channel took it. The batching window, the digest time
  and quiet hours set that moment, so they are not delay; retries and rulebook outages do not
  move it, so they are;
- ``notification_duplicate_sent_total{channel}``: a delivery of a notification that had already
  been sent, which only a delivery that outlasted its whole lease can cause, and which should
  never happen;
- ``notification_enqueued_total{channel, outcome}``: notifications queued, and ``duplicate`` for
  an occasion that already had its notification (a redelivered event), which is expected;
- ``notification_receipts_total{channel, kind, outcome}``: provider reports after a message was
  taken (``delivered``, ``read``, ``failed`` and so on) by what they made of it: ``applied``,
  ``unchanged`` (late or repeated) or ``unknown`` (no notification carries the message id, such
  as the bot's own replies);
- ``notification_pending_oldest_age_seconds``: seconds since the pending notification that has
  waited longest was planned to go out, 0 when none waits past its moment
  (``WorkIndex.oldest_due``). An observable gauge the API process registers
  (``register_pending_age_gauge``), so it reports while no worker runs; one reading of the
  work index serves ``PENDING_CACHE_SECONDS``, and a failed read reports nothing until the
  next one, so the alert sees a gap rather than a false zero.

The names carry no unit, since the collector's Prometheus exporter would add one; counters end in
``_total`` as Prometheus names them. Without telemetry configured the global meter provider
records nothing, so the instruments are always wired.
"""

import threading
from collections.abc import Callable, Iterable
from datetime import datetime

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Meter, Observation

from domain_kernel.channels import Channel
from notification.domain.ports import AttemptResult, QueueResult, ReceiptResult
from notification.domain.receipts import ReceiptKind
from py_common.logging import get_logger

SENDS = "notification_sends_total"
DELIVERY_LAG = "notification_delivery_lag_seconds"
DUPLICATE_SENT = "notification_duplicate_sent_total"
ENQUEUED = "notification_enqueued_total"
RECEIPTS = "notification_receipts_total"
PENDING_AGE = "notification_pending_oldest_age_seconds"
PENDING_CACHE_SECONDS = 30.0
LAG_BUCKETS = (1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1800.0, 3600.0, 21600.0)
"""Seconds; 900 is the 15-minute delivery objective."""

log = get_logger(__name__)


class OtelDeliveryMetrics:
    def __init__(self, meter: Meter | None = None) -> None:
        meter = meter or metrics.get_meter("notification")
        self._sends = meter.create_counter(
            SENDS, description="Delivery attempts by channel and what they made of the notification"
        )
        self._lag = meter.create_histogram(
            DELIVERY_LAG,
            description="Seconds from a notification being due to the channel taking it",
            explicit_bucket_boundaries_advisory=LAG_BUCKETS,
        )
        self._duplicate_sent = meter.create_counter(
            DUPLICATE_SENT, description="Deliveries of a notification that was already sent"
        )
        self._enqueued = meter.create_counter(
            ENQUEUED, description="Notifications queued, and duplicates the dedupe key caught"
        )
        self._receipts = meter.create_counter(
            RECEIPTS, description="Provider reports by kind and what they made of the notification"
        )

    def enqueued(self, channel: Channel, result: QueueResult) -> None:
        self._enqueued.add(1, {"channel": channel.value, "outcome": result.value})

    def attempted(self, channel: Channel, result: AttemptResult) -> None:
        self._sends.add(1, {"channel": channel.value, "outcome": result.value})

    def delivery_lag(self, channel: Channel, seconds: float) -> None:
        self._lag.record(seconds, {"channel": channel.value})

    def duplicate_sent(self, channel: Channel) -> None:
        self._duplicate_sent.add(1, {"channel": channel.value})

    def receipt(self, channel: Channel, kind: ReceiptKind, result: ReceiptResult) -> None:
        self._receipts.add(
            1, {"channel": channel.value, "kind": kind.value, "outcome": result.value}
        )


class PendingAgeGauge:
    """The callback of ``notification_pending_oldest_age_seconds``. ``oldest_due(now)`` is the
    work index's reading; it is read again once it is ``cache_seconds`` old, and the age moves
    with the clock in between."""

    def __init__(
        self,
        oldest_due: Callable[[datetime], datetime | None],
        clock: Callable[[], datetime],
        *,
        cache_seconds: float = PENDING_CACHE_SECONDS,
    ) -> None:
        self._oldest_due = oldest_due
        self._clock = clock
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._read_at: datetime | None = None
        self._read_ok = False
        self._oldest: datetime | None = None

    def age_seconds(self) -> float | None:
        """Seconds since the oldest pending notification was planned to go out; 0 when none
        waits past its moment; None after a failed read."""
        now = self._clock()
        with self._lock:
            if self._read_at is None or (
                (now - self._read_at).total_seconds() >= self._cache_seconds
            ):
                self._read_at = now
                try:
                    self._oldest, self._read_ok = self._oldest_due(now), True
                except Exception as exc:
                    self._oldest, self._read_ok = None, False
                    log.warning(
                        "notification.pending_age_read_failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
            if not self._read_ok:
                return None
            if self._oldest is None:
                return 0.0
            return max((now - self._oldest).total_seconds(), 0.0)

    def observe(self, _: CallbackOptions) -> Iterable[Observation]:
        age = self.age_seconds()
        return [] if age is None else [Observation(age)]


def register_pending_age_gauge(
    oldest_due: Callable[[datetime], datetime | None],
    clock: Callable[[], datetime],
    meter: Meter,
) -> PendingAgeGauge:
    """Register ``notification_pending_oldest_age_seconds`` on ``meter``; the composition root
    calls this only when telemetry is on."""
    gauge = PendingAgeGauge(oldest_due, clock)
    meter.create_observable_gauge(
        PENDING_AGE,
        callbacks=[gauge.observe],
        description="Seconds the oldest pending notification has waited past its planned moment",
    )
    return gauge
