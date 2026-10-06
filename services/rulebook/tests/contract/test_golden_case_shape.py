"""Provider side of the golden export's contract with the eval harness: the case the rulebook
exports for the example decisions (``rulebook.testing.ExampleDecisions``) is the shared example
``packages/contracts/golden/extraction-case.example.yaml``, which the harness's own test loads
with its case loader (``evals/harness/tests/unit/test_exported_case.py``). The two sides share
the file, never an import. The version's id, new on every run, is the example's."""

from pathlib import Path
from typing import Any

import pytest
import yaml

import ontology as ontology_package
from rulebook.application.golden_export import ExportDecidedCandidates
from rulebook.golden import case_yaml
from rulebook.testing import START, ExampleDecisions

EXAMPLE = (
    Path(__file__).resolve().parents[4] / "packages/contracts/golden/extraction-case.example.yaml"
)
EXAMPLE_VERSION = "00000000-0000-4000-8000-00000000b001"


@pytest.mark.contract
def test_the_export_of_the_example_decisions_is_the_shared_example() -> None:
    decided = ExampleDecisions(ontology_package.load())
    (case,) = ExportDecidedCandidates(decided.store).run(START).cases
    exported: dict[str, Any] = yaml.safe_load(
        case_yaml(case.content).replace(str(case.rule_version_id), EXAMPLE_VERSION)
    )
    shared = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert exported == shared, (
        "the export changed: regenerate packages/contracts/golden/extraction-case.example.yaml "
        "from rulebook.testing.ExampleDecisions and run the eval harness's test of it"
    )
    assert (shared["label_status"], shared["reviewed_by"]) == ("draft", "")
