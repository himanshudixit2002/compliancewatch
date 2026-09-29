"""The topics script requires a schema, at the class's version, for every event topic in code."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

CONTRACTS = Path(__file__).resolve().parents[4]
SCRIPT = CONTRACTS / "scripts" / "check_topics.py"

KERNEL = """
from typing import ClassVar


class DomainEvent:
    topic: ClassVar[str] = ""
    schema_version: ClassVar[str] = "1.0.0"
"""

GATEWAY = """
from typing import ClassVar

from domain_kernel.events import DomainEvent


class LLMCallCompleted(DomainEvent):
    topic: ClassVar[str] = "llm.call.completed"


class BudgetAlarmed(DomainEvent):
    topic: ClassVar[str] = "llm.budget.alarmed"
"""


def write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source))


def event_module(topic: str, version: str | None = None) -> str:
    version_line = f'    schema_version: ClassVar[str] = "{version}"\n' if version else ""
    return (
        "from typing import ClassVar\n\nfrom domain_kernel.events import DomainEvent\n\n\n"
        f'class Happened(DomainEvent):\n    topic: ClassVar[str] = "{topic}"\n{version_line}'
    )


def write_schema(schemas: Path, topic: str, version: str) -> None:
    major = version.split(".")[0]
    schemas.mkdir(parents=True, exist_ok=True)
    (schemas / f"{topic}.v{major}.json").write_text(json.dumps({"x-version": version}))


def run(root: Path, schemas: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--schemas", str(schemas)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A repository with the kernel base class and the gateway's log-only events."""
    repo = tmp_path / "repo"
    write(repo, "packages/domain-kernel/src/domain_kernel/events.py", KERNEL)
    write(repo, "services/llm-gateway/src/llm_gateway/domain/events.py", GATEWAY)
    return repo


@pytest.fixture
def schemas(tmp_path: Path) -> Path:
    directory = tmp_path / "schemas"
    directory.mkdir()
    return directory


def test_the_repository_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "are log only" in result.stdout


def test_log_only_topics_need_no_schema(root: Path, schemas: Path) -> None:
    result = run(root, schemas)
    assert result.returncode == 0, result.stderr
    assert "0 in code have a schema, 2 are log only" in result.stdout


def test_an_event_class_with_its_schema_passes(root: Path, schemas: Path) -> None:
    write(root, "services/alpha/src/alpha/domain/events.py", event_module("thing.happened"))
    write_schema(schemas, "thing.happened", "1.0.0")
    result = run(root, schemas)
    assert result.returncode == 0, result.stderr


def test_an_event_class_without_a_schema_fails(root: Path, schemas: Path) -> None:
    write(root, "services/alpha/src/alpha/domain/events.py", event_module("thing.happened"))
    result = run(root, schemas)
    assert result.returncode == 1
    assert "Happened (services/alpha/src/alpha/domain/events.py:6)" in result.stderr
    assert "topic thing.happened has no schema thing.happened.v1.json" in result.stderr


def test_a_version_mismatch_fails(root: Path, schemas: Path) -> None:
    write(
        root,
        "services/alpha/src/alpha/domain/events.py",
        event_module("thing.happened", version="1.1.0"),
    )
    write_schema(schemas, "thing.happened", "1.0.0")
    result = run(root, schemas)
    assert result.returncode == 1
    assert "schema_version is 1.1.0 but thing.happened.v1.json has x-version 1.0.0" in (
        result.stderr
    )


def test_a_new_major_version_needs_its_own_file(root: Path, schemas: Path) -> None:
    write(
        root,
        "services/alpha/src/alpha/domain/events.py",
        event_module("thing.happened", version="2.0.0"),
    )
    write_schema(schemas, "thing.happened", "1.0.0")
    result = run(root, schemas)
    assert result.returncode == 1
    assert "has no schema thing.happened.v2.json" in result.stderr


def test_the_version_is_inherited_from_a_base_class(root: Path, schemas: Path) -> None:
    source = event_module("thing.happened", version="1.2.0") + textwrap.dedent(
        """

        class HappenedAgain(Happened):
            topic: ClassVar[str] = "thing.repeated"
        """
    )
    write(root, "services/alpha/src/alpha/domain/events.py", source)
    write_schema(schemas, "thing.happened", "1.2.0")
    write_schema(schemas, "thing.repeated", "1.0.0")
    result = run(root, schemas)
    assert result.returncode == 1
    assert "schema_version is 1.2.0 but thing.repeated.v1.json has x-version 1.0.0" in (
        result.stderr
    )


def test_a_log_only_topic_that_gains_a_schema_is_stale(root: Path, schemas: Path) -> None:
    write_schema(schemas, "llm.call.completed", "1.0.0")
    result = run(root, schemas)
    assert result.returncode == 1
    assert "LOG_ONLY_TOPICS: llm.call.completed has a schema now" in result.stderr


def test_a_log_only_topic_no_class_declares_is_stale(root: Path, schemas: Path) -> None:
    write(root, "services/llm-gateway/src/llm_gateway/domain/events.py", "")
    result = run(root, schemas)
    assert result.returncode == 1
    assert "no class declares llm.budget.alarmed any more" in result.stderr
    assert "no class declares llm.call.completed any more" in result.stderr
