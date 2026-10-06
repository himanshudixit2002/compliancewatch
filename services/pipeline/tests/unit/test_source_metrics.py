"""The freshness gauges, read through an in-memory metric reader, and when the app registers
them."""

from datetime import UTC, datetime, timedelta
from typing import Any

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from structlog.testing import capture_logs

from pipeline.domain.sources import Source
from pipeline.infrastructure.source_metrics import (
    CADENCE,
    FRESHNESS,
    SourceFreshnessGauges,
    register_source_gauges,
)
from pipeline.main import build_app, install_source_metrics
from pipeline.testing import pipeline_settings
from py_common.telemetry import Telemetry

T0 = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def source(key: str, **overrides: Any) -> Source:
    values: dict[str, Any] = {
        "key": key,
        "adapter_type": "gstn",
        "parameters": {},
        "cadence": timedelta(hours=3),
        "created_at": T0 - timedelta(days=2),
        "updated_at": T0 - timedelta(days=2),
    }
    values.update(overrides)
    return Source(**values)


def points(reader: InMemoryMetricReader, name: str) -> dict[str, float]:
    data = reader.get_metrics_data()
    assert data is not None
    found: dict[str, float] = {}
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != name:
                    continue
                for point in metric.data.data_points:
                    assert isinstance(point, NumberDataPoint)
                    assert point.attributes is not None
                    found[str(point.attributes["source"])] = point.value
    return found


def test_the_gauges_report_each_crawled_sources_age_and_cadence() -> None:
    clock, reader = Clock(), InMemoryMetricReader()
    sources = [
        source("gstn_advisories", last_fetch_at=T0 - timedelta(hours=1)),
        source("never_listed"),
        source("paused_one", paused=True),
        source("disabled_one", enabled=False),
    ]
    register_source_gauges(lambda: sources, clock, MeterProvider([reader]).get_meter("test"))
    assert points(reader, FRESHNESS) == {
        "gstn_advisories": 3600,
        "never_listed": 2 * 86400,
    }
    assert points(reader, CADENCE) == {"gstn_advisories": 10800, "never_listed": 10800}


def test_one_reading_serves_both_gauges_and_a_failed_read_reports_nothing() -> None:
    clock, reads = Clock(), [0]

    def read() -> list[Source]:
        reads[0] += 1
        if reads[0] == 2:
            raise RuntimeError("the database is away")
        return [source("gstn_advisories")]

    gauges = SourceFreshnessGauges(read, clock, cache_seconds=30)
    assert gauges.sources() is not None
    assert gauges.sources() is not None
    assert reads == [1]
    clock.now += timedelta(seconds=31)
    with capture_logs() as logs:
        assert gauges.sources() is None
    assert logs[0]["event"] == "source_metrics.read_failed"
    assert list(gauges.freshness(None)) == []  # type: ignore[arg-type]
    assert list(gauges.cadence(None)) == []  # type: ignore[arg-type]


def telemetry(reader: InMemoryMetricReader) -> Telemetry:
    return Telemetry(
        enabled=True,
        service_name="pipeline",
        endpoint="http://collector.invalid:4317",
        meter_provider=MeterProvider([reader]),
    )


def test_the_app_registers_the_gauges_only_with_telemetry_and_crawling_on() -> None:
    app = build_app(pipeline_settings(pipeline_crawl_enabled=True))
    assert install_source_metrics(app, app.state.wiring) is False, "telemetry is off"
    reader = InMemoryMetricReader()
    app.state.telemetry = telemetry(reader)
    assert install_source_metrics(app, app.state.wiring) is True
    assert len(points(reader, FRESHNESS)) == 5, "the built-in sources that are crawled"
    off = build_app(pipeline_settings())
    off.state.telemetry = telemetry(InMemoryMetricReader())
    assert install_source_metrics(off, off.state.wiring) is False
