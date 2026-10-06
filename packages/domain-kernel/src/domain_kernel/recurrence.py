"""How often a duty recurs and when each period's instance is due.

A recurring rule (a monthly return, a quarterly statement, an annual reconciliation) is
materialised as one obligation per period. ``Recurrence`` turns a date into the period it
belongs to and a period into its due date, and lists the periods that follow. Periods are
aligned to the financial year: quarters are April to June, July to September, October to
December and January to March; half-years are April to September and October to March; an
annual period is the financial year itself.

The due date is ``due_day`` of the month that is ``due_month_offset`` months after the month in
which the period ends (offset 0 is the month right after the period). ``due_day`` is clamped to
the length of that month, so 31 means the last day. The concrete values for a duty come from the
seed calendar and its cited notification, not from this module.

A period falls due after it ends, so on any day the duty due next may belong to a period that has
already ended: on 5 October, September's monthly return (due 20 October) is still ahead.
``periods_due`` lists the periods still due on a day: those earlier periods, then the one the day
falls in and the ones after it. Due dates rise from one period to the next, so the periods still
due on a day are every period from the first one due on or after it.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Self

from domain_kernel._validation import (
    require_date,
    require_instance,
    require_int,
    require_mapping,
    require_text,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FIRST_MONTH, FinancialYear


class Frequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    HALF_YEARLY = "half_yearly"
    ANNUAL = "annual"


_MONTHS_PER_PERIOD = {Frequency.QUARTERLY: 3, Frequency.HALF_YEARLY: 6}
_PERIOD_PREFIX = {Frequency.QUARTERLY: "Q", Frequency.HALF_YEARLY: "H"}


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
    def half_yearly(cls, due_day: int, *, due_month_offset: int = 0) -> Self:
        return cls(Frequency.HALF_YEARLY, due_day, due_month_offset)

    @classmethod
    def annual(cls, due_day: int, *, due_month_offset: int = 0) -> Self:
        return cls(Frequency.ANNUAL, due_day, due_month_offset)

    def to_mapping(self) -> dict[str, object]:
        """JSON-ready form, the inverse of ``from_mapping``."""
        return {
            "frequency": self.frequency.value,
            "due_day": self.due_day,
            "due_month_offset": self.due_month_offset,
        }

    @classmethod
    def from_mapping(cls, data: object) -> Self:
        mapping = require_mapping(data, "recurrence")
        unknown = set(mapping) - {"frequency", "due_day", "due_month_offset"}
        if unknown:
            raise InvariantViolationError(f"recurrence has unknown keys {sorted(unknown)}")
        try:
            frequency = Frequency(require_text(mapping.get("frequency"), "recurrence.frequency"))
        except ValueError as exc:
            raise InvariantViolationError(
                f"recurrence.frequency must be one of {[f.value for f in Frequency]}"
            ) from exc
        return cls(
            frequency,
            require_int(mapping.get("due_day"), "recurrence.due_day"),
            require_int(mapping.get("due_month_offset", 0), "recurrence.due_month_offset"),
        )

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
        length = _MONTHS_PER_PERIOD[self.frequency]
        months_into_year = (day.month - FIRST_MONTH) % 12
        index = months_into_year // length + 1
        start_year, start_month = _add_months(fy.start_year, FIRST_MONTH, (index - 1) * length)
        end_year, end_month = _add_months(start_year, start_month, length)
        return Period(
            _month_start(start_year, start_month),
            _month_start(end_year, end_month),
            f"{fy.label} {_PERIOD_PREFIX[self.frequency]}{index}",
        )

    def next_period(self, period: Period) -> Period:
        """The period that starts when ``period`` ends."""
        require_instance(period, Period, "period")
        return self.period_containing(period.end)

    def previous_period(self, period: Period) -> Period:
        """The period that ends when ``period`` starts."""
        require_instance(period, Period, "period")
        return self.period_containing(period.start - timedelta(days=1))

    def periods(self, from_day: date, count: int) -> tuple[Period, ...]:
        """``count`` consecutive periods starting with the one containing ``from_day``."""
        require_int(count, "count", minimum=0)
        result: list[Period] = []
        period = self.period_containing(from_day) if count else None
        while period is not None and len(result) < count:
            result.append(period)
            period = self.next_period(period)
        return tuple(result)

    def periods_due(self, as_of: date, count: int) -> tuple[Period, ...]:
        """The periods whose duty is still ahead on ``as_of``, up to the ``count`` periods that
        start with the one containing it.

        Every period of ``periods(as_of, count)`` is due after ``as_of``, since a period falls
        due after it ends; before them come the earlier periods due on or after ``as_of``, oldest
        first (on 5 October a monthly return due on the 20th adds September, due 20 October; on
        25 October it adds nothing). A period due before ``as_of`` is never listed. Empty when
        ``count`` is 0.
        """
        require_date(as_of, "as_of")
        ahead = self.periods(as_of, count)
        if not ahead:
            return ()
        earlier: list[Period] = []
        period = self.previous_period(ahead[0])
        while self.due_date(period) >= as_of:
            earlier.append(period)
            period = self.previous_period(period)
        return (*reversed(earlier), *ahead)

    def due_date(self, period: Period) -> date:
        """When the duty for ``period`` falls due."""
        require_instance(period, Period, "period")
        year, month = _add_months(period.end.year, period.end.month, self.due_month_offset)
        day = min(self.due_day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
