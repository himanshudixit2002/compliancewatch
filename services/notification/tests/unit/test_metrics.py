from typing import Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from domain_kernel.channels import Channel
from notification.domain.ports import NO_METRICS, AttemptResult, QueueResult
from notification.infrastructure.metrics import (
    DELIVERY_LAG,
    DUPLICATE_SENT,
    ENQUEUED,
    SENDS,
    OtelDeliveryMetrics,
)


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
    metrics.delivery_lag(Channel.WHATSAPP, 42.0)
    metrics.duplicate_sent(Channel.EMAIL)
    found = points(reader)
    sends = {(p.attributes["channel"], p.attributes["outcome"]): p.value for p in found[SENDS]}
    assert sends == {("whatsapp", "sent"): 1, ("email", "failed"): 1}
    enqueued = {p.attributes["outcome"] for p in found[ENQUEUED]}
    assert enqueued == {"queued", "duplicate"}
    (lag,) = found[DELIVERY_LAG]
    assert (lag.count, lag.sum, lag.attributes) == (1, 42.0, {"channel": "whatsapp"})
    assert 900.0 in lag.explicit_bounds
    (duplicate,) = found[DUPLICATE_SENT]
    assert (duplicate.value, duplicate.attributes) == (1, {"channel": "email"})


def test_no_metrics_counts_nothing() -> None:
    NO_METRICS.enqueued(Channel.EMAIL, QueueResult.QUEUED)
    NO_METRICS.attempted(Channel.EMAIL, AttemptResult.RETRY)
    NO_METRICS.delivery_lag(Channel.EMAIL, 1.0)
    NO_METRICS.duplicate_sent(Channel.EMAIL)
    OtelDeliveryMetrics().attempted(Channel.EMAIL, AttemptResult.SUPPRESSED)
