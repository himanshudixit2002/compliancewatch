"""The TOML prompt registry: the shipped file loads; malformed files are refused with a location."""

from pathlib import Path

import pytest

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.prompts import PromptSpec
from llm_gateway.infrastructure.prompts.toml import TomlPromptRegistry, default_registry_path

VALID = """
[[prompts]]
name = "smoke.echo"
version = "1"
owner = "ai-platform"
eval_cases = 1
"""


def write(tmp_path: Path, text: str) -> Path:
    file = tmp_path / "registry.toml"
    file.write_text(text, encoding="utf-8")
    return file


def test_the_shipped_registry_loads() -> None:
    registry = TomlPromptRegistry.load(default_registry_path())
    smoke = registry.get("smoke.echo", "1")
    assert smoke == PromptSpec(
        name="smoke.echo",
        version="1",
        owner="ai-platform",
        eval_cases=1,
        description=(
            "Deterministic echo served by the fake provider; used by tests and the smoke route."
        ),
    )
    assert [str(spec.ref) for spec in registry.list()] == [
        "smoke.echo@1",
        "extraction.rule_candidate@1",
    ]
    assert registry.get("smoke.echo", "2") is None
    assert registry.get("nope.nope", "1") is None


def test_default_registry_path_is_at_the_service_root() -> None:
    path = default_registry_path()
    assert path.is_file()
    assert path.parts[-3:] == ("llm-gateway", "prompts", "registry.toml")


def test_load_accepts_a_string_path_and_optional_fields(tmp_path: Path) -> None:
    digest = "a" * 64
    file = write(
        tmp_path,
        f"""
[[prompts]]
name = "qa.answer"
version = "2.1"
owner = "qa-team"
eval_cases = 12
sha256 = "{digest}"
description = "Grounded answer."
""",
    )
    registry = TomlPromptRegistry.load(str(file))
    [spec] = registry.list()
    assert spec == PromptSpec("qa.answer", "2.1", "qa-team", 12, digest, "Grounded answer.")


def test_an_empty_registry_lists_nothing(tmp_path: Path) -> None:
    registry = TomlPromptRegistry.load(write(tmp_path, "# nothing registered yet\n"))
    assert registry.list() == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            '[[prompts]]\nname = "smoke.echo"\nversion = "1"\nowner = "x"\n',
            r"prompts\[0\] is missing eval_cases",
        ),
        (
            '[[prompts]]\nname = "smoke.echo"\n',
            r"prompts\[0\] is missing version, owner, eval_cases",
        ),
        (
            VALID + 'feature = "smoke"\n',
            r"prompts\[0\] has unknown keys feature",
        ),
        (
            '[[prompts]]\nname = "smoke.echo"\nversion = 1\nowner = "x"\neval_cases = 1\n',
            r"prompts\[0\]: version must be str",
        ),
        (
            '[[prompts]]\nname = "smoke.echo"\nversion = "1"\nowner = "x"\neval_cases = 0\n',
            r"prompts\[0\]: eval_cases must be at least 1",
        ),
        (
            '[[prompts]]\nname = "Smoke"\nversion = "1"\nowner = "x"\neval_cases = 1\n',
            r"prompts\[0\]: prompt name must look like",
        ),
        (VALID + VALID, "smoke.echo@1 is registered twice"),
        ("prompts = 1\n", "'prompts' must be an array of tables"),
        ("prompts = [1]\n", r"prompts\[0\] must be a table"),
        ("this is not toml\n", "is not valid TOML"),
    ],
)
def test_malformed_registries_are_refused(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        TomlPromptRegistry.load(write(tmp_path, text))


def test_a_missing_file_is_a_file_not_found_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        TomlPromptRegistry.load(tmp_path / "absent.toml")


def test_the_constructor_refuses_non_specs_and_duplicates() -> None:
    with pytest.raises(InvariantViolationError, match="must be PromptSpec"):
        TomlPromptRegistry(["smoke.echo@1"])  # type: ignore[list-item]
    spec = PromptSpec("smoke.echo", "1", "ai-platform", 1)
    with pytest.raises(InvariantViolationError, match="registered twice"):
        TomlPromptRegistry([spec, spec])
