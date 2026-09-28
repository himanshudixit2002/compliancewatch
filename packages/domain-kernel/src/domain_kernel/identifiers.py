"""Indian tax identifiers as value objects.

A PAN is ten characters: five letters, four digits, one letter. A GSTIN is fifteen: the
two-digit state code, the PAN of the entity, an entity code, the letter Z and a check
character. Both are kept in canonical upper case; ``parse`` accepts spaces and lower case. The
GSTIN check character is not verified here: the GSTIN lookup adapter confirms a number against
the registry, which is the only authority on whether it exists.
"""

import re
from dataclasses import dataclass
from typing import Self

from domain_kernel._validation import require_instance
from domain_kernel.errors import InvariantViolationError

PAN_PATTERN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
GSTIN_PATTERN = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")


@dataclass(frozen=True, slots=True)
class Pan:
    """Permanent Account Number: the identity of a legal entity across its registrations."""

    value: str

    def __post_init__(self) -> None:
        text = require_instance(self.value, str, "pan")
        if not PAN_PATTERN.fullmatch(text):
            raise InvariantViolationError(
                f"pan must be five letters, four digits and a letter in upper case, got {text!r}"
            )

    @classmethod
    def parse(cls, text: str) -> Self:
        return cls("".join(require_instance(text, str, "pan").split()).upper())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Gstin:
    """GST identification number of one registration; it embeds the state and the PAN."""

    value: str

    def __post_init__(self) -> None:
        text = require_instance(self.value, str, "gstin")
        if not GSTIN_PATTERN.fullmatch(text):
            raise InvariantViolationError(
                f"gstin must be fifteen characters: state code, PAN, entity code, Z and a check "
                f"character, in upper case, got {text!r}"
            )

    @classmethod
    def parse(cls, text: str) -> Self:
        return cls("".join(require_instance(text, str, "gstin").split()).upper())

    @property
    def state_code(self) -> str:
        return self.value[:2]

    @property
    def pan(self) -> Pan:
        return Pan(self.value[2:12])

    @property
    def entity_code(self) -> str:
        return self.value[12]

    def __str__(self) -> str:
        return self.value
