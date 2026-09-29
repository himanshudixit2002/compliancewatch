"""OpenTelemetry instruments of delivery, the series the notification alerts read
(``docs/runbooks/notification-delivery.md``):

- ``notification_sends_total{channel, outcome}``: one per attempt, by what it made of the
  notification: ``sent``, ``retry`` (failed, another follows), ``failed`` (the last one failed)
  or ``suppressed`` (the address closed before it went out);
- ``notification_delivery_lag_seconds{channel}``: seconds from the moment a notification was
  due to the moment the channel took it, so the batching window and quiet hours, which move
  that moment, are not counted as delay;
- ``notification_duplicate_sent_total{channel}``: a delivery of a notification that had already
  been sent, which only a dispatcher whose lease ran out mid-send can cause, and which should
  never happen;
- ``notification_enqueued_total{channel, outcome}``: notifications queued, and ``duplicate`` for
  an occasion that already had its notification (a redelivered event), which is expected;
- ``notification_receipts_total{channel, kind, outcome}``: provider reports after a message was
  taken (``delivered``, ``read``, ``failed`` and so on) by what they made of it: ``applied``,
  ``unchanged`` (late or repeated) or ``unknown`` (no notification carries the message id, such
  as the bot's own replies).

The names carry no unit, since the collector's Prometheus exporter would add one; counters end in
``_total`` as Prometheus names them. Without telemetry configured the global meter provider
records nothing, so the instruments are always wired.
"""

from opentelemetry import metrics
from opentelemetry.metrics import Meter

from domain_kernel.channels import Channel
from notification.domain.ports import AttemptResult, QueueResult, ReceiptResult
from notification.domain.receipts import ReceiptKind

SENDS = "notification_sends_total"
DELIVERY_LAG = "notification_delivery_lag_seconds"
DUPLICATE_SENT = "notification_duplicate_sent_total"
ENQUEUED = "notification_enqueued_total"
RECEIPTS = "notification_receipts_total"
LAG_BUCKETS = (1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1800.0, 3600.0, 21600.0)
"""Seconds; 900 is the 15-minute delivery objective."""


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
