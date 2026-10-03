"""Request and response bodies of the eval API."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eval_service.domain.model import EvalRun, GateResult, Profile, Suite


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: Suite = Field(description="The harness suite to run")
    profile: Profile = Field(
        default=Profile.CI,
        description="ci: scripted and fake providers, no tokens; nightly: a real model through "
        "the gateway",
    )


class GateOut(BaseModel):
    """One gate. ``previous_value`` is the same gate's value in the previous run of the suite
    and profile, and ``drift`` this value less that one; both are null without one of them."""

    name: str
    metric: str
    threshold: float
    value: float | None
    passed: bool
    previous_value: float | None
    drift: float | None

    @classmethod
    def from_gate(cls, gate: GateResult) -> "GateOut":
        return cls(
            name=gate.name,
            metric=gate.measurement.metric,
            threshold=gate.measurement.threshold,
            value=gate.measurement.value,
            passed=gate.passed,
            previous_value=gate.previous_value,
            drift=gate.drift,
        )


class RunSummaryOut(BaseModel):
    """One run without its gates. ``passed`` is true when every gate passed."""

    run_id: UUID
    suite: Suite
    profile: Profile
    started_at: datetime
    completed_at: datetime
    passed: bool
    gates_total: int
    failed_gates: list[str]
    regressed_gates: list[str]
    previous_run_id: UUID | None

    @classmethod
    def from_run(cls, run: EvalRun) -> "RunSummaryOut":
        return cls(
            run_id=run.id.value,
            suite=run.suite,
            profile=run.profile,
            started_at=run.started_at.astimezone(UTC),
            completed_at=run.completed_at.astimezone(UTC),
            passed=run.passed,
            gates_total=len(run.gates),
            failed_gates=list(run.failed_gates),
            regressed_gates=list(run.regressed_gates),
            previous_run_id=None if run.previous_run_id is None else run.previous_run_id.value,
        )


class RunOut(RunSummaryOut):
    """One run with every gate, in the harness's order."""

    gates: list[GateOut]

    @classmethod
    def from_run(cls, run: EvalRun) -> "RunOut":
        summary = RunSummaryOut.from_run(run).model_dump()
        return cls(**summary, gates=[GateOut.from_gate(gate) for gate in run.gates])
