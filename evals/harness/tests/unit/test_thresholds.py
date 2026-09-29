"""Gates: a minimum, and for some a baseline suite to reach within a tolerance."""

from dataclasses import dataclass

from cw_evals.thresholds import Gate, GateResult, evaluate


@dataclass(frozen=True)
class Numbers:
    grounded_answer_rate: float | None


def test_a_gate_passes_at_its_minimum_and_fails_below_or_without_a_value() -> None:
    gate = Gate("grounded_answer_rate", 0.9, "scripted", "qa_kag")
    assert GateResult(gate, 0.9).passed
    assert not GateResult(gate, 0.89).passed
    assert not GateResult(gate, None).passed


def test_a_baseline_gate_needs_the_baseline_reached_within_its_tolerance() -> None:
    gate = Gate("grounded_answer_rate", 0.0, "scripted", "qa_kag", baseline="qa_hybrid")
    assert GateResult(gate, 0.8, 0.8).passed
    assert not GateResult(gate, 0.79, 0.8).passed
    assert not GateResult(gate, 0.8, None).passed
    lenient = Gate("grounded_answer_rate", 0.0, "gateway", "qa_kag", "qa_hybrid", tolerance=0.02)
    assert GateResult(lenient, 0.79, 0.8).passed
    assert not GateResult(lenient, 0.77, 0.8).passed


def test_evaluate_reads_each_gate_from_its_suite_and_its_baseline_from_the_other() -> None:
    suites: dict[str, dict[str, object]] = {
        "qa_kag": {"scripted": Numbers(1.0), "fake": Numbers(None)},
        "qa_hybrid": {"scripted": Numbers(0.87)},
    }
    results = {
        (r.gate.suite, r.gate.metric, r.gate.provider, r.gate.baseline): r
        for r in evaluate("ci", suites)
    }
    baseline = results["qa_kag", "grounded_answer_rate", "scripted", "qa_hybrid"]
    assert (baseline.value, baseline.baseline_value, baseline.passed) == (1.0, 0.87, True)
    alone = results["qa_kag", "grounded_answer_rate", "scripted", None]
    assert (alone.value, alone.passed) == (1.0, True)
    assert results["extraction", "parse_rate", "fake", None].value is None
    assert not results["qa_hybrid", "answer_safety", "fake", None].passed
