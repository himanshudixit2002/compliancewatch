"""The worker process's health: whether every loop it hosts is running and its event loop is not
stuck.

``WorkerHealth`` knows the loops (``<service>/<component>``) and Temporal task queues the worker
hosts. ``heartbeat`` runs on the worker's event loop and, every interval, records which of them
are running (``py_common.runtime.running_loops`` and ``py_common.temporal.liveness``). The
health app answers on its own thread (``HealthServer``), so it still answers when the worker's
event loop is blocked:

- ``GET /health``: 200 while the last heartbeat is younger than the stale limit and every
  hosted loop and queue was running at it; 503 otherwise, which makes the platform restart the
  process;
- ``GET /loops``: the detail, always 200: each loop and queue with whether it runs, and the age
  of the last heartbeat.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from cw_mvp.serve import listener
from py_common.runtime import running_loops
from py_common.temporal.liveness import running_queues

STARTUP_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class HealthReport:
    healthy: bool
    heartbeat_age_seconds: float | None
    stale_after_seconds: float
    loops: dict[str, bool]
    task_queues: dict[str, bool]

    def as_json(self) -> dict[str, Any]:
        return {
            "status": "ok" if self.healthy else "unhealthy",
            "heartbeat_age_seconds": self.heartbeat_age_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "loops": self.loops,
            "task_queues": self.task_queues,
        }


@dataclass
class WorkerHealth:
    """What the worker hosts and what its last heartbeat saw. Thread-safe: the heartbeat writes
    on the worker's loop, the health app reads on its own thread."""

    loops: tuple[str, ...]
    task_queues: tuple[str, ...]
    stale_after_seconds: float
    clock: Callable[[], float] = time.monotonic
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _beat_at: float | None = None
    _running_loops: frozenset[str] = frozenset()
    _running_queues: frozenset[str] = frozenset()

    def beat(self, *, loops: Iterable[str], task_queues: Iterable[str]) -> None:
        with self._lock:
            self._beat_at = self.clock()
            self._running_loops = frozenset(loops)
            self._running_queues = frozenset(task_queues)

    def report(self) -> HealthReport:
        with self._lock:
            beat_at, loops, queues = self._beat_at, self._running_loops, self._running_queues
        age = None if beat_at is None else max(self.clock() - beat_at, 0.0)
        loop_states = {loop: loop in loops for loop in self.loops}
        queue_states = {queue: queue in queues for queue in self.task_queues}
        healthy = (
            age is not None
            and age <= self.stale_after_seconds
            and all(loop_states.values())
            and all(queue_states.values())
        )
        return HealthReport(
            healthy=healthy,
            heartbeat_age_seconds=None if age is None else round(age, 3),
            stale_after_seconds=self.stale_after_seconds,
            loops=loop_states,
            task_queues=queue_states,
        )


async def heartbeat(health: WorkerHealth, stop: asyncio.Event, *, interval: float) -> None:
    """Record what runs every ``interval`` seconds until ``stop`` is set."""
    while not stop.is_set():
        health.beat(loops=running_loops(), task_queues=running_queues())
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue


def health_app(health: WorkerHealth) -> Starlette:
    async def healthy(_: Request) -> JSONResponse:
        report = health.report()
        return JSONResponse(report.as_json(), status_code=200 if report.healthy else 503)

    async def loops(_: Request) -> JSONResponse:
        return JSONResponse(health.report().as_json())

    return Starlette(routes=[Route("/health", healthy), Route("/loops", loops)])


class HealthServer:
    """The health app served by uvicorn on a thread of its own, on ``host`` and ``port``."""

    def __init__(self, app: Starlette, host: str, port: int) -> None:
        self._socket = listener(host, port)
        config = uvicorn.Config(app, lifespan="off", log_config=None, access_log=False)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [self._socket]},
            name="cw-worker-health",
            daemon=True,
        )

    @property
    def port(self) -> int:
        bound: int = self._socket.getsockname()[1]
        return bound

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + STARTUP_SECONDS
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the worker's health server did not start")
            time.sleep(0.01)

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(STARTUP_SECONDS)
        self._socket.close()
