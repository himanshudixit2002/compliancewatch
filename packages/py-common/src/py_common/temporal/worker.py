"""Build and run a worker from workflow classes and activity instances.

While the worker runs, its task queue reports ``temporal_worker_up`` (``liveness.running``).
"""

import asyncio
import signal
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from py_common.logging import get_logger
from py_common.settings import Settings
from py_common.temporal.activity import ActivityBase
from py_common.temporal.client import connect
from py_common.temporal.liveness import running

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    task_queue: str
    max_concurrent_activities: int = 20
    max_concurrent_workflow_tasks: int = 20

    def __post_init__(self) -> None:
        if not self.task_queue.strip():
            raise ValueError("task_queue must not be blank")
        if self.max_concurrent_activities < 1 or self.max_concurrent_workflow_tasks < 1:
            raise ValueError("concurrency limits must be at least 1")


def build_worker(
    client: Client,
    config: WorkerConfig,
    *,
    workflows: Sequence[type[Any]],
    activities: Sequence[ActivityBase[Any, Any]],
) -> Worker:
    names = [activity.name for activity in activities]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate activity names: {sorted(names)}")
    return Worker(
        client,
        task_queue=config.task_queue,
        workflows=list(workflows),
        activities=[activity.definition() for activity in activities],
        max_concurrent_activities=config.max_concurrent_activities,
        max_concurrent_workflow_tasks=config.max_concurrent_workflow_tasks,
    )


def install_stop_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)


async def run_worker(
    settings: Settings,
    config: WorkerConfig,
    *,
    workflows: Sequence[type[Any]],
    activities: Sequence[ActivityBase[Any, Any]],
    stop: asyncio.Event | None = None,
    client: Client | None = None,
) -> None:
    """Run until ``stop`` is set or a SIGTERM/SIGINT arrives. The task queue reports as up
    while the worker runs, and stops reporting when it stops or fails."""
    stop = stop or asyncio.Event()
    install_stop_signals(stop)
    client = client or await connect(settings)
    worker = build_worker(client, config, workflows=workflows, activities=activities)
    log.info(
        "worker.started",
        task_queue=config.task_queue,
        temporal_address=settings.temporal_address,
        namespace=settings.temporal_namespace,
        workflows=[workflow.__name__ for workflow in workflows],
        activities=[activity.name for activity in activities],
    )
    with running(config.task_queue):
        async with worker:
            await stop.wait()
    log.info("worker.stopped", task_queue=config.task_queue)
