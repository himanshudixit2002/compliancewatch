"""Decided rule candidates exported as draft golden cases, on the memory store: an approved
candidate's case reads its approved version's content into the candidate shape with the stored
document's clauses, labelled by the decider and reviewed by nobody; a rejected one is only listed;
one whose conditions the shape cannot hold is skipped with why; the command writes the files and
refuses evals/golden. Synthetic text throughout."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

import ontology as ontology_package
from domain_kernel.ontology import Ontology
from rulebook.application.golden_export import ExportDecidedCandidates, slug
from rulebook.golden import case_yaml, inside_golden, run
from rulebook.testing import (
    APPROVED,
    CLAUSES,
    DIGEST,
    REJECTED,
    REVIEWER,
    START,
    UNFIT,
    ExampleDecisions,
)


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


@pytest.fixture
def decided(ontology: Ontology) -> ExampleDecisions:
    return ExampleDecisions(ontology)


def test_an_approved_candidate_is_a_draft_case_of_its_approved_content(
    decided: ExampleDecisions,
) -> None:
    export = ExportDecidedCandidates(decided.store).run(START)
    (case,) = export.cases
    content = case.content
    assert case.case_id == f"05-2000-example-{APPROVED.hex[-8:]}"
    assert (content["label_status"], content["labelled_by"], content["reviewed_by"]) == (
        "draft",
        str(REVIEWER),
        "",
    )
    assert content["source"]["sha256"] == DIGEST
    assert content["source"]["source_key"] == "cbic_notifications"
    assert [c["ref"] for c in content["document"]["clauses"]] == ["en.p1", "en.p2", "en.p3"]
    assert content["document"]["clauses"][1]["text"] == CLAUSES[1].text
    expected = content["expected"]
    assert expected["title"] == "Example: the monthly example statement", "the approved title"
    assert (expected["effective_from"], expected["effective_to"]) == ("2000-03-01", None)
    assert expected["applies_to"] == [
        {
            "attribute": "registration_type",
            "operator": "eq",
            "value": "regular",
            "clause_ref": "en.p2",
        }
    ]
    assert expected["recurrence"] == {
        "frequency": "monthly",
        "due_day": 11,
        "due_month_offset": 1,
        "clause_ref": "en.p2",
    }
    assert expected["obligation"]["title"] == "File the example statement"
    assert expected["obligation"]["clause_ref"] == "en.p2"
    assert [c["clause_ref"] for c in expected["citations"]] == ["en.p2", "en.p3"]
    assert expected["references"] == ["Example notification No. 01/2000"], "the model's"
    assert (expected["doc_kind"], expected["change_kind"], expected["confidence"]) == (
        "notification",
        "none",
        0.8,
    )
    provenance = content["export"]
    assert provenance["candidate_id"] == str(APPROVED)
    assert provenance["edited"] == ["title"]
    assert "nothing here is reviewed" in content["notes"]


def test_a_rejection_is_listed_and_an_unfit_candidate_skipped(decided: ExampleDecisions) -> None:
    export = ExportDecidedCandidates(decided.store).run(START)
    (rejection,) = export.rejections
    assert (rejection.candidate_id, rejection.reason, rejection.decided_by) == (
        REJECTED,
        "wrong_extraction",
        str(REVIEWER),
    )
    (skipped,) = export.skipped
    assert skipped.candidate_id == UNFIT
    assert "not an all_of of conditions" in skipped.why
    summary = export.summary()
    assert [entry["candidate_id"] for entry in summary["rejections"]] == [str(REJECTED)]
    assert summary["cases"][0]["file"] == f"cases/05-2000-example-{APPROVED.hex[-8:]}.yaml"
    assert summary["label_status"] == "draft"
    later = ExportDecidedCandidates(decided.store).run(decided.clock.now + timedelta(days=1))
    assert (later.cases, later.rejections, later.skipped) == ((), (), ())


def test_the_command_writes_the_drafts_and_refuses_the_golden_set(
    decided: ExampleDecisions, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "export"
    assert run(["--since", "2000-01-01", "--out", str(out)], units=decided.store) == 0
    case_file = out / "cases" / f"05-2000-example-{APPROVED.hex[-8:]}.yaml"
    written = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    assert (written["label_status"], written["reviewed_by"]) == ("draft", "")
    summary = yaml.safe_load((out / "summary.yaml").read_text(encoding="utf-8"))
    assert len(summary["rejections"]) == 1
    assert "1 draft case(s), 1 rejection(s) listed, 1 skipped" in capsys.readouterr().out
    golden = tmp_path / "repo" / "evals" / "golden" / "extraction"
    assert run(["--since", "2000-01-01", "--out", str(golden)], units=decided.store) == 2
    assert "inside evals/golden" in capsys.readouterr().err
    assert not golden.exists()
    assert run(["--since", "2000-01-01", "--out", str(out), "--json"], units=decided.store) == 0
    assert '"label_status": "draft"' in capsys.readouterr().out


def test_a_store_that_does_not_answer_is_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    class Away:
        def __call__(self) -> Any:
            raise ConnectionError("example database away")

    assert run(["--since", "2000-01-01", "--out", str(tmp_path)], units=Away()) == 1
    assert "cannot read the rulebook" in capsys.readouterr().err


def test_paths_and_slugs() -> None:
    assert inside_golden(Path("/x/evals/golden"))
    assert inside_golden(Path("/x/evals/golden/extraction/cases"))
    assert not inside_golden(Path("/x/evals/goldens"))
    assert not inside_golden(Path("/x/var/golden-export"))
    assert slug("01/2026-Central Tax") == "01-2026-central-tax"
    assert case_yaml({"b": 1, "a": "é"}).splitlines() == ["b: 1", "a: é"]
