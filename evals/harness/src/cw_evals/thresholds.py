"""What blocks a merge, per profile.

``ci`` runs on every change with the scripted answers and the fake provider: no model is
involved, so it gates what is deterministic. The scripted run must score 1.0 (the harness and
the validators agree with the labels), the detector must be right on at least 90% of labelled
fields, and every labelled case must parse. ``nightly`` runs against a real model through the
gateway and gates the guide's section 8 numbers: extraction acceptance at or above 0.90 and
citation validity at or above 0.95. The fake provider's own scores are reported, never gated:
it answers placeholders by design.

The relation suite (``suite="relations"``) is gated in ``ci`` the same way: the scripted run must
find every labelled relation with valid evidence, and the fake provider's answers must parse.
Its nightly numbers are reported but not gated until at least five cases are reviewed.

The qa suites are the KAG golden questions with the KAG layer on (``qa_kag``) and off
(``qa_hybrid``, the baseline). In ``ci`` the scripted KAG run must score 1.0 on every gated
metric and be grounded at least as often as the scripted hybrid run (a gate with a
``baseline``); the hybrid run must still refuse what it must and never cite a clause that does
not hold. The fake provider must answer every question with a valid body and never unsafely.
Nightly, qa is reported, not gated, until the cases are reviewed.
"""

from collections.abc import Mapping
from dataclasses import dataclass

PROFILES = ("ci", "nightly")


@dataclass(frozen=True, slots=True)
class Gate:
    metric: str
    minimum: float
    provider: str
    """Which provider's aggregate the gate reads."""
    suite: str = "extraction"
    baseline: str | None = None
    """Another suite whose value of the same metric, for the same provider, this one must reach
    (less ``tolerance``) on top of ``minimum``."""
    tolerance: float = 0.0


GATES: Mapping[str, tuple[Gate, ...]] = {
    "ci": (
        Gate("extraction_acceptance", 1.0, "scripted"),
        Gate("citation_validity", 1.0, "scripted"),
        Gate("validator_pass_rate", 1.0, "scripted"),
        Gate("detector_accuracy", 0.9, "scripted"),
        Gate("parse_rate", 1.0, "fake"),
        Gate("relation_recall", 1.0, "scripted", "relations"),
        Gate("relation_precision", 1.0, "scripted", "relations"),
        Gate("evidence_validity", 1.0, "scripted", "relations"),
        Gate("relation_parse_rate", 1.0, "fake", "relations"),
        Gate("plan_validity", 1.0, "scripted", "qa_kag"),
        Gate("solver_success", 1.0, "scripted", "qa_kag"),
        Gate("citation_correctness", 1.0, "scripted", "qa_kag"),
        Gate("refusal_accuracy", 1.0, "scripted", "qa_kag"),
        Gate("answer_safety", 1.0, "scripted", "qa_kag"),
        Gate("grounded_answer_rate", 1.0, "scripted", "qa_kag"),
        Gate("grounded_answer_rate", 0.0, "scripted", "qa_kag", baseline="qa_hybrid"),
        Gate("refusal_accuracy", 1.0, "scripted", "qa_hybrid"),
        Gate("answer_safety", 1.0, "scripted", "qa_hybrid"),
        Gate("response_rate", 1.0, "fake", "qa_kag"),
        Gate("answer_safety", 1.0, "fake", "qa_kag"),
        Gate("response_rate", 1.0, "fake", "qa_hybrid"),
        Gate("answer_safety", 1.0, "fake", "qa_hybrid"),
    ),
    "nightly": (
        Gate("extraction_acceptance", 0.90, "gateway"),
        Gate("citation_validity", 0.95, "gateway"),
        Gate("parse_rate", 0.98, "gateway"),
    ),
}


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: Gate
    value: float | None
    baseline_value: float | None = None

    @property
    def passed(self) -> bool:
        if self.value is None or self.value < self.gate.minimum:
            return False
        if self.gate.baseline is None:
            return True
        return (
            self.baseline_value is not None
            and self.value >= self.baseline_value - self.gate.tolerance
        )


def evaluate(profile: str, suites: Mapping[str, Mapping[str, object]]) -> list[GateResult]:
    """Each gate of the profile against the aggregate of its suite and provider; ``suites``
    maps a suite name to its aggregates by provider. A gate whose aggregate or value is missing
    fails, and so does one whose baseline is missing."""
    results = []
    for gate in GATES[profile]:
        baseline = None
        if gate.baseline is not None:
            baseline = _value(suites, gate.baseline, gate.provider, gate.metric)
        results.append(
            GateResult(gate, _value(suites, gate.suite, gate.provider, gate.metric), baseline)
        )
    return results


def _value(
    suites: Mapping[str, Mapping[str, object]], suite: str, provider: str, metric: str
) -> float | None:
    aggregate = suites.get(suite, {}).get(provider)
    value = None if aggregate is None else getattr(aggregate, metric, None)
    return None if value is None else float(value)
