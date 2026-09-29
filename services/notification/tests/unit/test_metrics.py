from datetime import datetime, timedelta
from typing import Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from structlog.testing import capture_logs

from domain_kernel.channels import Channel
from notification.domain.ports import NO_METRICS, AttemptResult, QueueResult, ReceiptResult
from notification.domain.receipts import ReceiptKind
from notification.infrastructure.metrics import (
    DELIVERY_LAG,
    DUPLICATE_SENT,
    ENQUEUED,
    PENDING_AGE,
    RECEIPTS,
    SENDS,
    OtelDeliveryMetrics,
    PendingAgeGauge,
    register_pending_age_gauge,
)
from notification.main import build_app, install_pending_metrics
from notification.testing import NOON_IST, FakeClock, notification_settings
from py_common.telemetry import Telemetry


def points(reader: InMemoryMetricReader) -> dict[str, list[Any]]:
    data = reader.get_metrics_data()
    assert data is not None
    found: dict[str, list[Any]] = {}
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                found[metric.name] = list(metric.data.data_points)
    return found


def test_the_instruments_carry_the_names_and_labels_the_alerts_read() -> None:
    reader = InMemoryMetricReader()
    metrics = OtelDeliveryMetrics(MeterProvider(metric_readers=[reader]).get_meter("test"))
    metrics.enqueued(Channel.WHATSAPP, QueueResult.QUEUED)
    metrics.enqueued(Channel.WHATSAPP, QueueResult.DUPLICATE)
    metrics.attempted(Channel.WHATSAPP, AttemptResult.SENT)
    metrics.attempted(Channel.EMAIL, AttemptResult.FAILED)
    metrics.attempted(Channel.WHATSAPP, AttemptResult.RESCHEDULED)
    metrics.delivery_lag(Channel.WHATSAPP, 42.0)
    metrics.duplicate_sent(Channel.EMAIL)
    metrics.receipt(Channel.WHATSAPP, ReceiptKind.READ, ReceiptResult.APPLIED)
    found = points(reader)
    sends = {(p.attributes["channel"], p.attributes["outcome"]): p.value for p in found[SENDS]}
    assert sends == {
        ("whatsapp", "sent"): 1,
        ("email", "failed"): 1,
        ("whatsapp", "rescheduled"): 1,
    }
    enqueued = {p.attributes["outcome"] for p in found[ENQUEUED]}
    assert enqueued == {"queued", "duplicate"}
    (lag,) = found[DELIVERY_LAG]
    assert (lag.count, lag.sum, lag.attributes) == (1, 42.0, {"channel": "whatsapp"})
    assert 900.0 in lag.explicit_bounds
    (duplicate,) = found[DUPLICATE_SENT]
    assert (duplicate.value, duplicate.attributes) == (1, {"channel": "email"})
    (receipt,) = found[RECEIPTS]
    assert receipt.attributes == {"channel": "whatsapp", "kind": "read", "outcome": "applied"}


def test_no_metrics_counts_nothing() -> None:
    NO_METRICS.enqueued(Channel.EMAIL, QueueResult.QUEUED)
    NO_METRICS.attempted(Channel.EMAIL, AttemptResult.RETRY)
    NO_METRICS.delivery_lag(Channel.EMAIL, 1.0)
    NO_METRICS.duplicate_sent(Channel.EMAIL)
    NO_METRICS.receipt(Channel.EMAIL, ReceiptKind.BOUNCED, ReceiptResult.UNKNOWN)
    OtelDeliveryMetrics().attempted(Channel.EMAIL, AttemptResult.SUPPRESSED)


def gauge_value(reader: InMemoryMetricReader) -> list[float]:
    return [point.value for point in points(reader).get(PENDING_AGE, [])]


def test_the_pending_age_counts_from_the_oldest_planned_moment_and_moves_with_the_clock() -> None:
    clock = FakeClock(NOON_IST)
    reads: list[datetime] = []
    oldest: list[datetime | None] = [NOON_IST - timedelta(minutes=20)]

    def oldest_due(now: datetime) -> datetime | None:
        reads.append(now)
        return oldest[0]

    reader = InMemoryMetricReader()
    register_pending_age_gauge(
        oldest_due, clock, MeterProvider(metric_readers=[reader]).get_meter("t")
    )
    assert gauge_value(reader) == [1200.0]
    clock.advance(29)
    oldest[0] = None
    assert gauge_value(reader) == [1229.0], "one reading serves 30 seconds"
    clock.advance(1)
    assert gauge_value(reader) == [0.0], "nothing waits past its moment"
    assert reads == [NOON_IST, NOON_IST + timedelta(seconds=30)]


def test_a_failed_read_reports_nothing_until_the_next_read() -> None:
    clock = FakeClock(NOON_IST)
    failures = [RuntimeError("database unavailable")]

    def oldest_due(now: datetime) -> datetime | None:
        if failures:
            raise failures.pop()
        return now

    gauge = PendingAgeGauge(oldest_due, clock)
    with capture_logs() as logs:
        assert gauge.age_seconds() is None
    assert [entry["event"] for entry in logs] == ["notification.pending_age_read_failed"]
    clock.advance(30)
    assert gauge.age_seconds() == 0.0


def test_the_app_registers_the_pending_age_gauge_only_when_telemetry_is_on() -> None:
    app = build_app(notification_settings())
    assert app.state.telemetry.enabled is False
    assert install_pending_metrics(app, app.state.wiring) is False

    reader = InMemoryMetricReader()
    app.state.telemetry = Telemetry(
        enabled=True,
        service_name="notification",
        endpoint="http://collector:4317",
        meter_provider=MeterProvider(metric_readers=[reader]),
    )
    assert install_pending_metrics(app, app.state.wiring) is True
    assert gauge_value(reader) == [0.0], "an empty queue"
