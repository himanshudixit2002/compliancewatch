"""Every alert links a runbook that exists: the check behind ``make runbooks-check``."""

import textwrap
from pathlib import Path

import pytest

from check_alert_runbooks import ALERTS, RUNBOOKS, problems

URL = "https://github.com/himanshudixit2002/compliancewatch/blob/main/docs/runbooks/"


@pytest.fixture
def runbooks(tmp_path: Path) -> Path:
    directory = tmp_path / "runbooks"
    directory.mkdir()
    (directory / "api-slo-burn.md").write_text("# API SLO burn\n", encoding="utf-8")
    return directory


def alerts(tmp_path: Path, rules: str) -> Path:
    path = tmp_path / "alerts.yml"
    body = textwrap.indent(textwrap.dedent(rules).strip(), " " * 6)
    path.write_text(f"groups:\n  - name: api-slo\n    rules:\n{body}\n", encoding="utf-8")
    return path


def test_the_repository_alerts_pass() -> None:
    assert problems(ALERTS, RUNBOOKS) == []


def test_a_rule_with_an_existing_runbook_passes(tmp_path: Path, runbooks: Path) -> None:
    path = alerts(
        tmp_path,
        f"""
        - alert: ApiErrorBurnRate
          expr: vector(1)
          annotations:
            runbook_url: {URL}api-slo-burn.md
        """,
    )
    assert problems(path, runbooks) == []


def test_a_rule_without_a_runbook_url_fails(tmp_path: Path, runbooks: Path) -> None:
    path = alerts(
        tmp_path,
        """
        - alert: ApiErrorBurnRate
          expr: vector(1)
          annotations:
            summary: no link
        """,
    )
    assert problems(path, runbooks) == ["api-slo/ApiErrorBurnRate: no runbook_url annotation"]


def test_a_rule_without_annotations_fails(tmp_path: Path, runbooks: Path) -> None:
    path = alerts(tmp_path, "- alert: ApiErrorBurnRate\n  expr: vector(1)")
    assert problems(path, runbooks) == ["api-slo/ApiErrorBurnRate: no runbook_url annotation"]


def test_a_dead_link_fails(tmp_path: Path, runbooks: Path) -> None:
    path = alerts(
        tmp_path,
        f"""
        - alert: ApiLatencyBurnRate
          expr: vector(1)
          annotations:
            runbook_url: {URL}missing.md
        """,
    )
    assert problems(path, runbooks) == [
        f"api-slo/ApiLatencyBurnRate: runbook {URL}missing.md does not exist"
    ]


def test_a_link_outside_the_runbooks_directory_fails(tmp_path: Path, runbooks: Path) -> None:
    path = alerts(
        tmp_path,
        """
        - alert: ApiLatencyBurnRate
          expr: vector(1)
          annotations:
            runbook_url: https://example.invalid/wiki/api
        """,
    )
    assert len(problems(path, runbooks)) == 1


@pytest.mark.parametrize("content", ["groups: []\n", "{}\n", "just text\n"])
def test_a_file_without_groups_fails(tmp_path: Path, runbooks: Path, content: str) -> None:
    path = tmp_path / "alerts.yml"
    path.write_text(content, encoding="utf-8")
    assert problems(path, runbooks) == [f"{path}: no alert groups"]
