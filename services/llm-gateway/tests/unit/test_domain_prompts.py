from collections.abc import Sequence

import pytest

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.prompts import (
    PROMPT_NAME,
    PROMPT_VERSION,
    PromptRef,
    PromptRegistry,
    PromptSpec,
)

SHA = "a" * 64


def test_parse_and_str_round_trip() -> None:
    ref = PromptRef.parse("smoke.echo@1")
    assert (ref.name, ref.version) == ("smoke.echo", "1")
    assert str(ref) == "smoke.echo@1"
    assert PromptRef.parse("extraction.rule_candidate.v2@2.10") == PromptRef(
        "extraction.rule_candidate.v2", "2.10"
    )
    assert PromptRef.parse("a.b@0").version == "0"
    assert PromptRef("a.b", "1.10") != PromptRef("a.b", "1.1")


@pytest.mark.parametrize(
    "text",
    [
        "smoke.echo",
        "smoke@1",
        "Smoke.echo@1",
        "smoke.echo@v1",
        "smoke.echo@1.",
        "smoke.echo@",
        "@1",
        "smoke.echo@1@2",
        "smoke..echo@1",
        "1smoke.echo@1",
        "smoke.echo @1",
        "",
    ],
)
def test_malformed_references(text: str) -> None:
    with pytest.raises(InvariantViolationError):
        PromptRef.parse(text)


def test_reference_must_be_text() -> None:
    with pytest.raises(InvariantViolationError, match="prompt reference must be str"):
        PromptRef.parse(1)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="name must be str"):
        PromptRef(None, "1")  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="version must be str"):
        PromptRef("a.b", 1)  # type: ignore[arg-type]


def test_patterns_are_anchored_by_fullmatch_only() -> None:
    assert PROMPT_NAME.fullmatch("a.b_c.d9")
    assert not PROMPT_NAME.fullmatch("a")
    assert PROMPT_VERSION.fullmatch("10.0.1")
    assert not PROMPT_VERSION.fullmatch("1.")


def test_spec_defaults_and_ref() -> None:
    spec = PromptSpec("smoke.echo", "1", "ai-platform", 1)
    assert spec.sha256 is None
    assert spec.description == ""
    assert spec.ref == PromptRef("smoke.echo", "1")
    full = PromptSpec("smoke.echo", "1", "ai-platform", 3, SHA, "Echo.")
    assert (full.sha256, full.description) == (SHA, "Echo.")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "smoke"}, "prompt name must look like"),
        ({"version": "x"}, "prompt version must be dotted digits"),
        ({"owner": ""}, "owner must not be blank"),
        ({"eval_cases": 0}, "eval_cases must be at least 1"),
        ({"eval_cases": True}, "eval_cases must be an integer"),
        ({"sha256": "a" * 63}, "sha256 must be 64 lowercase hex"),
        ({"sha256": "A" * 64}, "sha256 must be 64 lowercase hex"),
        ({"sha256": 5}, "sha256 must be str"),
        ({"description": None}, "description must be str"),
    ],
)
def test_spec_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {
        "name": "smoke.echo",
        "version": "1",
        "owner": "ai-platform",
        "eval_cases": 1,
    }
    fields.update(kwargs)
    with pytest.raises(InvariantViolationError, match=message):
        PromptSpec(**fields)  # type: ignore[arg-type]


class _Registry:
    def __init__(self, specs: Sequence[PromptSpec]) -> None:
        self._specs = list(specs)

    def get(self, name: str, version: str) -> PromptSpec | None:
        return next((s for s in self._specs if (s.name, s.version) == (name, version)), None)

    def list(self) -> Sequence[PromptSpec]:
        return tuple(self._specs)


def test_registry_protocol_is_structural() -> None:
    registry: PromptRegistry = _Registry([PromptSpec("smoke.echo", "1", "ai-platform", 1)])
    assert registry.get("smoke.echo", "1") is not None
    assert registry.get("smoke.echo", "2") is None
    assert len(registry.list()) == 1
