"""What the Temporal adapter sends: the workflow's input in the shape the workflow reads, the
workflow id and the reuse policy, and signals that never raise."""

import asyncio
from typing import Any

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from applicability_engine.application.fanout_flow import FanOutRequest
from applicability_engine.domain.fanout import FanOutSignal, FanOutStart
from applicability_engine.infrastructure.temporal import (
    NoFanOutWorkflows,
    TemporalFanOuts,
    start_payload,
)
from domain_kernel.ids import CorrelationId, EventId, RuleVersionId
from domain_kernel.ontology import AttributeLevel
from py_common.settings import Settings

SETTINGS = Settings(_env_file=None, service_name="applicability-engine")
START = FanOutStart(
    rule_version_id=RuleVersionId.new(),
    rule_key="gstr9_annual",
    level=AttributeLevel.REGISTRATION,
    trigger_event_id=EventId.new(),
    supersedes=(RuleVersionId.new(),),
    correlation_id=CorrelationId.new(),
)


class FakeHandle:
    def __init__(self, client: "FakeClient", workflow_id: str) -> None:
        self._client = client
        self._workflow_id = workflow_id

    async def signal(self, name: str) -> None:
        if self._client.unreachable:
            raise ConnectionError("temporal is down")
        self._client.signals.append((self._workflow_id, name))


class FakeClient:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.signals: list[tuple[str, str]] = []
        self.unreachable = False

    async def start_workflow(self, workflow: str, arg: object, **options: Any) -> None:
        if any(seen["id"] == options["id"] for seen in self.starts):
            raise WorkflowAlreadyStartedError(options["id"], workflow)
        self.starts.append({"workflow": workflow, "arg": arg, **options})

    def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
        return FakeHandle(self, workflow_id)


def adapter(client: FakeClient, **options: object) -> TemporalFanOuts:
    async def connect(settings: Settings) -> Client:
        return client  # type: ignore[return-value]

    return TemporalFanOuts(SETTINGS, options=options, connector=connect)


def test_the_payload_is_what_the_workflow_reads() -> None:
    request = FanOutRequest.model_validate(start_payload(START, {"batch_size": 10}))
    assert request.start() == START
    assert request.batch_size == 10
    assert request == FanOutRequest.of(START, batch_size=10)


def test_a_version_starts_once_with_its_id_on_the_applicability_queue() -> None:
    client = FakeClient()
    fanouts = adapter(client, poll_seconds=1.0)
    assert fanouts.start(START) is True
    assert fanouts.start(START) is False, "a duplicate start is refused"
    (started,) = client.starts
    assert started["workflow"] == "applicability.fan_out"
    assert started["id"] == f"applicability-fan-out-{START.rule_version_id}"
    assert started["task_queue"] == "applicability"
    assert started["id_reuse_policy"] is WorkflowIDReusePolicy.REJECT_DUPLICATE
    assert started["arg"]["poll_seconds"] == 1.0


def test_signals_go_by_name_and_a_failure_is_only_logged() -> None:
    client = FakeClient()
    fanouts = adapter(client)
    fanouts.signal(START.rule_version_id, FanOutSignal.PAUSE)
    assert client.signals == [(f"applicability-fan-out-{START.rule_version_id}", "pause")]
    client.unreachable = True
    fanouts.signal(START.rule_version_id, FanOutSignal.RESUME)
    assert len(client.signals) == 1


def test_where_nothing_runs_nothing_starts_and_signals_are_dropped() -> None:
    nothing = NoFanOutWorkflows()
    assert nothing.start(START) is False
    nothing.signal(START.rule_version_id, FanOutSignal.CANCEL)


async def test_an_async_caller_runs_the_adapter_on_a_thread() -> None:
    client = FakeClient()
    assert await asyncio.to_thread(adapter(client).start, START) is True
    assert len(client.starts) == 1
