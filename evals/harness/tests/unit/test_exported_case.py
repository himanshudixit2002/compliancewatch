"""Consumer side of the golden export's contract: the rulebook's exported case
(``packages/contracts/golden/extraction-case.example.yaml``, which the rulebook's contract test
keeps equal to its export) loads with the harness's case loader as a labelled draft, and its
``expected`` is a candidate the validators accept against its own clauses. The file is copied
into a temporary golden root: nothing is written under evals/golden."""

import shutil
from pathlib import Path

import yaml

from cw_evals.cases import load_extraction_set
from pipeline.label import check_case

EXAMPLE = (
    Path(__file__).resolve().parents[4] / "packages/contracts/golden/extraction-case.example.yaml"
)


def test_an_exported_case_loads_with_the_harness_loader_as_a_draft(tmp_path: Path) -> None:
    cases = tmp_path / "extraction" / "exported" / "cases"
    cases.mkdir(parents=True)
    shutil.copy(EXAMPLE, cases / EXAMPLE.name)
    extraction = load_extraction_set(tmp_path)
    (case,) = extraction.cases
    assert case.label_status == "draft"
    assert case.is_labelled
    assert extraction.by_status() == {"draft": 1}
    assert [clause.clause_ref for clause in case.document.clauses] == ["en.p1", "en.p2", "en.p3"]
    assert check_case(case) == [], "the validators accept the exported expected"
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert (raw["reviewed_by"], raw["labelled_by"]) == ("", "00000000-0000-0000-0000-000000000048")
