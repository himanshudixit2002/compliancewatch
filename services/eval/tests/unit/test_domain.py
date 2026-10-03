"""The eval run: gate results, drift against the previous run, pass and regressions."""

from datetime import timedelta

import pytest

from domain_kernel.errors import InvariantViolationError
from eval_service.domain.events import EvalRunCompleted
from eval_service.domain.model import (
    EvalRun,
    EvalRunId,
    GateMeasurement,
    GateResult,
    Profile,
    Suite,
)
from eval_service.testing import NOW, gate

RECALL = "relations.relation_recall[scripted]"
PRECISION = "relations.relation_precision[scripted]"


def record(*measurements: GateMeasurement, previous: EvalRun | None = None) -> EvalRun:
    return EvalRun.record(
        suite=Suite.RELATIONS,
        profile=Profile.CI,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        measurements=measurements,
        previous=previous,
    )


def test_drift_is_the_change_since_the_previous_value() -> None:
    assert GateResult(gate(value=0.9), previous_value=1.0).drift == pytest.approx(-0.1)
    assert GateResult(gate(value=1.0)).drift is None
    assert GateResult(gate(value=None), previous_value=1.0).drift is None


def test_a_first_run_has_no_previous_values() -> None:
    run = record(gate(RECALL), gate(PRECISION))
    assert run.previous_run_id is None
    assert [g.previous_value for g in run.gates] == [None, None]
    assert run.passed
    assert run.failed_gates == ()
    assert run.regressed_gates == ()


def test_a_later_run_matches_the_previous_gates_by_name() -> None:
    first = record(gate(RECALL, 1.0), gate(PRECISION, 1.0))
    second = record(
        gate(RECALL, 0.5), gate(PRECISION, 1.0), gate("relations.new[fake]"), previous=first
    )
    assert second.previous_run_id == first.id
    assert [g.previous_value for g in second.gates] == [1.0, 1.0, None]
    assert not second.passed
    assert second.failed_gates == (RECALL,)
    assert second.regressed_gates == (RECALL,)


def test_a_gate_that_falls_but_still_passes_is_a_regression() -> None:
    first = record(gate(RECALL, 0.95, threshold=0.9))
    second = record(gate(RECALL, 0.92, threshold=0.9), previous=first)
    assert second.passed
    assert second.regressed_gates == (RECALL,)


def test_a_run_without_gates_does_not_pass() -> None:
    assert not record().passed


def test_gate_names_are_unique_within_a_run() -> None:
    with pytest.raises(InvariantViolationError, match="unique"):
        record(gate(RECALL), gate(RECALL))


def test_a_run_cannot_complete_before_it_started() -> None:
    with pytest.raises(InvariantViolationError, match="precede"):
        EvalRun(
            id=EvalRunId.new(),
            suite=Suite.QA,
            profile=Profile.NIGHTLY,
            started_at=NOW,
            completed_at=NOW - timedelta(seconds=1),
            gates=(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("name", ""), ("metric", " "), ("threshold", 1), ("value", "1.0"), ("passed", 1)],
)
def test_a_measurement_refuses_bad_values(field: str, value: object) -> None:
    values: dict[str, object] = {
        "name": RECALL,
        "metric": "relation_recall",
        "threshold": 1.0,
        "value": 1.0,
        "passed": True,
    }
    values[field] = value
    with pytest.raises(InvariantViolationError):
        GateMeasurement(**values)  # type: ignore[arg-type]


def test_the_completed_event_summarises_the_run() -> None:
    first = record(gate(RECALL, 1.0))
    run = record(gate(RECALL, 0.0), previous=first)
    event = EvalRunCompleted.of(run)
    assert event.tenant_id is None
    assert event.run_id == run.id
    assert (event.suite, event.profile) == (Suite.RELATIONS, Profile.CI)
    assert not event.passed
    assert event.gates_total == 1
    assert event.failed_gates == (RECALL,)
    assert event.regressed_gates == (RECALL,)
    assert event.previous_run_id == first.id
    assert (event.started_at, event.completed_at) == (run.started_at, run.completed_at)
