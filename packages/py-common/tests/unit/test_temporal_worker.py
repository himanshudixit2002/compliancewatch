import asyncio
from collections.abc import Iterator
from typing import Any, cast

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint
from temporalio.client import Client

from py_common.settings import Settings
from py_common.temporal import liveness
from py_common.temporal import worker as worker_module
from py_common.temporal.worker import WorkerConfig, run_worker


def test_worker_config_defaults_and_checks() -> None:
    config = WorkerConfig(task_queue="pipeline")
    assert config.max_concurrent_activities == 20
    assert config.max_concurrent_workflow_tasks == 20
    with pytest.raises(ValueError, match="task_queue"):
        WorkerConfig(task_queue=" ")
    with pytest.raises(ValueError, match="at least 1"):
        WorkerConfig(task_queue="q", max_concurrent_activities=0)


@pytest.fixture
def reader() -> Iterator[InMemoryMetricReader]:
    """A meter provider of the test's own with the liveness gauge on it; the registry behind
    the gauge is the module's, so it sees what ``run_worker`` records."""
    metric_reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[metric_reader])
    liveness.register(provider.get_meter("test"))
    yield metric_reader
    provider.shutdown()


def reported(reader: InMemoryMetricReader) -> set[tuple[str, int | float]]:
    """(task_queue, value) for every temporal_worker_up point of one collection."""
    data = reader.get_metrics_data()
    points: set[tuple[str, int | float]] = set()
    for resource in [] if data is None else data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != liveness.METRIC_NAME:
                    continue
                for point in metric.data.data_points:
                    assert isinstance(point, NumberDataPoint)
                    queue = point.attributes[liveness.QUEUE_ATTRIBUTE] if point.attributes else ""
                    points.add((str(queue), point.value))
    return points


class FakeWorker:
    """Stands in for ``temporalio.worker.Worker``: an async context that starts and stops."""

    def __init__(self, task_queue: str, started: dict[str, asyncio.Event]) -> None:
        self.task_queue = task_queue
        self.started = started

    async def __aenter__(self) -> "FakeWorker":
        self.started[self.task_queue].set()
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> dict[str, asyncio.Event]:
    events: dict[str, asyncio.Event] = {}

    def build(client: Client, config: WorkerConfig, **_: Any) -> FakeWorker:
        events.setdefault(config.task_queue, asyncio.Event())
        return FakeWorker(config.task_queue, events)

    monkeypatch.setattr(worker_module, "build_worker", build)
    monkeypatch.setattr(worker_module, "install_stop_signals", lambda stop: None)
    return events


def start(queue: str, stop: asyncio.Event, started: dict[str, asyncio.Event]) -> asyncio.Task[None]:
    started.setdefault(queue, asyncio.Event())
    return asyncio.create_task(
        run_worker(
            Settings(_env_file=None),
            WorkerConfig(task_queue=queue),
            workflows=[],
            activities=[],
            stop=stop,
            client=cast(Client, object()),
        )
    )


async def test_the_gauge_reports_a_queue_while_run_worker_runs(
    reader: InMemoryMetricReader, started: dict[str, asyncio.Event]
) -> None:
    assert reported(reader) == set()
    stop = asyncio.Event()
    task = start("pipeline", stop, started)
    await started["pipeline"].wait()
    assert liveness.running_queues() == ("pipeline",)
    assert reported(reader) == {("pipeline", 1)}
    stop.set()
    await task
    assert liveness.running_queues() == ()
    assert reported(reader) == set()


async def test_two_queues_in_one_process_report_two_series(
    reader: InMemoryMetricReader, started: dict[str, asyncio.Event]
) -> None:
    stop_pipeline, stop_rulebook = asyncio.Event(), asyncio.Event()
    tasks = [start("pipeline", stop_pipeline, started), start("rulebook", stop_rulebook, started)]
    await asyncio.gather(started["pipeline"].wait(), started["rulebook"].wait())
    assert reported(reader) == {("pipeline", 1), ("rulebook", 1)}
    stop_pipeline.set()
    await tasks[0]
    assert reported(reader) == {("rulebook", 1)}
    stop_rulebook.set()
    await tasks[1]
    assert reported(reader) == set()


async def test_a_worker_that_fails_stops_reporting(
    reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingWorker:
        async def __aenter__(self) -> "FailingWorker":
            assert liveness.running_queues() == ("pipeline",)
            raise RuntimeError("namespace not found")

        async def __aexit__(self, *exc: object) -> None:
            return None  # pragma: no cover - never entered

    monkeypatch.setattr(worker_module, "build_worker", lambda *a, **k: FailingWorker())
    monkeypatch.setattr(worker_module, "install_stop_signals", lambda stop: None)
    with pytest.raises(RuntimeError, match="namespace not found"):
        await run_worker(
            Settings(_env_file=None),
            WorkerConfig(task_queue="pipeline"),
            workflows=[],
            activities=[],
            stop=asyncio.Event(),
            client=cast(Client, object()),
        )
    assert liveness.running_queues() == ()
    assert reported(reader) == set()


def test_two_workers_on_one_queue_keep_it_up_until_the_last_leaves(
    reader: InMemoryMetricReader,
) -> None:
    with liveness.running("pipeline"):
        with liveness.running("pipeline"):
            assert reported(reader) == {("pipeline", 1)}
        assert liveness.running_queues() == ("pipeline",)
    assert liveness.running_queues() == ()
    assert reported(reader) == set()


def test_a_blank_queue_is_refused() -> None:
    with pytest.raises(ValueError, match="task_queue"), liveness.running("  "):
        pass  # pragma: no cover - never entered
