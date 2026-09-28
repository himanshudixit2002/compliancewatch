from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar

import pytest
from temporalio.common import RetryPolicy
from temporalio.testing import ActivityEnvironment

from py_common.temporal.activity import DEFAULT_RETRY_POLICY, ActivityBase, sleep_with_heartbeat


@dataclass(frozen=True)
class AddRequest:
    left: int
    right: int


@dataclass(frozen=True)
class AddResult:
    total: int


class Add(ActivityBase[AddRequest, AddResult]):
    name: ClassVar[str] = "add"
    input_type: ClassVar[type[AddRequest]] = AddRequest
    output_type: ClassVar[type[AddResult]] = AddResult
    start_to_close: ClassVar[timedelta] = timedelta(seconds=30)
    retry_policy: ClassVar[RetryPolicy] = RetryPolicy(maximum_attempts=2)

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_record = False

    def validate(self, input: AddRequest) -> None:
        self.calls.append("validate")
        if input.left < 0 or input.right < 0:
            raise ValueError("operands must not be negative")

    async def run(self, input: AddRequest) -> AddResult:
        self.calls.append("run")
        self.heartbeat("adding")
        return AddResult(total=input.left + input.right)

    def record(self, input: AddRequest, result: AddResult) -> None:
        self.calls.append("record")
        if self.fail_record:
            raise RuntimeError("metrics backend down")


async def test_execute_runs_the_template_in_order() -> None:
    add = Add()
    assert await add.execute(AddRequest(2, 3)) == AddResult(5)
    assert add.calls == ["validate", "run", "record"]


async def test_validate_stops_the_run() -> None:
    add = Add()
    with pytest.raises(ValueError, match="negative"):
        await add.execute(AddRequest(-1, 3))
    assert add.calls == ["validate"]


async def test_a_failing_record_does_not_fail_the_activity() -> None:
    add = Add()
    add.fail_record = True
    assert await add.execute(AddRequest(1, 1)) == AddResult(2)
    assert add.calls == ["validate", "run", "record"]


async def test_definition_is_a_typed_temporal_activity() -> None:
    add = Add()
    definition = add.definition()
    assert definition.__name__ == "add"
    assert definition.__annotations__ == {"input": AddRequest, "return": AddResult}
    result = await ActivityEnvironment().run(definition, AddRequest(4, 5))
    assert result == AddResult(9)
    assert add.calls == ["validate", "run", "record"]


async def test_heartbeat_is_delivered_inside_an_activity() -> None:
    heartbeats: list[object] = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *details: heartbeats.append(details)
    await environment.run(Add().definition(), AddRequest(1, 2))
    assert heartbeats == [("adding",)]


async def test_heartbeat_outside_an_activity_is_a_no_op() -> None:
    Add().heartbeat("ignored")


def test_declared_policy_and_timeouts() -> None:
    assert Add.retry_policy.maximum_attempts == 2
    assert Add.start_to_close == timedelta(seconds=30)
    assert Add.heartbeat_timeout is None
    assert DEFAULT_RETRY_POLICY.maximum_attempts == 5
    assert DEFAULT_RETRY_POLICY.maximum_interval == timedelta(minutes=1)


def test_subclasses_must_declare_their_shape() -> None:
    with pytest.raises(TypeError, match="must declare name"):

        class Nameless(ActivityBase[int, int]):
            input_type: ClassVar[type[int]] = int
            output_type: ClassVar[type[int]] = int

            async def run(self, input: int) -> int:
                return input

    with pytest.raises(TypeError, match="name must not be blank"):

        class Blank(ActivityBase[int, int]):
            name: ClassVar[str] = " "
            input_type: ClassVar[type[int]] = int
            output_type: ClassVar[type[int]] = int

            async def run(self, input: int) -> int:
                return input

    with pytest.raises(TypeError, match="start_to_close must be positive"):

        class Instant(ActivityBase[int, int]):
            name: ClassVar[str] = "instant"
            input_type: ClassVar[type[int]] = int
            output_type: ClassVar[type[int]] = int
            start_to_close: ClassVar[timedelta] = timedelta(0)

            async def run(self, input: int) -> int:
                return input


async def test_sleep_with_heartbeat_waits_the_whole_duration() -> None:
    await sleep_with_heartbeat(0.03, every=0.01)
