"""The shape every activity follows.

An activity is a class: ``name`` is its Temporal activity type, ``input_type`` and
``output_type`` say what crosses the wire, ``retry_policy``, ``start_to_close`` and
``heartbeat_timeout`` are declared next to the code they protect, and ``execute`` is the
template method: ``validate`` the input, ``run`` it, ``record`` the outcome. A workflow calls
``SomeActivity.schedule(input)`` and never repeats the timeouts; a worker registers
``SomeActivity(...).definition()``. Log lines inside an activity carry the workflow id, the
activity id and the attempt.
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, ClassVar

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from py_common.logging import get_logger

log = get_logger(__name__)

DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=5,
)


class ActivityBase[ActivityInput, ActivityOutput](ABC):
    name: ClassVar[str]
    input_type: ClassVar[type[Any]]
    output_type: ClassVar[type[Any]]
    retry_policy: ClassVar[RetryPolicy] = DEFAULT_RETRY_POLICY
    start_to_close: ClassVar[timedelta] = timedelta(minutes=5)
    heartbeat_timeout: ClassVar[timedelta | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attribute in ("name", "input_type", "output_type"):
            if not hasattr(cls, attribute):
                raise TypeError(f"{cls.__name__} must declare {attribute}")
        if not cls.name.strip():
            raise TypeError(f"{cls.__name__}.name must not be blank")
        if cls.start_to_close <= timedelta(0):
            raise TypeError(f"{cls.__name__}.start_to_close must be positive")

    def validate(self, input: ActivityInput) -> None:  # noqa: B027 (optional hook)
        """Reject a malformed input before any work happens. Raise to fail the attempt."""

    @abstractmethod
    async def run(self, input: ActivityInput) -> ActivityOutput:
        """The work. Long loops call ``self.heartbeat()``."""

    def record(self, input: ActivityInput, result: ActivityOutput) -> None:  # noqa: B027
        """Bookkeeping after a successful run (metrics, a log line). Must not raise."""

    async def execute(self, input: ActivityInput) -> ActivityOutput:
        """The template method the worker runs."""
        with structlog.contextvars.bound_contextvars(**_activity_context()):
            self.validate(input)
            result = await self.run(input)
            try:
                self.record(input, result)
            except Exception:
                log.exception("activity.record_failed", activity=self.name)
            return result

    def heartbeat(self, *details: Any) -> None:
        """Report progress; a no-op outside an activity so unit tests can call ``run`` directly."""
        if activity.in_activity():
            activity.heartbeat(*details)

    def definition(self) -> Callable[[ActivityInput], Awaitable[ActivityOutput]]:
        """The callable a ``Worker`` registers: typed with the declared input and output."""
        instance = self

        async def run(input: ActivityInput) -> ActivityOutput:
            return await instance.execute(input)

        run.__name__ = self.name
        run.__qualname__ = f"{type(self).__qualname__}.{self.name}"
        run.__annotations__ = {"input": self.input_type, "return": self.output_type}
        defined: Callable[[ActivityInput], Awaitable[ActivityOutput]] = activity.defn(
            name=self.name
        )(run)
        return defined

    @classmethod
    def schedule(cls, input: ActivityInput) -> Awaitable[ActivityOutput]:
        """Run the activity from inside a workflow with the class's own timeouts and retries."""
        handle: Awaitable[ActivityOutput] = workflow.execute_activity(
            cls.name,
            input,
            result_type=cls.output_type,
            start_to_close_timeout=cls.start_to_close,
            heartbeat_timeout=cls.heartbeat_timeout,
            retry_policy=cls.retry_policy,
        )
        return handle


def _activity_context() -> dict[str, Any]:
    if not activity.in_activity():
        return {}
    info = activity.info()
    return {
        "workflow_id": info.workflow_id,
        "workflow_run_id": info.workflow_run_id,
        "activity_id": info.activity_id,
        "activity_type": info.activity_type,
        "attempt": info.attempt,
        "task_queue": info.task_queue,
    }


async def sleep_with_heartbeat(seconds: float, *, every: float = 1.0) -> None:
    """Wait ``seconds`` while heartbeating, so a cancelled workflow stops the activity promptly."""
    remaining = seconds
    while remaining > 0:
        step = min(every, remaining)
        await asyncio.sleep(step)
        remaining -= step
        if activity.in_activity():
            activity.heartbeat()
