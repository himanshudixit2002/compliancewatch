"""Worker components and the loop that runs them, without a broker or a database."""

import asyncio
import threading
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Any

import pytest

from py_common import runtime
from py_common.outbox.consumer import ConsumerConfig
from py_common.outbox.store import UnitOfWork
from py_common.runtime import (
    ConsumerComponent,
    PeriodicComponent,
    RelayComponent,
    TaskComponent,
    WorkerComponents,
    daily_at,
    run_components,
    run_worker_process,
    serve,
)
from py_common.settings import Settings

IST = timezone(timedelta(hours=5, minutes=30), "IST")
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
        temporal=(TaskComponent("waits", waits), TaskComponent("fails", fails))
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
        temporal=(TaskComponent("stopper", stop_soon),),
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
        return WorkerComponents(temporal=(TaskComponent("once", once),))

    await asyncio.wait_for(serve(SETTINGS, components), timeout=5)
    assert built == [SETTINGS]
    assert ran == ["once"]


def test_run_worker_process_runs_the_components_to_the_end() -> None:
    ran: list[str] = []

    async def once(event: asyncio.Event) -> None:
        ran.append("once")

    run_worker_process(
        SETTINGS,
        lambda settings: WorkerComponents(temporal=(TaskComponent("once", once),)),
        version="0.0.0",
    )
    assert ran == ["once"]
