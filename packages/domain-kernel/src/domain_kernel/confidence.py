"""Confidence of a model output or a decision, from 0 to 1."""

from dataclasses import dataclass

from domain_kernel._validation import require_finite
from domain_kernel.errors import InvariantViolationError

REVIEW_THRESHOLD = 0.8
"""Below this an outcome goes to a human."""


@dataclass(frozen=True, slots=True, order=True)
class Confidence:
    """A number in [0, 1]. Ordered so results can be sorted and compared."""

    value: float

    def __post_init__(self) -> None:
        require_finite(self.value, "confidence")
        if not 0 <= self.value <= 1:
            raise InvariantViolationError(f"confidence must be within [0, 1], got {self.value}")

    def needs_review(self, threshold: float = REVIEW_THRESHOLD) -> bool:
        """True when the value is below the threshold."""
        return self.value < threshold


CERTAIN = Confidence(1.0)
ZERO = Confidence(0.0)
