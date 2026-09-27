"""The compatibility script accepts additive changes and refuses breaking ones."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

CONTRACTS = Path(__file__).resolve().parents[4]
SCRIPT = CONTRACTS / "scripts" / "check_compat.py"
EVENTS = CONTRACTS / "events"


def run(base: Path, head: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--base-dir", str(base), "--head-dir", str(head)],
        capture_output=True,
        text=True,
        check=False,
    )


def edit_schema(root: Path, name: str, change: Any) -> None:
    path = root / "schemas" / name
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document))


@pytest.fixture
def head(tmp_path: Path) -> Path:
    copy = tmp_path / "head"
    shutil.copytree(EVENTS, copy)
    return copy


def test_identical_revisions_are_compatible(head: Path) -> None:
    result = run(EVENTS, head)
    assert result.returncode == 0, result.stderr
    assert "backward compatible" in result.stdout


def test_an_empty_base_is_compatible(tmp_path: Path, head: Path) -> None:
    result = run(tmp_path / "missing", head)
    assert result.returncode == 0, result.stderr


def test_adding_an_optional_field_with_a_minor_bump_is_compatible(head: Path) -> None:
    def add(document: dict[str, Any]) -> None:
        document["properties"]["note"] = {"type": "string", "description": "x"}
        document["x-version"] = "1.1.0"

    edit_schema(head, "obligation.closed.v1.json", add)
    result = run(EVENTS, head)
    assert result.returncode == 0, result.stderr


def test_a_change_without_a_version_bump_is_refused(head: Path) -> None:
    def add(document: dict[str, Any]) -> None:
        document["properties"]["note"] = {"type": "string", "description": "x"}

    edit_schema(head, "obligation.closed.v1.json", add)
    result = run(EVENTS, head)
    assert result.returncode == 1
    assert "x-version is still 1.0.0" in result.stderr


def test_a_new_required_field_is_refused(head: Path) -> None:
    def require(document: dict[str, Any]) -> None:
        document["required"].append("evidence_type")
        document["x-version"] = "1.1.0"

    edit_schema(head, "obligation.created.v1.json", require)
    result = run(EVENTS, head)
    assert result.returncode == 1
    assert "examples/obligation.created/no-deadline.json" in result.stderr
    assert "base example rejected by head schema" in result.stderr


def test_a_narrowed_enum_is_refused(head: Path) -> None:
    def narrow(document: dict[str, Any]) -> None:
        document["properties"]["channel"]["enum"] = ["whatsapp"]
        document["x-version"] = "1.0.1"

    edit_schema(head, "notification.failed.v1.json", narrow)
    result = run(EVENTS, head)
    assert result.returncode == 1
    assert "email-given-up.json" in result.stderr


def test_a_removed_schema_is_refused(head: Path) -> None:
    (head / "schemas" / "rule.superseded.v1.json").unlink()
    result = run(EVENTS, head)
    assert result.returncode == 1
    assert "rule.superseded.v1.json: removed" in result.stderr


def test_a_version_going_down_is_refused(head: Path) -> None:
    def downgrade(document: dict[str, Any]) -> None:
        document["x-version"] = "0.9.0"

    edit_schema(head, "rule.published.v1.json", downgrade)
    result = run(EVENTS, head)
    assert result.returncode == 1
    assert "went down" in result.stderr


def test_an_envelope_change_that_rejects_old_messages_is_refused(head: Path) -> None:
    def require_causation(document: dict[str, Any]) -> None:
        document["properties"]["causation_id"] = {"type": "string", "format": "uuid"}
        document["x-version"] = "1.1.0"

    edit_schema(head, "envelope.v1.json", require_causation)
    result = run(EVENTS, head)
    assert result.returncode == 1
    assert "base envelope example rejected by head" in result.stderr
