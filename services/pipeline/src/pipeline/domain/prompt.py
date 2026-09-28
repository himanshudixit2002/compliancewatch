"""A versioned prompt as the pipeline ships it."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptText:
    """The reference the gateway checks (``name@version``), the owner and the system text."""

    name: str
    version: str
    owner: str
    system: str

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"
