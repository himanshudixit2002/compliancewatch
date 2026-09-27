"""Prompt references and the registry every call must resolve against.

A prompt travels as ``name@version`` in ``CompletionRequest.prompt_version``. The registry
knows each prompt's owner, eval case count and text digest; an unregistered prompt is refused.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, Self

from domain_kernel._validation import require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError

PROMPT_NAME = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")
"""``area.purpose`` in snake case, such as ``extraction.rule_candidate``."""
PROMPT_VERSION = re.compile(r"[0-9]+(\.[0-9]+)*")
"""``1``, ``2``, ``2.1``: text, so ``1.10`` and ``1.1`` stay distinct."""
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class PromptRef:
    """A registered prompt at one version."""

    name: str
    version: str

    def __post_init__(self) -> None:
        if not PROMPT_NAME.fullmatch(require_instance(self.name, str, "name")):
            raise InvariantViolationError(
                f"prompt name must look like area.purpose in snake case, got {self.name!r}"
            )
        if not PROMPT_VERSION.fullmatch(require_instance(self.version, str, "version")):
            raise InvariantViolationError(
                f"prompt version must be dotted digits, got {self.version!r}"
            )

    @classmethod
    def parse(cls, text: str) -> Self:
        """Build the reference from ``name@version``."""
        require_instance(text, str, "prompt reference")
        name, separator, version = text.partition("@")
        if not separator:
            raise InvariantViolationError(
                f"prompt reference must look like name@version, got {text!r}"
            )
        return cls(name, version)

    def __str__(self) -> str:
        return f"{self.name}@{self.version}"


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """One registry entry: who owns the prompt, how many eval cases guard it, its digest."""

    name: str
    version: str
    owner: str
    eval_cases: int
    sha256: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        PromptRef(self.name, self.version)
        require_text(self.owner, "owner")
        require_int(self.eval_cases, "eval_cases", minimum=1)
        if self.sha256 is not None and not _SHA256.fullmatch(
            require_instance(self.sha256, str, "sha256")
        ):
            raise InvariantViolationError("sha256 must be 64 lowercase hex characters")
        require_instance(self.description, str, "description")

    @property
    def ref(self) -> PromptRef:
        return PromptRef(self.name, self.version)


class PromptRegistry(Protocol):
    """Lookup of registered prompts. Implemented over a TOML file in the infrastructure."""

    def get(self, name: str, version: str) -> PromptSpec | None: ...

    def list(self) -> Sequence[PromptSpec]: ...
