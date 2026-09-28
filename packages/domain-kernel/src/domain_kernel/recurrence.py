"""How often a duty recurs and when each period's instance is due.

A recurring rule (a monthly return, a quarterly statement, an annual reconciliation) is
materialised as one obligation per period. ``Recurrence`` turns a date into the period it
belongs to and a period into its due date, and lists the periods that follow. Periods are
aligned to the financial year: quarters are April to June, July to September, October to
December and January to March; an annual period is the financial year itself.

The due date is ``due_day`` of the month that is ``due_month_offset`` months after the month in
which the period ends (offset 0 is the month right after the period). ``due_day`` is clamped to
the length of that month, so 31 means the last day. The concrete values for a duty come from the
seed calendar and its cited notification, not from this module.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Self

from domain_kernel._validation import require_date, require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FIRST_MONTH, FinancialYear


class Frequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


@dataclass(frozen=True, slots=True, order=True)
class Period:
    """A half-open date range with the label the obligation carries (``2026-09``, ``2026-27 Q2``,
    ``2026-27``)."""

    start: date
    end: date
    label: str

    def __post_init__(self) -> None:
        require_date(self.start, "start")
        require_date(self.end, "end")
        if self.end <= self.start:
            raise InvariantViolationError(f"end must be after start, got {self.start}..{self.end}")
        require_text(self.label, "label")

    def contains(self, day: date) -> bool:
        require_date(day, "day")
        return self.start <= day < self.end


def _add_months(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


@dataclass(frozen=True, slots=True)
class Recurrence:
    frequency: Frequency
    due_day: int
    due_month_offset: int = 0

    def __post_init__(self) -> None:
        require_instance(self.frequency, Frequency, "frequency")
        require_int(self.due_day, "due_day", minimum=1)
        if self.due_day > 31:
            raise InvariantViolationError(f"due_day must be at most 31, got {self.due_day}")
        require_int(self.due_month_offset, "due_month_offset", minimum=0)
        if self.due_month_offset > 24:
            raise InvariantViolationError(
                f"due_month_offset must be at most 24 months, got {self.due_month_offset}"
            )

    @classmethod
    def monthly(cls, due_day: int, *, due_month_offset: int = 0) -> Self:
        return cls(Frequency.MONTHLY, due_day, due_month_offset)

    @classmethod
    def quarterly(cls, due_day: int, *, due_month_offset: int = 0) -> Self:
        return cls(Frequency.QUARTERLY, due_day, due_month_offset)

    @classmethod
    def annual(cls, due_day: int, *, due_month_offset: int = 0) -> Self:
        return cls(Frequency.ANNUAL, due_day, due_month_offset)

    def period_containing(self, day: date) -> Period:
        """The period ``day`` falls in."""
        require_date(day, "day")
        if self.frequency is Frequency.MONTHLY:
            end_year, end_month = _add_months(day.year, day.month, 1)
            return Period(
                _month_start(day.year, day.month),
                _month_start(end_year, end_month),
                f"{day.year:04d}-{day.month:02d}",
            )
        fy = FinancialYear.for_date(day)
        if self.frequency is Frequency.ANNUAL:
            return Period(fy.start, fy.end, fy.label)
        months_into_year = (day.month - FIRST_MONTH) % 12
        quarter = months_into_year // 3 + 1
        start_year, start_month = _add_months(fy.start_year, FIRST_MONTH, (quarter - 1) * 3)
        end_year, end_month = _add_months(start_year, start_month, 3)
        return Period(
            _month_start(start_year, start_month),
            _month_start(end_year, end_month),
            f"{fy.label} Q{quarter}",
        )

    def next_period(self, period: Period) -> Period:
        """The period that starts when ``period`` ends."""
        require_instance(period, Period, "period")
        return self.period_containing(period.end)

    def periods(self, from_day: date, count: int) -> tuple[Period, ...]:
        """``count`` consecutive periods starting with the one containing ``from_day``."""
        require_int(count, "count", minimum=0)
        result: list[Period] = []
        period = self.period_containing(from_day) if count else None
        while period is not None and len(result) < count:
            result.append(period)
            period = self.next_period(period)
        return tuple(result)

    def due_date(self, period: Period) -> date:
        """When the duty for ``period`` falls due."""
        require_instance(period, Period, "period")
        year, month = _add_months(period.end.year, period.end.month, self.due_month_offset)
        day = min(self.due_day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
