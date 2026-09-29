"""What a service's worker process runs, and the loop that runs it.

Every service with background work exposes ``<pkg>.worker.components(settings)``, which returns
``WorkerComponents``; ``python -m <pkg>.worker`` (``make worker SERVICE=<svc>``) passes it to
``run_worker_process``, which runs every component until SIGTERM or SIGINT. A process that hosts
several services adds their components together (``a + b``) and runs the sum.

- ``consumers``: ``ConsumerComponent(group_id, topics, handler)``, an ``IdempotentConsumer`` on
  ``SyncProcessedStore`` (``py_common.outbox.sync.run_consumer``). Group ids follow
  ``<service>.<purpose>``, such as ``notification.obligations``, and a message the handler cannot
  process goes to ``<topic>.<group_id>.dlq``.
- ``relays``: ``RelayComponent()``, the outbox relay of the schema on ``CW_DATABASE_URL``.
- ``periodic``: ``PeriodicComponent(name, fn, interval_seconds=...)`` runs ``fn`` at once and
  then every interval; with ``next_run=`` instead it runs at the times the schedule gives, such
  as ``daily_at(time(3, 0, tzinfo=IST))``. A sync ``fn`` runs on a thread
  (``asyncio.to_thread``), so it never blocks the loop. A failing run is logged and the job runs
  again at its next time.
- ``temporal``: ``TaskComponent(name, run)``, any coroutine that runs until the stop event is
  set, such as a Temporal worker.

When a consumer, relay or task fails, the others are stopped and the error ends the process, so
the supervisor restarts it.
"""

import asyncio
import inspect
import re
import signal
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Protocol, cast

from domain_kernel.events import utc_now
from py_common.logging import configure_logging, get_logger
from py_common.outbox.consumer import DEFAULT_CONFIG as DEFAULT_CONSUMER_CONFIG
from py_common.outbox.consumer import ConsumerConfig, Handler
from py_common.outbox.relay import DEFAULT_CONFIG as DEFAULT_RELAY_CONFIG
from py_common.outbox.relay import RelayConfig, run_relay
from py_common.outbox.sync import run_consumer
from py_common.settings import Settings
from py_common.telemetry import configure_telemetry

log = get_logger(__name__)

GROUP_ID = re.compile(r"[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*")
"""``<service>.<purpose>``: the service directory name, a dot, and what the group consumes for."""

Clock = Callable[[], datetime]
Schedule = Callable[[datetime], datetime]
"""The next run after a moment; it must return a later moment."""


class Runnable(Protocol):
    """One component as the loop sees it: its name and how it runs until ``stop`` is set."""

    @property
    def name(self) -> str: ...

    async def run(self, settings: Settings, stop: asyncio.Event) -> None: ...


@dataclass(frozen=True, slots=True)
class ConsumerComponent:
    group_id: str
    topics: tuple[str, ...]
    handler: Handler
    config: ConsumerConfig = DEFAULT_CONSUMER_CONFIG

    def __post_init__(self) -> None:
        if not GROUP_ID.fullmatch(self.group_id):
            raise ValueError(f"group_id must be <service>.<purpose>, got {self.group_id!r}")
        if not self.topics:
            raise ValueError("a consumer needs at least one topic")

    @property
    def name(self) -> str:
        return f"consumer:{self.group_id}"

    def dead_letter_topics(self) -> tuple[str, ...]:
        """Where each topic's unprocessable messages go."""
        return tuple(f"{topic}.{self.group_id}{self.config.dlq_suffix}" for topic in self.topics)

    async def run(self, settings: Settings, stop: asyncio.Event) -> None:
        await run_consumer(
            settings,
            group_id=self.group_id,
            topics=self.topics,
            handler=self.handler,
            stop=stop,
            config=self.config,
        )


@dataclass(frozen=True, slots=True)
class RelayComponent:
    config: RelayConfig = DEFAULT_RELAY_CONFIG

    @property
    def name(self) -> str:
        return "outbox-relay"

    async def run(self, settings: Settings, stop: asyncio.Event) -> None:
        if not await run_relay(settings, stop, config=self.config):
            raise RuntimeError("the outbox relay found no outbox_event table; migrate first")


@dataclass(frozen=True, slots=True)
class PeriodicComponent:
    name: str
    fn: Callable[[], object]
    """A function of no arguments, sync (run on a thread) or async."""
    interval_seconds: float | None = None
    next_run: Schedule | None = None
    clock: Clock = field(default=utc_now, compare=False)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if (self.interval_seconds is None) == (self.next_run is None):
            raise ValueError("give exactly one of interval_seconds and next_run")
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

    async def run_once(self) -> bool:
        """One run of ``fn``; a failure is logged and reported as False, never raised."""
        try:
            if inspect.iscoroutinefunction(self.fn):
                await cast(Callable[[], Awaitable[object]], self.fn)()
            else:
                await asyncio.to_thread(self.fn)
        except Exception as exc:
            log.exception("worker.job_failed", job=self.name, error=f"{type(exc).__name__}: {exc}")
            return False
        return True

    async def run(self, settings: Settings, stop: asyncio.Event) -> None:
        while not stop.is_set():
            if self.next_run is not None:
                now = self.clock()
                due = self.next_run(now)
                if due <= now:
                    raise ValueError(f"{self.name}: the schedule gave {due}, not after {now}")
                if await _stopped_within(stop, (due - now).total_seconds()):
                    return
                await self.run_once()
            else:
                await self.run_once()
                if await _stopped_within(stop, cast(float, self.interval_seconds)):
                    return


@dataclass(frozen=True, slots=True)
class TaskComponent:
    name: str
    task: Callable[[asyncio.Event], Awaitable[object]]
    """Runs until the event is set, such as ``run_worker(..., stop=stop)`` for Temporal."""

    async def run(self, settings: Settings, stop: asyncio.Event) -> None:
        await self.task(stop)


@dataclass(frozen=True, slots=True)
class WorkerComponents:
    consumers: tuple[ConsumerComponent, ...] = ()
    relays: tuple[RelayComponent, ...] = ()
    periodic: tuple[PeriodicComponent, ...] = ()
    temporal: tuple[TaskComponent, ...] = ()

    def __post_init__(self) -> None:
        names = [component.name for component in self.all()]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"component names must be unique: {duplicates}")

    def __add__(self, other: "WorkerComponents") -> "WorkerComponents":
        return WorkerComponents(
            consumers=self.consumers + other.consumers,
            relays=self.relays + other.relays,
            periodic=self.periodic + other.periodic,
            temporal=self.temporal + other.temporal,
        )

    def all(self) -> Sequence[Runnable]:
        return (*self.consumers, *self.relays, *self.periodic, *self.temporal)


def daily_at(at: time) -> Schedule:
    """A schedule that runs once a day at ``at``, a wall-clock time with its time zone."""
    if at.tzinfo is None:
        raise ValueError("daily_at needs a time with a time zone")
    zone = at.tzinfo

    def next_run(now: datetime) -> datetime:
        local = now.astimezone(zone)
        due = local.replace(hour=at.hour, minute=at.minute, second=at.second, microsecond=0)
        if due <= local:
            due += timedelta(days=1)
        return due.astimezone(now.tzinfo)

    return next_run


async def _stopped_within(stop: asyncio.Event, seconds: float) -> bool:
    """Wait up to ``seconds``; True when ``stop`` was set meanwhile."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=max(seconds, 0))
    except TimeoutError:
        return False
    return True


async def run_components(
    settings: Settings, components: WorkerComponents, stop: asyncio.Event
) -> None:
    """Run every component until ``stop`` is set. The first failure sets ``stop`` for the
    others and is raised once they have ended."""
    runnables = components.all()
    if not runnables:
        log.warning("worker.nothing_to_run")
        return
    log.info("worker.started", components=[runnable.name for runnable in runnables])

    async def guarded(runnable: Runnable) -> None:
        try:
            await runnable.run(settings, stop)
        except Exception:
            log.exception("worker.component_failed", component=runnable.name)
            stop.set()
            raise

    async with asyncio.TaskGroup() as group:
        for runnable in runnables:
            group.create_task(guarded(runnable), name=runnable.name)
    log.info("worker.stopped", components=[runnable.name for runnable in runnables])


def install_stop_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)


async def serve[S: Settings](settings: S, components: Callable[[S], WorkerComponents]) -> None:
    """Build the components and run them until SIGTERM or SIGINT."""
    stop = asyncio.Event()
    install_stop_signals(stop)
    await run_components(settings, components(settings), stop)


def run_worker_process[S: Settings](
    settings: S, components: Callable[[S], WorkerComponents], *, version: str
) -> None:
    """The body of ``python -m <pkg>.worker``: logging, telemetry, then ``serve``."""
    configure_logging(
        service_name=settings.service_name,
        log_level=settings.log_level,
        json_output=settings.log_json,
    )
    telemetry = configure_telemetry(
        service_name=settings.service_name, version=version, settings=settings
    )
    try:
        asyncio.run(serve(settings, components))
    finally:
        telemetry.shutdown()
