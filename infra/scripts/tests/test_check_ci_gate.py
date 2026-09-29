"""The required check needs every CI job: the check behind ``make ci-gate-check``."""

from typing import Any

import pytest
import yaml

from check_ci_gate import WORKFLOW, main, problems

RESULTS_STEP = {
    "name": "Every job succeeded or was skipped",
    "env": {"RESULTS": "${{ toJSON(needs) }}"},
    "run": 'jq -e \'all(.[]; .result == "success" or .result == "skipped")\' <<< "$RESULTS"',
}


def workflow(**gate: Any) -> dict[str, Any]:
    job = {
        "name": "CI gate",
        "needs": ["changes", "python"],
        "if": "always()",
        "runs-on": "ubuntu-latest",
        "steps": [RESULTS_STEP],
    }
    job.update(gate)
    return {
        "jobs": {
            "changes": {"runs-on": "ubuntu-latest", "steps": []},
            "python": {"needs": "changes", "runs-on": "ubuntu-latest", "steps": []},
            "gate": job,
        }
    }


def test_the_repository_workflow_passes() -> None:
    assert problems(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))) == []


def test_main_reports_success_for_the_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    assert "needs every other job" in capsys.readouterr().out


def test_a_gate_that_needs_every_job_passes() -> None:
    assert problems(workflow()) == []


def test_a_job_missing_from_the_needs_fails() -> None:
    assert problems(workflow(needs=["changes"])) == [
        "job 'python' is not in gate.needs, so its failure would not block a merge"
    ]


def test_a_single_need_written_as_a_string_is_read() -> None:
    assert problems(workflow(needs="changes")) == [
        "job 'python' is not in gate.needs, so its failure would not block a merge"
    ]


def test_a_gate_without_always_fails() -> None:
    assert problems(workflow(**{"if": "success()"})) == [
        "job 'gate' does not run with if: always(), so a failed job would skip it and a "
        "skipped required check counts as passed"
    ]


def test_a_gate_under_another_name_fails() -> None:
    assert problems(workflow(name="Gate")) == [
        "job 'gate' is named 'Gate'; branch protection requires 'CI gate'"
    ]


def test_a_gate_that_never_reads_the_results_fails() -> None:
    assert problems(workflow(steps=[{"run": "echo ok"}])) == [
        "job 'gate' has no step that reads the results of its needs"
    ]


def test_a_workflow_without_a_gate_fails() -> None:
    jobs = workflow()["jobs"]
    del jobs["gate"]
    assert problems({"jobs": jobs}) == [
        "no job 'gate': branch protection requires the check 'CI gate'"
    ]


def test_a_workflow_without_jobs_fails() -> None:
    assert problems({"on": "push"}) == ["the workflow has no jobs"]
    assert problems(None) == ["the workflow has no jobs"]
