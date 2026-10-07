"""What a worker process runs, and the loop that runs it.

Every service with background work exposes ``<pkg>.worker.components(settings)``, which returns
``WorkerComponents``; ``python -m <pkg>.worker`` (``make worker SERVICE=<svc>``) passes it to
``run_worker_process``, which runs every component until SIGTERM or SIGINT. Components of one
service add up (``a + b``). A process that hosts several services registers each one's
components with the settings they run on (``ComponentRegistry().register(service, settings,
components)``) and runs them all with ``run_registry``.

- ``consumers``: ``ConsumerComponent(group_id, topics, handler)``, an ``IdempotentConsumer`` on
  ``SyncProcessedStore`` (``py_common.outbox.sync.run_consumer``; ``store_factory`` replaces the
  store). Group ids follow ``<service>.<purpose>``, such as ``notification.obligations``, and a
  message the handler cannot process goes to ``<topic>.<group_id>.dlq``.
- ``relays``: ``RelayComponent()``, the outbox relay of the schema on ``CW_DATABASE_URL``.
- ``periodic``: ``PeriodicComponent(name, fn, interval_seconds=...)`` runs ``fn`` at once and
  then every interval; with ``next_run=`` instead it runs at the times the schedule gives, such
  as ``daily_at(time(3, 0, tzinfo=IST))``. A sync ``fn`` runs on a thread
  (``asyncio.to_thread``), so it never blocks the loop. A failing run is logged and the job runs
  again at its next time.
- ``temporal``: ``TemporalComponent(WorkerConfig(task_queue), workflows, activities)``. The
  Temporal workers of a process share one client (``run_temporal``), and each reports
  ``temporal_worker_up{task_queue}`` while it serves its queue.
- ``tasks``: ``TaskComponent(name, run)``, any coroutine that runs until the stop event is set.
- ``startup`` and ``shutdown``: ``LifecycleHook(name, fn)``, sync or async like a periodic job.
  The startup hooks run in order before anything else starts, and a failing one ends the process
  before it serves. The shutdown hooks run in reverse order once everything has stopped, however
  it stopped; a failing one is logged and the rest still run.

Every consumer, relay, periodic job and task reports ``worker_loop_up{loop}`` while it runs, the
loop being ``<service>/<component>``. When one of them or a Temporal worker fails, the others are
stopped and the error ends the process, so the supervisor restarts it.
"""

import asyncio
import inspect
import re
import signal
import threading
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Protocol, Self, cast

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Meter, ObservableGauge, Observation
from temporalio.client import Client

from domain_kernel.events import utc_now
from py_common.logging import configure_logging, get_logger
from py_common.outbox.consumer import DEFAULT_CONFIG as DEFAULT_CONSUMER_CONFIG
from py_common.outbox.consumer import ConsumerConfig, Handler
from py_common.outbox.relay import DEFAULT_CONFIG as DEFAULT_RELAY_CONFIG
from py_common.outbox.relay import RelayConfig, run_relay
from py_common.outbox.sync import StoreFactory, run_consumer, sync_store
from py_common.settings import Settings
from py_common.telemetry import configure_telemetry
from py_common.temporal.activity import ActivityBase
from py_common.temporal.client import connect
from py_common.temporal.liveness import running
from py_common.temporal.worker import WorkerConfig, build_worker

log = get_logger(__name__)

GROUP_ID = re.compile(r"[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*")
"""``<service>.<purpose>``: the service directory name, a dot, and what the group consumes for."""
IST = timezone(timedelta(hours=5, minutes=30), "IST")
"""India Standard Time, the zone daily jobs are scheduled in."""
LOOP_METRIC = "worker_loop_up"
LOOP_ATTRIBUTE = "loop"
LOOP_DESCRIPTION = "1 for each consumer, relay, periodic job and task this worker is running"

Clock = Callable[[], datetime]
Schedule = Callable[[datetime], datetime]
"""The next run after a moment; it must return a later moment."""


class Runnable(Protocol):
    """One component as the loop sees it: its name and how it runs until ``stop`` is set."""

    @property
    def name(self) -> str: ...

    async def run(self, settings: Settings, stop: asyncio.Event) -> None: ...


async def _call(fn: Callable[[], object]) -> None:
    """``fn()``: awaited when it is a coroutine function, on a thread otherwise."""
    if inspect.iscoroutinefunction(fn):
        await cast(Callable[[], Awaitable[object]], fn)()
    else:
        await asyncio.to_thread(fn)


@dataclass(frozen=True, slots=True)
class ConsumerComponent:
    group_id: str
    topics: tuple[str, ...]
    handler: Handler
    config: ConsumerConfig = DEFAULT_CONSUMER_CONFIG
    store_factory: StoreFactory = sync_store
    """The processed-event store on the engine of ``CW_DATABASE_URL``."""

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
            store_factory=self.store_factory,
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
            await _call(self.fn)
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
    """Runs until the event is set."""

    async def run(self, settings: Settings, stop: asyncio.Event) -> None:
        await self.task(stop)


@dataclass(frozen=True, slots=True)
class TemporalComponent:
    """A Temporal worker: its task queue and concurrency, its workflows and its activities."""

    config: WorkerConfig
    workflows: Sequence[type[Any]] = ()
    activities: Sequence[ActivityBase[Any, Any]] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "workflows", tuple(self.workflows))
        object.__setattr__(self, "activities", tuple(self.activities))
        if not self.workflows and not self.activities:
            raise ValueError(f"{self.task_queue}: a Temporal worker needs workflows or activities")

    @property
    def task_queue(self) -> str:
        return self.config.task_queue

    @property
    def name(self) -> str:
        return f"temporal:{self.task_queue}"

    async def run(self, settings: Settings, stop: asyncio.Event) -> None:
        """This worker alone, on a client of its own."""
        await run_temporal(await connect(settings), (self,), stop)


@dataclass(frozen=True, slots=True)
class LifecycleHook:
    """Work a worker process does once, when it starts or when it stops."""

    name: str
    fn: Callable[[], object]
    """A function of no arguments, sync (run on a thread) or async."""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be blank")

    async def run(self) -> None:
        await _call(self.fn)


def _unique(what: str, names: Iterable[str]) -> None:
    listed = list(names)
    duplicates = sorted({name for name in listed if listed.count(name) > 1})
    if duplicates:
        raise ValueError(f"{what} must be unique: {duplicates}")


@dataclass(frozen=True, slots=True)
class WorkerComponents:
    consumers: tuple[ConsumerComponent, ...] = ()
    relays: tuple[RelayComponent, ...] = ()
    periodic: tuple[PeriodicComponent, ...] = ()
    temporal: tuple[TemporalComponent, ...] = ()
    tasks: tuple[TaskComponent, ...] = ()
    startup: tuple[LifecycleHook, ...] = ()
    shutdown: tuple[LifecycleHook, ...] = ()

    def __post_init__(self) -> None:
        _unique("consumer groups", (consumer.group_id for consumer in self.consumers))
        _unique("Temporal task queues", (worker.task_queue for worker in self.temporal))
        _unique("component names", (component.name for component in self.all()))
        _unique("startup hook names", (hook.name for hook in self.startup))
        _unique("shutdown hook names", (hook.name for hook in self.shutdown))

    def __add__(self, other: "WorkerComponents") -> "WorkerComponents":
        return WorkerComponents(
            consumers=self.consumers + other.consumers,
            relays=self.relays + other.relays,
            periodic=self.periodic + other.periodic,
            temporal=self.temporal + other.temporal,
            tasks=self.tasks + other.tasks,
            startup=self.startup + other.startup,
            shutdown=self.shutdown + other.shutdown,
        )

    def loops(self) -> Sequence[Runnable]:
        """Everything but the Temporal workers: the loops that report ``worker_loop_up``."""
        return (*self.consumers, *self.relays, *self.periodic, *self.tasks)

    def all(self) -> Sequence[Runnable]:
        return (*self.loops(), *self.temporal)

    @property
    def is_empty(self) -> bool:
        return not (self.all() or self.startup or self.shutdown)


@dataclass(frozen=True, slots=True)
class HostedComponents:
    """One service's components and the settings they run on."""

    service: str
    settings: Settings
    components: WorkerComponents

    def __post_init__(self) -> None:
        if not self.service.strip() or "/" in self.service:
            raise ValueError(f"service must be a name without a slash, got {self.service!r}")

    def loop_name(self, component: Runnable) -> str:
        """``<service>/<component>``, the ``loop`` of ``worker_loop_up``."""
        return f"{self.service}/{component.name}"


@dataclass(frozen=True, slots=True)
class ComponentRegistry:
    """The components of every service a worker process hosts. Consumer groups and Temporal task
    queues are unique across the services; component names only within each."""

    hosted: tuple[HostedComponents, ...] = ()

    def __post_init__(self) -> None:
        _unique("hosted services", (entry.service for entry in self.hosted))
        _unique("consumer groups", self.consumer_groups())
        _unique("Temporal task queues", self.task_queues())

    @classmethod
    def of(cls, settings: Settings, components: WorkerComponents) -> Self:
        """One service's components, under its ``service_name``."""
        return cls((HostedComponents(settings.service_name, settings, components),))

    def register(
        self, service: str, settings: Settings, components: WorkerComponents
    ) -> "ComponentRegistry":
        """This registry with ``service`` added; raises on a duplicate service, group or
        queue."""
        return ComponentRegistry((*self.hosted, HostedComponents(service, settings, components)))

    def consumer_groups(self) -> tuple[str, ...]:
        return tuple(
            consumer.group_id for entry in self.hosted for consumer in entry.components.consumers
        )

    def dead_letter_topics(self) -> tuple[str, ...]:
        """Every consumer's dead-letter topics, ``<topic>.<group_id>.dlq``."""
        return tuple(
            topic
            for entry in self.hosted
            for consumer in entry.components.consumers
            for topic in consumer.dead_letter_topics()
        )

    def task_queues(self) -> tuple[str, ...]:
        return tuple(worker.task_queue for worker in self.temporal())

    def temporal(self) -> tuple[TemporalComponent, ...]:
        return tuple(worker for entry in self.hosted for worker in entry.components.temporal)

    def loops(self) -> tuple[str, ...]:
        """The ``loop`` of every consumer, relay, periodic job and task."""
        return tuple(
            entry.loop_name(component)
            for entry in self.hosted
            for component in entry.components.loops()
        )

    @property
    def is_empty(self) -> bool:
        return all(entry.components.is_empty for entry in self.hosted)


_loops_lock = threading.Lock()
_running_loops: Counter[str] = Counter()


@contextmanager
def loop_running(loop: str) -> Iterator[None]:
    """Report ``loop`` in ``worker_loop_up`` while the block runs."""
    if not loop.strip():
        raise ValueError("loop must not be blank")
    with _loops_lock:
        _running_loops[loop] += 1
    try:
        yield
    finally:
        with _loops_lock:
            _running_loops[loop] -= 1
            if _running_loops[loop] <= 0:
                del _running_loops[loop]


def running_loops() -> tuple[str, ...]:
    """The loops this process runs now, sorted."""
    with _loops_lock:
        return tuple(sorted(_running_loops))


def observe_loops(_options: CallbackOptions) -> Iterable[Observation]:
    """The gauge's callback: 1 per running loop."""
    return [Observation(1, {LOOP_ATTRIBUTE: loop}) for loop in running_loops()]


def register_loop_gauge(meter: Meter) -> ObservableGauge:
    """Create ``worker_loop_up`` on ``meter``; the module does it once on the global meter, and
    tests call it with a meter of their own. No unit, so the collector adds no suffix."""
    return meter.create_observable_gauge(
        LOOP_METRIC, callbacks=[observe_loops], description=LOOP_DESCRIPTION
    )


LOOP_GAUGE = register_loop_gauge(metrics.get_meter("py_common.runtime"))
"""The process's one ``worker_loop_up`` instrument. A Temporal worker reports through
``temporal_worker_up`` instead (``py_common.temporal.liveness``)."""


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


async def run_temporal(
    client: Client, components: Sequence[TemporalComponent], stop: asyncio.Event
) -> None:
    """One Temporal worker per component, all on ``client``, until ``stop`` is set. Each queue
    reports ``temporal_worker_up`` while its worker runs. A worker that fails stops the others
    and its error is raised."""
    if not components:
        return
    _unique("Temporal task queues", (component.task_queue for component in components))
    workers = [
        (
            component,
            build_worker(
                client,
                component.config,
                workflows=component.workflows,
                activities=component.activities,
            ),
        )
        for component in components
    ]

    async def serve_queue(task_queue: str, worker: Any) -> None:
        with running(task_queue):
            await worker.run()

    async def shut_down_on_stop() -> None:
        await stop.wait()
        await asyncio.gather(*(worker.shutdown() for _, worker in workers))

    queues = [component.task_queue for component in components]
    log.info("worker.temporal_started", task_queues=queues)
    async with asyncio.TaskGroup() as group:
        for component, worker in workers:
            group.create_task(serve_queue(component.task_queue, worker), name=component.name)
        group.create_task(shut_down_on_stop(), name="temporal:shutdown")
    log.info("worker.temporal_stopped", task_queues=queues)


async def _run_hooks(hooks: Iterable[tuple[str, LifecycleHook]], *, raise_errors: bool) -> None:
    for service, hook in hooks:
        try:
            await hook.run()
        except Exception:
            log.exception("worker.hook_failed", service=service, hook=hook.name)
            if raise_errors:
                raise


def _bound(
    component: Runnable, settings: Settings, stop: asyncio.Event
) -> Callable[[], Awaitable[None]]:
    return lambda: component.run(settings, stop)


async def run_registry(
    registry: ComponentRegistry,
    stop: asyncio.Event,
    *,
    client: Client | None = None,
    temporal_settings: Settings | None = None,
) -> None:
    """Run every hosted service's components, each with its service's settings, until ``stop``
    is set. The startup hooks run first. The Temporal workers share ``client``, or one client
    connected with ``temporal_settings`` (the first service's settings when None). The first
    failure sets ``stop`` for the others and is raised once they have ended; the shutdown hooks
    run last in any case."""
    if registry.is_empty:
        log.warning("worker.nothing_to_run")
        return
    loops, queues = list(registry.loops()), list(registry.task_queues())
    log.info("worker.started", loops=loops, task_queues=queues)

    async def guarded(name: str, run: Callable[[], Awaitable[None]], *, loop: bool) -> None:
        try:
            if loop:
                with loop_running(name):
                    await run()
            else:
                await run()
        except Exception:
            log.exception("worker.component_failed", component=name)
            stop.set()
            raise

    startup = [
        (entry.service, hook) for entry in registry.hosted for hook in entry.components.startup
    ]
    shutdown = [
        (entry.service, hook)
        for entry in reversed(registry.hosted)
        for hook in reversed(entry.components.shutdown)
    ]
    try:
        await _run_hooks(startup, raise_errors=True)
        temporal = registry.temporal()
        if temporal and client is None:
            client = await connect(temporal_settings or registry.hosted[0].settings)
        async with asyncio.TaskGroup() as group:
            for entry in registry.hosted:
                for component in entry.components.loops():
                    name = entry.loop_name(component)
                    group.create_task(
                        guarded(name, _bound(component, entry.settings, stop), loop=True),
                        name=name,
                    )
            if temporal:
                shared = cast(Client, client)
                group.create_task(
                    guarded("temporal", lambda: run_temporal(shared, temporal, stop), loop=False),
                    name="temporal",
                )
    finally:
        await _run_hooks(shutdown, raise_errors=False)
    log.info("worker.stopped", loops=loops, task_queues=queues)


async def run_components(
    settings: Settings,
    components: WorkerComponents,
    stop: asyncio.Event,
    *,
    client: Client | None = None,
) -> None:
    """Run one service's components until ``stop`` is set: ``run_registry`` of that service
    alone, under its ``service_name``."""
    await run_registry(ComponentRegistry.of(settings, components), stop, client=client)


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
        env=settings.env,
    )
    telemetry = configure_telemetry(
        service_name=settings.service_name, version=version, settings=settings
    )
    try:
        asyncio.run(serve(settings, components))
    finally:
        telemetry.shutdown()
