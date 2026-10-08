"""``cw-mvp worker``: the worker process, every service's background work in one event loop.

``build_registry`` hosts, for each registered service, with that service's settings
(``registry.service_settings``: its schema first on the ``search_path``, every URL of another
service at ``--internal-url`` or ``CW_MVP_INTERNAL_URL``):

- its worker components (``<pkg>.worker.components``): consumers, periodic jobs, tasks, hooks and
  Temporal workers;
- the outbox relay of its schema, when the schema has an ``outbox_event`` table;
- the daily idempotency purge of its schema, when the schema has an ``idempotency_key`` table.

The process's flags are configured once, from the shared settings, before any component is
built (``py_common.erasure.configure_flags_once``), and every service's erasure consumer reads the
flag ``identity.tenant_erasure`` through the one switch (``erasure_switch``), so no flag is read
while another service swaps the provider.

``CW_WORKER_KAFKA_ENABLED`` turns the relays and the consumers on, ``CW_WORKER_TEMPORAL_ENABLED``
the Temporal workers, which share one client; periodic jobs run either way, behind their
service's own switch where it has one. So obligation's consumer of applicability.decided runs
only with Kafka on, and its reminder sweep whenever ``CW_OBLIGATION_SWEEP_ENABLED`` is on: the
reminders wait in obligation's outbox until a relay publishes them.

A service on its memory store (its ``<service>_store`` setting, such as
``CW_OBLIGATION_STORE=memory``) keeps its state in the app process, out of the worker's reach,
so the worker hosts nothing of it, not even its schema's relay or purge, and logs
``worker.service_skipped``. The service's own worker refuses to start on that store (``python -m
obligation.worker``); here the other services still run.

The calls the services make to each other go to the app process's internal listener with the
worker's own service client (``CW_SERVICE_CLIENT_ID``, ``worker`` when it is empty, and
``CW_SERVICE_CLIENT_SECRET``), whose tokens identity issues and every service verifies.

``run_worker`` runs them all (``py_common.runtime.run_registry``) next to the heartbeat of the
health app on ``CW_MVP_WORKER_HEALTH_PORT`` (``cw_mvp.worker_health``) until ``stop`` is set,
which SIGTERM and SIGINT do. When one loop fails it is logged, the others stop, and the process
exits 1 so the platform restarts it.
"""

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Final

from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from temporalio.client import Client

from cw_mvp import __version__
from cw_mvp.registry import REGISTRY, ServiceEntry, check_overrides, service_settings
from cw_mvp.settings import WORKER_SERVICE_NAME, MvpSettings
from cw_mvp.worker_health import HealthServer, WorkerHealth, health_app, heartbeat
from py_common.erasure import configure_flags_once
from py_common.idempotency.purge import purge_job
from py_common.idempotency.schema import IDEMPOTENCY_TABLE
from py_common.logging import configure_logging, get_logger
from py_common.outbox.schema import OUTBOX_TABLE
from py_common.runtime import (
    ComponentRegistry,
    RelayComponent,
    WorkerComponents,
    install_stop_signals,
    run_registry,
)
from py_common.settings import Settings
from py_common.telemetry import configure_telemetry

WORKER_CLIENT_ID: Final = "worker"
"""The service client the worker calls the other services as, unless CW_SERVICE_CLIENT_ID
names another."""
POSTGRES: Final = "postgres"
"""The store the worker can share with the app process."""

TableProbe = Callable[[Settings, str], Awaitable[bool]]
"""Whether the schema of the settings has the named table."""

log = get_logger(__name__)


async def has_table(settings: Settings, table: str) -> bool:
    """Whether ``table`` exists in the settings' schema (``db_schema``)."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

    def check(connection: Connection) -> bool:
        return inspect(connection).has_table(table, schema=settings.db_schema)

    try:
        async with engine.connect() as connection:
            return await connection.run_sync(check)
    finally:
        await engine.dispose()


def selected(components: WorkerComponents, *, kafka: bool, temporal: bool) -> WorkerComponents:
    """``components`` without the Kafka ones (consumers and relays) or the Temporal workers
    their switch leaves off."""
    return dataclasses.replace(
        components,
        consumers=components.consumers if kafka else (),
        relays=components.relays if kafka else (),
        temporal=components.temporal if temporal else (),
    )


def worker_settings[S: Settings](
    entry: ServiceEntry[S], root: MvpSettings, *, internal_url: str, **overrides: Any
) -> S:
    """``entry``'s settings in the worker: its own, calling the others as the worker's client."""
    values: dict[str, Any] = {"service_client_id": root.service_client_id or WORKER_CLIENT_ID}
    values.update(overrides)
    return service_settings(entry, root, internal_url=internal_url, **values)


def store_elsewhere(entry: ServiceEntry[Any], settings: Settings) -> str | None:
    """``CW_<SERVICE>_STORE=<store>`` when ``entry`` keeps its state off Postgres (its memory
    store); None for a service on Postgres or without a store setting."""
    field = entry.store_field
    if field is None:
        return None
    store = str(getattr(settings, field))
    return None if store == POSTGRES else f"CW_{field.upper()}={store}"


async def build_registry(
    root: MvpSettings,
    *,
    internal_url: str | None = None,
    registry: Sequence[ServiceEntry[Any]] = REGISTRY,
    probe: TableProbe = has_table,
    service_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> ComponentRegistry:
    """What the worker runs for every service, by the switches, the store each service is on
    and the tables each schema has."""
    overrides = service_overrides or {}
    check_overrides(overrides, registry)
    configure_flags_once(root)
    url = internal_url or root.mvp_internal_url
    kafka, temporal = root.worker_kafka_enabled, root.worker_temporal_enabled
    hosted = ComponentRegistry()
    for entry in registry:
        settings = worker_settings(entry, root, internal_url=url, **overrides.get(entry.name, {}))
        elsewhere = store_elsewhere(entry, settings)
        if elsewhere is not None:
            log.warning(
                "worker.service_skipped",
                service=entry.name,
                reason=f"{elsewhere}: its state is in the app process, out of the worker's reach",
            )
            continue
        own = WorkerComponents() if entry.components is None else entry.components(settings)
        components = selected(own, kafka=kafka, temporal=temporal)
        if kafka and not components.relays and await probe(settings, OUTBOX_TABLE):
            components += WorkerComponents(relays=(RelayComponent(),))
        if await probe(settings, IDEMPOTENCY_TABLE):
            components += WorkerComponents(periodic=(purge_job(settings),))
        if not components.is_empty:
            hosted = hosted.register(entry.name, settings, components)
    return hosted


async def run_worker(
    root: MvpSettings,
    stop: asyncio.Event,
    *,
    hosted: ComponentRegistry,
    client: Client | None = None,
    health_port: int | None = None,
) -> None:
    """Run ``hosted`` and the health app until ``stop`` is set; raise the first failure once
    the rest have stopped. With nothing hosted, only the health app runs."""
    health = WorkerHealth(
        loops=hosted.loops(),
        task_queues=hosted.task_queues(),
        stale_after_seconds=root.mvp_worker_stale_seconds,
    )
    port = root.mvp_worker_health_port if health_port is None else health_port
    server = HealthServer(health_app(health), root.mvp_host, port)
    await asyncio.to_thread(server.start)
    log.info(
        "worker.hosting",
        services=[entry.service for entry in hosted.hosted],
        loops=list(hosted.loops()),
        task_queues=list(hosted.task_queues()),
        health_port=server.port,
    )

    async def components() -> None:
        await run_registry(hosted, stop, client=client, temporal_settings=root)
        await stop.wait()

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(
                heartbeat(health, stop, interval=root.mvp_worker_heartbeat_seconds),
                name="worker:heartbeat",
            )
            group.create_task(components(), name="worker:components")
    finally:
        await asyncio.to_thread(server.stop)


async def serve(root: MvpSettings, *, internal_url: str | None = None) -> None:
    """Build what the worker hosts and run it until SIGTERM or SIGINT."""
    stop = asyncio.Event()
    install_stop_signals(stop)
    hosted = await build_registry(root, internal_url=internal_url)
    await run_worker(root, stop, hosted=hosted)


def main(*, internal_url: str | None = None, settings: MvpSettings | None = None) -> int:
    """The body of ``cw-mvp worker``: 0 after a clean stop, 1 when a loop failed."""
    root = settings or MvpSettings(service_name=WORKER_SERVICE_NAME)
    configure_logging(
        service_name=WORKER_SERVICE_NAME,
        log_level=root.log_level,
        json_output=root.log_json,
        env=root.env,
    )
    telemetry = configure_telemetry(
        service_name=WORKER_SERVICE_NAME, version=__version__, settings=root
    )
    try:
        asyncio.run(serve(root, internal_url=internal_url))
    except Exception:
        log.exception("worker.failed")
        return 1
    finally:
        telemetry.shutdown()
    return 0
