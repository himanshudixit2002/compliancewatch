"""What blocks a merge, per profile.

``ci`` runs on every change with the scripted answers and the fake provider: no model is
involved, so it gates what is deterministic. The scripted run must score 1.0 (the harness and
the validators agree with the labels), the detector must be right on at least 90% of labelled
fields, and every labelled case must parse. ``nightly`` runs against a real model through the
gateway and gates the guide's section 8 numbers: extraction acceptance at or above 0.90 and
citation validity at or above 0.95. The fake provider's own scores are reported, never gated:
it answers placeholders by design.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from cw_evals.metrics import Aggregate

PROFILES = ("ci", "nightly")


@dataclass(frozen=True, slots=True)
class Gate:
    metric: str
    minimum: float
    provider: str
    """Which provider's aggregate the gate reads."""


GATES: Mapping[str, tuple[Gate, ...]] = {
    "ci": (
        Gate("extraction_acceptance", 1.0, "scripted"),
        Gate("citation_validity", 1.0, "scripted"),
        Gate("validator_pass_rate", 1.0, "scripted"),
        Gate("detector_accuracy", 0.9, "scripted"),
        Gate("parse_rate", 1.0, "fake"),
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

    @property
    def passed(self) -> bool:
        return self.value is not None and self.value >= self.gate.minimum


def evaluate(profile: str, aggregates: Mapping[str, Aggregate]) -> list[GateResult]:
    results = []
    for gate in GATES[profile]:
        aggregate = aggregates.get(gate.provider)
        value = None if aggregate is None else float(getattr(aggregate, gate.metric))
        results.append(GateResult(gate, value))
    return results
