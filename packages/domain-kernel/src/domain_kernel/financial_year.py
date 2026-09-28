"""India's financial year: 1 April to 31 March, named by its two calendar years (``2025-26``).

Turnover thresholds are stated for a financial year (usually the previous one), annual returns
are due once per financial year, and quarterly returns follow its quarters. ``FinancialYear``
is the value object every such rule and profile attribute refers to.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Self

from domain_kernel._validation import require_date, require_int
from domain_kernel.errors import InvariantViolationError

FY_LABEL_PATTERN = re.compile(r"(\d{4})-(\d{2})")
FIRST_MONTH = 4
"""April: the first month of the financial year."""


@dataclass(frozen=True, slots=True, order=True)
class FinancialYear:
    """The financial year that starts on 1 April of ``start_year``."""

    start_year: int

    def __post_init__(self) -> None:
        require_int(self.start_year, "start_year", minimum=1900)
        if self.start_year > 2200:
            raise InvariantViolationError(f"start_year must be at most 2200, got {self.start_year}")

    @classmethod
    def parse(cls, text: str) -> Self:
        """``2025-26`` -> the year starting 1 April 2025. The second part is the next year."""
        match = FY_LABEL_PATTERN.fullmatch(text.strip()) if isinstance(text, str) else None
        if match is None:
            raise InvariantViolationError(f"financial year must look like 2025-26, got {text!r}")
        start_year = int(match.group(1))
        if int(match.group(2)) != (start_year + 1) % 100:
            raise InvariantViolationError(
                f"financial year {text!r} does not name two consecutive years"
            )
        return cls(start_year)

    @classmethod
    def for_date(cls, day: date) -> Self:
        """The financial year that contains ``day``."""
        require_date(day, "day")
        return cls(day.year if day.month >= FIRST_MONTH else day.year - 1)

    @property
    def label(self) -> str:
        return f"{self.start_year}-{(self.start_year + 1) % 100:02d}"

    @property
    def start(self) -> date:
        """1 April, included."""
        return date(self.start_year, FIRST_MONTH, 1)

    @property
    def end(self) -> date:
        """1 April of the next year, excluded."""
        return date(self.start_year + 1, FIRST_MONTH, 1)

    def contains(self, day: date) -> bool:
        require_date(day, "day")
        return self.start <= day < self.end

    def previous(self) -> Self:
        return type(self)(self.start_year - 1)

    def next(self) -> Self:
        return type(self)(self.start_year + 1)

    def __str__(self) -> str:
        return self.label
