"""The real harness, run the way the service runs it: its report gives the gates of a suite.

The relation suite under ``ci`` is the quickest one (scripted and fake providers, no tokens, a
second or two); it pins the command line and the ``latest.json`` shape the runner reads.
"""

from pathlib import Path

from eval_service.domain.model import Profile, Suite
from eval_service.infrastructure.harness import HarnessSuiteRunner

GOLDEN = Path(__file__).resolve().parents[4] / "evals" / "golden"


def test_the_relation_suite_passes_its_ci_gates() -> None:
    runner = HarnessSuiteRunner(
        golden_dir=GOLDEN, gateway_url="http://localhost:8008", timeout_seconds=300
    )
    gates = runner.run(Suite.RELATIONS, Profile.CI)
    assert {gate.name for gate in gates} == {
        "relations.relation_recall[scripted]",
        "relations.relation_precision[scripted]",
        "relations.evidence_validity[scripted]",
        "relations.relation_parse_rate[fake]",
    }
    assert all(gate.passed and gate.value is not None for gate in gates)
