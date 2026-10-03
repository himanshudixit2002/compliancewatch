"""Builders for tests of this service: settings on the memory store, a ticking clock and a
suite runner that answers measured gates without the harness."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from eval_service.domain.errors import EvalHarnessError
from eval_service.domain.model import GateMeasurement, Profile, Suite
from eval_service.settings import EvalSettings

NOW = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)


def eval_settings(**overrides: Any) -> EvalSettings:
    """Settings that ignore the repo ``.env``; the memory store, so no Postgres is needed."""
    values: dict[str, Any] = {"_env_file": None, "service_name": "eval", "eval_store": "memory"}
    values.update(overrides)
    return EvalSettings(**values)


class TickingClock:
    """Each call is one second after the previous one, from ``NOW``."""

    def __init__(self, start: datetime = NOW) -> None:
        self._next = start

    def __call__(self) -> datetime:
        now = self._next
        self._next = now + timedelta(seconds=1)
        return now


def gate(
    name: str = "relations.relation_recall[scripted]",
    value: float | None = 1.0,
    threshold: float = 1.0,
) -> GateMeasurement:
    """A measured gate; it passes when the value reaches the threshold."""
    metric = name.split(".", 1)[1].split("[", 1)[0]
    passed = value is not None and value >= threshold
    return GateMeasurement(
        name=name, metric=metric, threshold=threshold, value=value, passed=passed
    )


class ScriptedRunner:
    """Answers the next scripted list of gates on every run (the last one again once they run
    out), or raises ``EvalHarnessError`` when ``failure`` is set. ``calls`` records each run."""

    def __init__(self, *answers: Sequence[GateMeasurement], failure: str | None = None) -> None:
        self._answers = list(answers) or [[gate()]]
        self._failure = failure
        self.calls: list[tuple[Suite, Profile]] = []

    def run(self, suite: Suite, profile: Profile) -> Sequence[GateMeasurement]:
        self.calls.append((suite, profile))
        if self._failure is not None:
            raise EvalHarnessError(self._failure)
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
