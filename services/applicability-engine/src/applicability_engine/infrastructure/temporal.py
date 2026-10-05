"""The fan-out workflows on Temporal, as the engine's ``FanOutWorkflows``.

``TemporalFanOuts.start`` starts ``applicability.fan_out`` on the ``applicability`` task queue
with the workflow id ``applicability-fan-out-<rule version id>`` and the id reuse policy
``REJECT_DUPLICATE``, so a version is fanned out once, ever: a second start, running or
finished, is refused and answers False. ``signal`` sends ``pause``, ``resume`` or ``cancel`` to
the version's workflow and never raises: a signal that cannot be delivered (no such workflow,
Temporal unreachable) is logged, and the workflow sees the change at its next poll.

The workflow is named, not imported, and its input is built here from the domain's
``FanOutStart`` in the shape of ``FanOutRequest`` (its fields, and any ``options``, such as a
smaller batch in tests), so infrastructure imports no application code.

The engine's controls are synchronous code on a thread (a route, a consumer's read phase), so
each call runs on an event loop of its own (``asyncio.run``) with a client connected for it
(``py_common.temporal.connect``: the settings' address, namespace and credentials, the pydantic
data converter). Starts and signals are rare, one per publication or control, so the connection
is not kept.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Final

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from applicability_engine.domain.fanout import (
    FAN_OUT_TASK_QUEUE,
    FAN_OUT_WORKFLOW,
    FanOutSignal,
    FanOutStart,
    fan_out_workflow_id,
)
from domain_kernel.ids import RuleVersionId
from py_common.logging import get_logger
from py_common.settings import Settings
from py_common.temporal import connect

log = get_logger(__name__)

TIMEOUT_SECONDS: Final = 10.0

Connect = Callable[[Settings], Awaitable[Client]]


def start_payload(
    start: FanOutStart, options: Mapping[str, object] | None = None
) -> dict[str, object]:
    """The workflow's input for ``start``: ``FanOutRequest``'s fields as JSON values."""
    payload: dict[str, object] = {
        "rule_version_id": str(start.rule_version_id),
        "rule_key": start.rule_key,
        "level": start.level.value,
        "trigger_event_id": str(start.trigger_event_id),
        "supersedes": [str(superseded) for superseded in start.supersedes],
        "correlation_id": None if start.correlation_id is None else str(start.correlation_id),
    }
    payload.update(options or {})
    return payload


class TemporalFanOuts:
    def __init__(
        self,
        settings: Settings,
        *,
        options: Mapping[str, object] | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
        connector: Connect = connect,
        task_queue: str = FAN_OUT_TASK_QUEUE,
    ) -> None:
        self._settings = settings
        self._options = dict(options or {})
        self._timeout = timeout_seconds
        self._connect = connector
        self._task_queue = task_queue

    def start(self, start: FanOutStart) -> bool:
        return asyncio.run(asyncio.wait_for(self._start(start), self._timeout))

    async def _start(self, start: FanOutStart) -> bool:
        client = await self._connect(self._settings)
        workflow_id = fan_out_workflow_id(start.rule_version_id)
        try:
            await client.start_workflow(
                FAN_OUT_WORKFLOW,
                start_payload(start, self._options),
                id=workflow_id,
                task_queue=self._task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            log.info("applicability.fanout_already_started", workflow_id=workflow_id)
            return False
        log.info("applicability.fanout_started", workflow_id=workflow_id)
        return True

    def signal(self, rule_version_id: RuleVersionId, signal: FanOutSignal) -> None:
        try:
            asyncio.run(asyncio.wait_for(self._signal(rule_version_id, signal), self._timeout))
        except Exception as exc:
            log.warning(
                "applicability.fanout_signal_failed",
                rule_version_id=str(rule_version_id),
                signal=signal.value,
                error=f"{type(exc).__name__}: {exc}",
            )

    async def _signal(self, rule_version_id: RuleVersionId, signal: FanOutSignal) -> None:
        client = await self._connect(self._settings)
        handle = client.get_workflow_handle(fan_out_workflow_id(rule_version_id))
        await handle.signal(signal.value)


class NoFanOutWorkflows:
    """``FanOutWorkflows`` where no workflow runs: the flag is off, or the store is in memory.
    Nothing starts, and a signal is dropped."""

    def start(self, start: FanOutStart) -> bool:
        return False

    def signal(self, rule_version_id: RuleVersionId, signal: FanOutSignal) -> None:
        log.debug(
            "applicability.fanout_signal_dropped",
            rule_version_id=str(rule_version_id),
            signal=signal.value,
        )
