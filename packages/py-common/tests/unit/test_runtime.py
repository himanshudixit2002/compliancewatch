"""Worker components and the loop that runs them, without a broker or a database."""

import asyncio
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import Engine
from temporalio import workflow
from temporalio.client import Client

from py_common import runtime
from py_common.outbox.consumer import ConsumerConfig
from py_common.outbox.store import ProcessedStore, UnitOfWork
from py_common.outbox.sync import sync_store
from py_common.outbox.testing import MemoryProcessedStore
from py_common.runtime import (
    IST,
    ComponentRegistry,
    ConsumerComponent,
    LifecycleHook,
    PeriodicComponent,
    RelayComponent,
    TaskComponent,
    TemporalComponent,
    WorkerComponents,
    daily_at,
    loop_running,
    register_loop_gauge,
    run_components,
    run_registry,
    run_temporal,
    run_worker_process,
    running_loops,
    serve,
)
from py_common.settings import Settings
from py_common.temporal.liveness import running_queues
from py_common.temporal.worker import WorkerConfig

SETTINGS = Settings(_env_file=None, service_name="runtime-test")


async def handler(message: object, unit: UnitOfWork) -> None:
    return None


def consumer(group_id: str = "notification.obligations") -> ConsumerComponent:
    return ConsumerComponent(group_id, ("obligation.created", "obligation.closed"), handler)


def test_a_consumer_group_is_named_service_dot_purpose() -> None:
    component = consumer()
    assert component.name == "consumer:notification.obligations"
    assert component.dead_letter_topics() == (
        "obligation.created.notification.obligations.dlq",
        "obligation.closed.notification.obligations.dlq",
    )
    for bad in ("notification", "Notification.obligations", "notification.", ".obligations"):
        with pytest.raises(ValueError, match=r"<service>\.<purpose>"):
            consumer(bad)
    with pytest.raises(ValueError, match="at least one topic"):
        ConsumerComponent("notification.obligations", (), handler)


def test_components_add_up_and_names_are_unique() -> None:
    first = WorkerComponents(consumers=(consumer(),), relays=(RelayComponent(),))
    second = WorkerComponents(
        periodic=(PeriodicComponent("dispatch", lambda: None, interval_seconds=5),)
    )
    both = first + second
    assert [component.name for component in both.all()] == [
        "consumer:notification.obligations",
        "outbox-relay",
        "dispatch",
    ]
    with pytest.raises(ValueError, match="unique"):
        _ = first + first


def test_a_periodic_job_takes_one_schedule() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        PeriodicComponent("job", lambda: None)
    with pytest.raises(ValueError, match="exactly one"):
        PeriodicComponent(
            "job", lambda: None, interval_seconds=1, next_run=daily_at(time(3, 0, tzinfo=IST))
        )
    with pytest.raises(ValueError, match="positive"):
        PeriodicComponent("job", lambda: None, interval_seconds=0)
    with pytest.raises(ValueError, match="blank"):
        PeriodicComponent(" ", lambda: None, interval_seconds=1)


def test_daily_at_is_the_next_wall_clock_time_in_its_zone() -> None:
    at_three = daily_at(time(3, 0, tzinfo=IST))
    two_am = datetime(2026, 9, 29, 2, 0, tzinfo=IST).astimezone(UTC)
    assert at_three(two_am) == datetime(2026, 9, 29, 3, 0, tzinfo=IST)
    assert at_three(two_am).tzinfo is UTC
    exactly = datetime(2026, 9, 29, 3, 0, tzinfo=IST)
    assert at_three(exactly) == datetime(2026, 9, 30, 3, 0, tzinfo=IST)
    with pytest.raises(ValueError, match="time zone"):
        daily_at(time(3, 0))


async def test_an_interval_job_runs_at_once_then_every_interval_on_a_thread() -> None:
    stop = asyncio.Event()
    threads: list[int] = []

    def tick() -> None:
        threads.append(threading.get_ident())
        if len(threads) == 3:
            stop.set()

    job = PeriodicComponent("tick", tick, interval_seconds=0.01)
    await asyncio.wait_for(job.run(SETTINGS, stop), timeout=5)
    assert len(threads) == 3
    assert threading.get_ident() not in threads, "a sync job runs off the loop"


async def test_a_failing_run_is_logged_and_the_job_goes_on() -> None:
    stop = asyncio.Event()
    calls = 0

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database away")
        stop.set()

    job = PeriodicComponent("flaky", flaky, interval_seconds=0.01)
    assert await job.run_once() is False
    await asyncio.wait_for(job.run(SETTINGS, stop), timeout=5)
    assert calls == 2


async def test_a_scheduled_job_waits_for_its_time() -> None:
    stop = asyncio.Event()
    now = datetime(2026, 9, 29, tzinfo=UTC)
    seen: list[datetime] = []

    async def purge() -> None:
        seen.append(now)
        stop.set()

    job = PeriodicComponent(
        "purge", purge, next_run=lambda at: at + timedelta(milliseconds=10), clock=lambda: now
    )
    await asyncio.wait_for(job.run(SETTINGS, stop), timeout=5)
    assert seen == [now]

    stopped = asyncio.Event()
    stopped.set()
    never = PeriodicComponent("never", purge, next_run=lambda at: at + timedelta(days=1))
    await asyncio.wait_for(never.run(SETTINGS, stopped), timeout=5)
    assert seen == [now], "a set stop event ends the wait before the run"

    backwards = PeriodicComponent("backwards", purge, next_run=lambda at: at, clock=lambda: now)
    with pytest.raises(ValueError, match="not after"):
        await backwards.run(SETTINGS, asyncio.Event())


async def test_a_failing_component_stops_the_others_and_is_raised() -> None:
    stop = asyncio.Event()
    stopped_cleanly: list[str] = []

    async def waits(event: asyncio.Event) -> None:
        await event.wait()
        stopped_cleanly.append("waits")

    async def fails(event: asyncio.Event) -> None:
        await asyncio.sleep(0)
        raise RuntimeError("broker gone")

    components = WorkerComponents(
        tasks=(TaskComponent("waits", waits), TaskComponent("fails", fails))
    )
    with pytest.raises(ExceptionGroup) as raised:
        await asyncio.wait_for(run_components(SETTINGS, components, stop), timeout=5)
    assert raised.group_contains(RuntimeError, match="broker gone")
    assert stop.is_set()


async def test_the_stop_event_ends_every_component() -> None:
    stop = asyncio.Event()
    ticks = 0

    def tick() -> None:
        nonlocal ticks
        ticks += 1

    async def stop_soon(event: asyncio.Event) -> None:
        await asyncio.sleep(0.05)
        event.set()

    components = WorkerComponents(
        periodic=(PeriodicComponent("tick", tick, interval_seconds=0.01),),
        tasks=(TaskComponent("stopper", stop_soon),),
    )
    await asyncio.wait_for(run_components(SETTINGS, components, stop), timeout=5)
    assert ticks >= 1
    await run_components(SETTINGS, WorkerComponents(), stop)


async def test_consumer_and_relay_components_run_their_runners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def fake_consumer(settings: Settings, **kwargs: Any) -> int:
        calls.append(("consumer", kwargs))
        return 0

    relay_started = [True]

    async def fake_relay(settings: Settings, stop: asyncio.Event, *, config: Any) -> bool:
        calls.append(("relay", config))
        return relay_started[0]

    monkeypatch.setattr(runtime, "run_consumer", fake_consumer)
    monkeypatch.setattr(runtime, "run_relay", fake_relay)
    stop = asyncio.Event()
    config = ConsumerConfig(max_handler_attempts=5)
    component = ConsumerComponent(
        "notification.obligations", ("obligation.created",), handler, config
    )
    await component.run(SETTINGS, stop)
    ((kind, kwargs),) = calls
    assert kind == "consumer"
    assert kwargs["group_id"] == "notification.obligations"
    assert kwargs["topics"] == ("obligation.created",)
    assert kwargs["config"] is config
    assert kwargs["stop"] is stop
    assert kwargs["store_factory"] is sync_store

    await RelayComponent().run(SETTINGS, stop)
    relay_started[0] = False
    with pytest.raises(RuntimeError, match="outbox_event"):
        await RelayComponent().run(SETTINGS, stop)


async def test_serve_builds_the_components_from_the_settings() -> None:
    built: list[Settings] = []
    ran: list[str] = []

    async def once(event: asyncio.Event) -> None:
        ran.append("once")

    def components(settings: Settings) -> WorkerComponents:
        built.append(settings)
        return WorkerComponents(tasks=(TaskComponent("once", once),))

    await asyncio.wait_for(serve(SETTINGS, components), timeout=5)
    assert built == [SETTINGS]
    assert ran == ["once"]


def test_run_worker_process_runs_the_components_to_the_end() -> None:
    ran: list[str] = []

    async def once(event: asyncio.Event) -> None:
        ran.append("once")

    run_worker_process(
        SETTINGS,
        lambda settings: WorkerComponents(tasks=(TaskComponent("once", once),)),
        version="0.0.0",
    )
    assert ran == ["once"]


# ---- several services in one process ---------------------------------------------------------


@workflow.defn(name="runtime-test.noop")
class NoopWorkflow:
    @workflow.run
    async def run(self) -> None:
        return None


def temporal(task_queue: str) -> TemporalComponent:
    return TemporalComponent(WorkerConfig(task_queue=task_queue), workflows=[NoopWorkflow])


def test_duplicate_task_queues_and_consumer_groups_are_rejected() -> None:
    with pytest.raises(ValueError, match="Temporal task queues must be unique"):
        WorkerComponents(temporal=(temporal("pipeline"), temporal("pipeline")))
    with pytest.raises(ValueError, match="consumer groups must be unique"):
        WorkerComponents(consumers=(consumer(), consumer()))
    notification = WorkerComponents(consumers=(consumer(),), temporal=(temporal("pipeline"),))
    with pytest.raises(ValueError, match="consumer groups must be unique"):
        ComponentRegistry().register("notification", SETTINGS, notification).register(
            "eval", SETTINGS, WorkerComponents(consumers=(consumer(),))
        )
    with pytest.raises(ValueError, match="Temporal task queues must be unique"):
        ComponentRegistry().register("pipeline", SETTINGS, notification).register(
            "eval", SETTINGS, WorkerComponents(temporal=(temporal("pipeline"),))
        )
    with pytest.raises(ValueError, match="hosted services must be unique"):
        ComponentRegistry().register("eval", SETTINGS, WorkerComponents()).register(
            "eval", SETTINGS, WorkerComponents()
        )
    with pytest.raises(ValueError, match="without a slash"):
        ComponentRegistry().register("a/b", SETTINGS, WorkerComponents())


def test_a_temporal_component_needs_something_to_run() -> None:
    worker = temporal("pipeline")
    assert (worker.name, worker.task_queue, worker.workflows) == (
        "temporal:pipeline",
        "pipeline",
        (NoopWorkflow,),
    )
    with pytest.raises(ValueError, match="workflows or activities"):
        TemporalComponent(WorkerConfig(task_queue="empty"))
    with pytest.raises(ValueError, match="blank"):
        LifecycleHook(" ", lambda: None)


def test_the_registry_names_every_loop_after_its_service() -> None:
    dispatch = PeriodicComponent("dispatch", lambda: None, interval_seconds=5)
    registry = (
        ComponentRegistry()
        .register(
            "notification",
            SETTINGS,
            WorkerComponents(consumers=(consumer(),), periodic=(dispatch,)),
        )
        .register("profile", SETTINGS, WorkerComponents(relays=(RelayComponent(),)))
        .register("rulebook", SETTINGS, WorkerComponents(relays=(RelayComponent(),)))
        .register("pipeline", SETTINGS, WorkerComponents(temporal=(temporal("pipeline"),)))
    )
    assert registry.loops() == (
        "notification/consumer:notification.obligations",
        "notification/dispatch",
        "profile/outbox-relay",
        "rulebook/outbox-relay",
    )
    assert registry.task_queues() == ("pipeline",)
    assert registry.consumer_groups() == ("notification.obligations",)
    assert registry.dead_letter_topics() == consumer().dead_letter_topics()
    assert not registry.is_empty
    assert ComponentRegistry().is_empty
    single = ComponentRegistry.of(SETTINGS, WorkerComponents(periodic=(dispatch,)))
    assert single.loops() == ("runtime-test/dispatch",)


async def test_each_service_runs_on_its_own_settings_and_reports_its_loops() -> None:
    reader = InMemoryMetricReader()
    register_loop_gauge(MeterProvider(metric_readers=[reader]).get_meter("test"))
    stop = asyncio.Event()
    seen: dict[str, str | None] = {}
    both_relaying = asyncio.Event()
    observed: list[tuple[str, ...]] = []

    class Relay:
        """Records the settings it runs on, then runs until the stop event."""

        name = "outbox-relay"

        async def run(self, settings: Settings, stop: asyncio.Event) -> None:
            seen[settings.service_name] = settings.db_schema
            if len(seen) == 2:
                both_relaying.set()
            await stop.wait()

    async def watch(event: asyncio.Event) -> None:
        await both_relaying.wait()
        observed.append(running_loops())
        event.set()

    def relaying(*extra: TaskComponent) -> WorkerComponents:
        return WorkerComponents(tasks=(cast(TaskComponent, Relay()), *extra))

    profile = Settings(_env_file=None, service_name="profile", db_schema="profile")
    rulebook = Settings(_env_file=None, service_name="rulebook", db_schema="rulebook")
    registry = (
        ComponentRegistry()
        .register("profile", profile, relaying(TaskComponent("watch", watch)))
        .register("rulebook", rulebook, relaying())
    )
    await asyncio.wait_for(run_registry(registry, stop), timeout=5)
    assert seen == {"profile": "profile", "rulebook": "rulebook"}
    assert observed == [("profile/outbox-relay", "profile/watch", "rulebook/outbox-relay")]
    assert running_loops() == ()
    with loop_running("profile/outbox-relay"):
        data = reader.get_metrics_data()
    assert data is not None
    metric = data.resource_metrics[0].scope_metrics[0].metrics[0]
    assert metric.name == "worker_loop_up"
    assert [dict(point.attributes or {}) for point in metric.data.data_points] == [
        {"loop": "profile/outbox-relay"}
    ]
    with pytest.raises(ValueError, match="blank"), loop_running(" "):
        pass


async def test_startup_hooks_run_first_and_shutdown_hooks_last_in_reverse() -> None:
    order: list[str] = []
    stop = asyncio.Event()

    async def async_hook() -> None:
        order.append("startup:async")

    def failing_shutdown() -> None:
        order.append("shutdown:failing")
        raise RuntimeError("cleanup went wrong")

    async def work(event: asyncio.Event) -> None:
        order.append("task")
        event.set()

    first = WorkerComponents(
        tasks=(TaskComponent("work", work),),
        startup=(LifecycleHook("sync", lambda: order.append("startup:sync")),),
        shutdown=(LifecycleHook("first", lambda: order.append("shutdown:first")),),
    )
    second = WorkerComponents(
        startup=(LifecycleHook("async", async_hook),),
        shutdown=(
            LifecycleHook("second", lambda: order.append("shutdown:second")),
            LifecycleHook("failing", failing_shutdown),
        ),
    )
    registry = ComponentRegistry().register("a", SETTINGS, first).register("b", SETTINGS, second)
    await asyncio.wait_for(run_registry(registry, stop), timeout=5)
    assert order == [
        "startup:sync",
        "startup:async",
        "task",
        "shutdown:failing",
        "shutdown:second",
        "shutdown:first",
    ]


async def test_a_failing_startup_hook_starts_nothing_and_still_shuts_down() -> None:
    ran: list[str] = []

    def broken() -> None:
        raise RuntimeError("schedule upsert refused")

    async def never(event: asyncio.Event) -> None:
        ran.append("task")

    components = WorkerComponents(
        tasks=(TaskComponent("never", never),),
        startup=(LifecycleHook("broken", broken),),
        shutdown=(LifecycleHook("close", lambda: ran.append("closed")),),
    )
    with pytest.raises(RuntimeError, match="schedule upsert refused"):
        await run_components(SETTINGS, components, asyncio.Event())
    assert ran == ["closed"]


def test_components_with_only_hooks_still_run_them() -> None:
    hooks = WorkerComponents(startup=(LifecycleHook("warm", lambda: None),))
    assert not hooks.is_empty
    assert WorkerComponents().is_empty
    both = hooks + WorkerComponents(shutdown=(LifecycleHook("drain", lambda: None),))
    assert [hook.name for hook in both.startup + both.shutdown] == ["warm", "drain"]
    with pytest.raises(ValueError, match="startup hook names must be unique"):
        _ = hooks + hooks


class FakeWorker:
    """Stands in for a temporalio Worker: runs until shut down, or fails when told to."""

    def __init__(self, task_queue: str, fail: bool) -> None:
        self.task_queue = task_queue
        self.fail = fail
        self.started = asyncio.Event()
        self._shutdown = asyncio.Event()
        self.shut_down = False

    async def run(self) -> None:
        self.started.set()
        if self.fail:
            raise RuntimeError(f"{self.task_queue}: namespace not found")
        await self._shutdown.wait()
        self.shut_down = True

    async def shutdown(self) -> None:
        self._shutdown.set()


def fake_workers(
    monkeypatch: pytest.MonkeyPatch, *, failing: Sequence[str] = ()
) -> dict[str, FakeWorker]:
    built: dict[str, FakeWorker] = {}

    def build_worker(client: object, config: WorkerConfig, **_: object) -> FakeWorker:
        assert client == "shared-client"
        worker = FakeWorker(config.task_queue, config.task_queue in failing)
        built[config.task_queue] = worker
        return worker

    monkeypatch.setattr(runtime, "build_worker", build_worker)
    return built


async def test_run_temporal_serves_every_queue_on_one_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = fake_workers(monkeypatch)
    stop = asyncio.Event()
    client = cast(Client, "shared-client")
    queues: list[tuple[str, ...]] = []

    async def stop_when_serving() -> None:
        for worker in list(built.values()):
            await worker.started.wait()
        queues.append(running_queues())
        stop.set()

    components = (temporal("pipeline"), temporal("eval"))
    runner = asyncio.create_task(run_temporal(client, components, stop))
    await asyncio.sleep(0)  # the workers are built before run_temporal first waits
    assert sorted(built) == ["eval", "pipeline"]
    await asyncio.wait_for(stop_when_serving(), timeout=5)
    await asyncio.wait_for(runner, timeout=5)
    assert queues == [("eval", "pipeline")]
    assert all(worker.shut_down for worker in built.values())
    assert running_queues() == ()
    await run_temporal(client, (), stop)
    with pytest.raises(ValueError, match="Temporal task queues must be unique"):
        await run_temporal(client, (temporal("eval"), temporal("eval")), stop)


async def test_a_failing_temporal_worker_stops_the_whole_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_workers(monkeypatch, failing=["eval"])
    connected: list[Settings] = []

    async def connect(settings: Settings) -> str:
        connected.append(settings)
        return "shared-client"

    monkeypatch.setattr(runtime, "connect", connect)
    stop = asyncio.Event()
    ended: list[str] = []

    async def waits(event: asyncio.Event) -> None:
        await event.wait()
        ended.append("waits")

    components = WorkerComponents(
        temporal=(temporal("pipeline"), temporal("eval")),
        tasks=(TaskComponent("waits", waits),),
    )
    with pytest.raises(ExceptionGroup) as raised:
        await asyncio.wait_for(run_components(SETTINGS, components, stop), timeout=5)
    assert raised.group_contains(RuntimeError, match="namespace not found")
    assert stop.is_set()
    assert connected == [SETTINGS], "one client for every queue"


async def test_a_temporal_component_alone_connects_its_own_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = fake_workers(monkeypatch)

    async def connect(settings: Settings) -> str:
        return "shared-client"

    monkeypatch.setattr(runtime, "connect", connect)
    stop = asyncio.Event()
    stop.set()
    await asyncio.wait_for(temporal("pipeline").run(SETTINGS, stop), timeout=5)
    assert sorted(built) == ["pipeline"]
    assert built["pipeline"].started.is_set()
    assert built["pipeline"].shut_down, "a set stop event shuts the worker down at once"


async def test_a_consumer_takes_a_store_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryProcessedStore()
    stores: list[ProcessedStore] = []

    def memory_store(engine: Engine, group_id: str) -> ProcessedStore:
        stores.append(store)
        return store

    async def fake_consumer(settings: Settings, **kwargs: Any) -> int:
        kwargs["store_factory"](cast(Engine, None), kwargs["group_id"])
        return 0

    monkeypatch.setattr(runtime, "run_consumer", fake_consumer)
    component = ConsumerComponent(
        "notification.obligations", ("obligation.created",), handler, store_factory=memory_store
    )
    await component.run(SETTINGS, asyncio.Event())
    assert stores == [store]


def test_ist_is_india_standard_time() -> None:
    assert IST.utcoffset(None) == timedelta(hours=5, minutes=30)
