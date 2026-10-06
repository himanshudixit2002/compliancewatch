"""The open-tasks gauge, read through an in-memory metric reader, and when the app registers it."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from structlog.testing import capture_logs

from pipeline.domain.tasks import TaskKind
from pipeline.infrastructure.task_metrics import OPEN_TASKS, OpenTaskGauge, register_task_gauge
from pipeline.main import build_app, install_task_metrics
from pipeline.testing import pipeline_settings
from py_common.telemetry import Telemetry

T0 = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def points(reader: InMemoryMetricReader) -> dict[str, float]:
    data = reader.get_metrics_data()
    found: dict[str, float] = {}
    if data is None:
        return found
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != OPEN_TASKS:
                    continue
                for point in metric.data.data_points:
                    assert isinstance(point, NumberDataPoint)
                    assert point.attributes is not None
                    found[str(point.attributes["kind"])] = point.value
    return found


def test_every_kind_is_reported_zero_when_none_is_open() -> None:
    reader = InMemoryMetricReader()
    counts: dict[TaskKind, int] = {TaskKind.MANUAL_PARSE: 3}
    register_task_gauge(lambda: counts, Clock(), MeterProvider([reader]).get_meter("test"))
    assert points(reader) == {"manual_parse": 3, "triage": 0}


def test_one_reading_serves_the_cache_window_and_a_failed_read_reports_nothing() -> None:
    clock = Clock()
    reads: list[int] = []
    failing = False

    def read() -> Mapping[TaskKind, int]:
        reads.append(1)
        if failing:
            raise ConnectionError("the database is away")
        return {TaskKind.TRIAGE: 1}

    gauge = OpenTaskGauge(read, clock)
    assert gauge.counts() == {TaskKind.MANUAL_PARSE: 0, TaskKind.TRIAGE: 1}
    gauge.counts()
    assert len(reads) == 1
    failing = True
    clock.now = T0 + timedelta(seconds=31)
    with capture_logs() as logs:
        assert gauge.counts() is None
    assert logs[0]["event"] == "task_metrics.read_failed"
    assert list(gauge.observe(None)) == []  # type: ignore[arg-type]


def test_the_app_registers_the_gauge_only_with_telemetry_on() -> None:
    app = build_app(pipeline_settings())
    assert install_task_metrics(app, app.state.wiring) is False, "telemetry is off"
    reader = InMemoryMetricReader()
    app.state.telemetry = Telemetry(
        enabled=True,
        service_name="pipeline",
        endpoint="http://collector.invalid:4317",
        meter_provider=MeterProvider([reader]),
    )
    assert install_task_metrics(app, app.state.wiring) is True
    assert points(reader) == {"manual_parse": 0, "triage": 0}
