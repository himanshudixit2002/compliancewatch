"""The prompt registry as a TOML file of ``[[prompts]]`` tables, read once at startup.

Each table carries ``name``, ``version`` (text), ``owner`` and ``eval_cases``, optionally
``sha256`` and ``description``. Anything else, a missing key or a duplicate entry is refused so
that a bad registry stops the service before it serves a call.
"""

import tomllib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Self

from domain_kernel.errors import InvariantViolationError
from llm_gateway.domain.prompts import PromptSpec

REQUIRED_KEYS = ("name", "version", "owner", "eval_cases")
OPTIONAL_KEYS = ("sha256", "description")


def default_registry_path() -> Path:
    """``services/llm-gateway/prompts/registry.toml`` in a checkout (editable install).

    The wheel inside the image does not carry ``prompts/``; the Dockerfile copies the directory
    to ``/app/prompts`` and sets ``CW_LLM_PROMPT_REGISTRY_PATH`` instead.
    """
    return Path(__file__).resolve().parents[4] / "prompts" / "registry.toml"


class TomlPromptRegistry:
    """Lookups are dictionary hits; ``list`` keeps the file order."""

    def __init__(self, specs: Iterable[PromptSpec]) -> None:
        self._specs: dict[tuple[str, str], PromptSpec] = {}
        for spec in specs:
            if not isinstance(spec, PromptSpec):
                raise InvariantViolationError(
                    f"registry entries must be PromptSpec, got {spec.__class__.__name__}"
                )
            key = (spec.name, spec.version)
            if key in self._specs:
                raise InvariantViolationError(f"prompt {spec.ref} is registered twice")
            self._specs[key] = spec

    @classmethod
    def load(cls, path: Path | str) -> Self:
        """Read the file at ``path``. A missing file raises ``FileNotFoundError``."""
        file = Path(path)
        try:
            with file.open("rb") as handle:
                data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise InvariantViolationError(
                f"prompt registry {file} is not valid TOML: {exc}"
            ) from exc
        prompts = data.get("prompts", [])
        if not isinstance(prompts, list):
            raise InvariantViolationError(
                f"prompt registry {file}: 'prompts' must be an array of tables"
            )
        return cls(_spec(table, index, file) for index, table in enumerate(prompts))

    def get(self, name: str, version: str) -> PromptSpec | None:
        return self._specs.get((name, version))

    def list(self) -> Sequence[PromptSpec]:
        return tuple(self._specs.values())


def _spec(table: object, index: int, file: Path) -> PromptSpec:
    where = f"prompt registry {file}, prompts[{index}]"
    if not isinstance(table, Mapping):
        raise InvariantViolationError(f"{where} must be a table")
    missing = [key for key in REQUIRED_KEYS if key not in table]
    if missing:
        raise InvariantViolationError(f"{where} is missing {', '.join(missing)}")
    unknown = sorted(str(key) for key in table if key not in REQUIRED_KEYS + OPTIONAL_KEYS)
    if unknown:
        raise InvariantViolationError(f"{where} has unknown keys {', '.join(unknown)}")
    try:
        return PromptSpec(
            name=table["name"],
            version=table["version"],
            owner=table["owner"],
            eval_cases=table["eval_cases"],
            sha256=table.get("sha256"),
            description=table.get("description", ""),
        )
    except InvariantViolationError as exc:
        raise InvariantViolationError(f"{where}: {exc.detail}") from exc
