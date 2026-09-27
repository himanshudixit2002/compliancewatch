"""Date ranges during which a rule version is in force."""

from dataclasses import dataclass
from datetime import date

from domain_kernel._validation import require_date
from domain_kernel.errors import InvariantViolationError


@dataclass(frozen=True, slots=True)
class EffectivePeriod:
    """Half-open date range: ``start`` is included, ``end`` is not. ``end=None`` means open."""

    start: date
    end: date | None = None

    def __post_init__(self) -> None:
        require_date(self.start, "start")
        if self.end is not None:
            require_date(self.end, "end")
            if self.start >= self.end:
                raise InvariantViolationError(
                    f"end must be after start, got {self.start} to {self.end}"
                )

    @property
    def is_open(self) -> bool:
        return self.end is None

    def contains(self, as_of: date) -> bool:
        """True when ``as_of`` falls inside the period."""
        return self.start <= as_of and (self.end is None or as_of < self.end)

    def overlaps(self, other: "EffectivePeriod") -> bool:
        """True when the two periods share at least one day."""
        return self.start < (other.end or date.max) and other.start < (self.end or date.max)
