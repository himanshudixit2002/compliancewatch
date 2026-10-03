"""Events the eval service publishes; payload fields follow packages/contracts/events.

Eval runs are platform data, not a tenant's, so the events carry no tenant id.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from domain_kernel._validation import require_aware, require_bool, require_instance, require_int
from domain_kernel.events import DomainEvent
from eval_service.domain.model import EvalRun, EvalRunId, Profile, Suite


@dataclass(frozen=True, slots=True, kw_only=True)
class EvalRunCompleted(DomainEvent):
    topic: ClassVar[str] = "eval.run.completed"
    schema_version: ClassVar[str] = "1.0.0"

    run_id: EvalRunId
    suite: Suite
    profile: Profile
    passed: bool
    gates_total: int
    failed_gates: tuple[str, ...]
    regressed_gates: tuple[str, ...]
    previous_run_id: EvalRunId | None
    started_at: datetime
    completed_at: datetime

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        require_instance(self.run_id, EvalRunId, "run_id")
        require_instance(self.suite, Suite, "suite")
        require_instance(self.profile, Profile, "profile")
        require_bool(self.passed, "passed")
        require_int(self.gates_total, "gates_total", minimum=0)
        require_instance(self.failed_gates, tuple, "failed_gates")
        require_instance(self.regressed_gates, tuple, "regressed_gates")
        if self.previous_run_id is not None:
            require_instance(self.previous_run_id, EvalRunId, "previous_run_id")
        require_aware(self.started_at, "started_at")
        require_aware(self.completed_at, "completed_at")

    @classmethod
    def of(cls, run: EvalRun) -> "EvalRunCompleted":
        return cls(
            run_id=run.id,
            suite=run.suite,
            profile=run.profile,
            passed=run.passed,
            gates_total=len(run.gates),
            failed_gates=run.failed_gates,
            regressed_gates=run.regressed_gates,
            previous_run_id=run.previous_run_id,
            started_at=run.started_at,
            completed_at=run.completed_at,
        )
