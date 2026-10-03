"""The eval run: one suite of the eval harness under one profile, its gates, and the drift of each
gate against the previous run of the same suite and profile.

A gate is one threshold of the harness (``cw_evals.thresholds``): a metric of one provider's
aggregate held to a minimum, sometimes also to a baseline suite. Its name is stable across runs
(``suite.metric[provider]``, with ``>=baseline`` for a baseline gate), which is what drift matches
on. A run passes when every gate passes; a run with no gates measured nothing and does not pass.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain_kernel._validation import require_aware, require_bool, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import EntityId


@dataclass(frozen=True, slots=True)
class EvalRunId(EntityId):
    """One stored run of an eval suite."""


class Suite(StrEnum):
    """The harness's suites (``eval-harness --suite``)."""

    EXTRACTION = "extraction"
    RELATIONS = "relations"
    QA = "qa"


class Profile(StrEnum):
    """The harness's profiles: ``ci`` gates the scripted and fake providers, ``nightly`` a real
    model behind the gateway."""

    CI = "ci"
    NIGHTLY = "nightly"


@dataclass(frozen=True, slots=True)
class GateMeasurement:
    """What the harness measured for one gate. ``value`` is None when the run produced no
    aggregate for it, which fails the gate."""

    name: str
    metric: str
    threshold: float
    value: float | None
    passed: bool

    def __post_init__(self) -> None:
        require_text(self.name, "name")
        require_text(self.metric, "metric")
        require_instance(self.threshold, float, "threshold")
        if self.value is not None:
            require_instance(self.value, float, "value")
        require_bool(self.passed, "passed")


@dataclass(frozen=True, slots=True)
class GateResult:
    """A measured gate with the value the same gate had in the previous run, if any."""

    measurement: GateMeasurement
    previous_value: float | None = None

    @property
    def name(self) -> str:
        return self.measurement.name

    @property
    def passed(self) -> bool:
        return self.measurement.passed

    @property
    def drift(self) -> float | None:
        """This run's value less the previous run's; None when either is missing."""
        value = self.measurement.value
        if value is None or self.previous_value is None:
            return None
        return value - self.previous_value


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalRun:
    id: EvalRunId
    suite: Suite
    profile: Profile
    started_at: datetime
    completed_at: datetime
    gates: tuple[GateResult, ...]
    previous_run_id: EvalRunId | None = None

    def __post_init__(self) -> None:
        require_instance(self.id, EvalRunId, "id")
        require_instance(self.suite, Suite, "suite")
        require_instance(self.profile, Profile, "profile")
        require_aware(self.started_at, "started_at")
        require_aware(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise InvariantViolationError("completed_at must not precede started_at")
        names = [gate.name for gate in self.gates]
        if len(set(names)) != len(names):
            raise InvariantViolationError("gate names must be unique within a run")
        if self.previous_run_id is not None:
            require_instance(self.previous_run_id, EvalRunId, "previous_run_id")

    @classmethod
    def record(
        cls,
        *,
        suite: Suite,
        profile: Profile,
        started_at: datetime,
        completed_at: datetime,
        measurements: Sequence[GateMeasurement],
        previous: "EvalRun | None",
    ) -> "EvalRun":
        """A new run whose gates carry the previous run's values, matched by gate name."""
        before: Mapping[str, float | None] = (
            {} if previous is None else {g.name: g.measurement.value for g in previous.gates}
        )
        return cls(
            id=EvalRunId.new(),
            suite=suite,
            profile=profile,
            started_at=started_at,
            completed_at=completed_at,
            gates=tuple(GateResult(m, before.get(m.name)) for m in measurements),
            previous_run_id=None if previous is None else previous.id,
        )

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(gate.passed for gate in self.gates)

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(gate.name for gate in self.gates if not gate.passed)

    @property
    def regressed_gates(self) -> tuple[str, ...]:
        """Gates whose value fell since the previous run, whether or not they still pass."""
        return tuple(gate.name for gate in self.gates if gate.drift is not None and gate.drift < 0)
