from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import InvariantViolationError
from domain_kernel.periods import EffectivePeriod

_dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2040, 12, 31))


@st.composite
def _periods(draw: st.DrawFn) -> EffectivePeriod:
    start = draw(_dates)
    if draw(st.booleans()):
        return EffectivePeriod(start)
    end = draw(st.dates(min_value=start + timedelta(days=1), max_value=date(2041, 12, 31)))
    return EffectivePeriod(start, end)


def test_open_period_has_no_end() -> None:
    period = EffectivePeriod(date(2024, 4, 1))
    assert period.is_open
    assert period.end is None
    assert period.contains(date(2024, 4, 1))
    assert period.contains(date.max)
    assert not period.contains(date(2024, 3, 31))


def test_end_is_excluded_and_start_is_included() -> None:
    period = EffectivePeriod(date(2024, 4, 1), date(2024, 5, 1))
    assert not period.is_open
    assert period.contains(date(2024, 4, 1))
    assert period.contains(date(2024, 4, 30))
    assert not period.contains(date(2024, 5, 1))


@pytest.mark.parametrize("end", [date(2024, 4, 1), date(2024, 3, 31)])
def test_end_must_be_after_start(end: date) -> None:
    with pytest.raises(InvariantViolationError, match="end must be after start"):
        EffectivePeriod(date(2024, 4, 1), end)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2024, 4, 1, tzinfo=UTC), None),
        (date(2024, 4, 1), datetime(2024, 5, 1, tzinfo=UTC)),
        ("2024-04-01", None),
    ],
)
def test_datetimes_and_strings_are_rejected(start: object, end: object) -> None:
    with pytest.raises(InvariantViolationError, match="date"):
        EffectivePeriod(start, end)  # type: ignore[arg-type]


def test_overlap_examples() -> None:
    first = EffectivePeriod(date(2024, 1, 1), date(2024, 4, 1))
    adjacent = EffectivePeriod(date(2024, 4, 1), date(2024, 7, 1))
    inside = EffectivePeriod(date(2024, 2, 1), date(2024, 3, 1))
    open_later = EffectivePeriod(date(2024, 3, 15))
    assert not first.overlaps(adjacent)
    assert first.overlaps(inside)
    assert first.overlaps(open_later)
    assert not adjacent.overlaps(EffectivePeriod(date(2024, 7, 1)))
    assert EffectivePeriod(date(2024, 1, 1)).overlaps(EffectivePeriod(date(2030, 1, 1)))


@given(period=_periods(), as_of=_dates)
def test_contains_matches_the_definition(period: EffectivePeriod, as_of: date) -> None:
    expected = period.start <= as_of and (period.end is None or as_of < period.end)
    assert period.contains(as_of) == expected


@given(first=_periods(), second=_periods())
def test_overlap_is_symmetric_and_means_sharing_the_later_start(
    first: EffectivePeriod, second: EffectivePeriod
) -> None:
    assert first.overlaps(second) == second.overlaps(first)
    assert first.overlaps(first)
    later_start = max(first.start, second.start)
    assert first.overlaps(second) == (first.contains(later_start) and second.contains(later_start))
