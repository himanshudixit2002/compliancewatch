from datetime import date, timedelta
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FinancialYear
from domain_kernel.periods import EffectivePeriod
from domain_kernel.recurrence import Frequency, Period, Recurrence, governs
from domain_kernel.rules import ObligationTemplate, one_off_due_on

_days = st.dates(min_value=date(2000, 1, 1), max_value=date(2099, 12, 31))
_recurrences = st.builds(
    Recurrence,
    st.sampled_from(list(Frequency)),
    st.integers(min_value=1, max_value=31),
    st.integers(min_value=0, max_value=24),
)


def test_monthly_period_and_due_date() -> None:
    monthly = Recurrence.monthly(20)
    period = monthly.period_containing(date(2026, 9, 15))
    assert period == Period(date(2026, 9, 1), date(2026, 10, 1), "2026-09")
    assert monthly.due_date(period) == date(2026, 10, 20)
    assert monthly.next_period(period).label == "2026-10"
    december = monthly.period_containing(date(2026, 12, 31))
    assert december.end == date(2027, 1, 1)
    assert monthly.due_date(december) == date(2027, 1, 20)


def test_quarterly_periods_follow_the_financial_year() -> None:
    quarterly = Recurrence.quarterly(22)
    assert quarterly.period_containing(date(2026, 4, 1)) == Period(
        date(2026, 4, 1), date(2026, 7, 1), "2026-27 Q1"
    )
    assert quarterly.period_containing(date(2026, 9, 28)).label == "2026-27 Q2"
    assert quarterly.period_containing(date(2026, 12, 31)).label == "2026-27 Q3"
    january = quarterly.period_containing(date(2027, 1, 1))
    assert january == Period(date(2027, 1, 1), date(2027, 4, 1), "2026-27 Q4")
    assert quarterly.due_date(january) == date(2027, 4, 22)
    assert quarterly.next_period(january).label == "2027-28 Q1"


def test_annual_period_is_the_financial_year() -> None:
    annual = Recurrence.annual(31, due_month_offset=8)
    period = annual.period_containing(date(2026, 9, 28))
    fy = FinancialYear(2026)
    assert period == Period(fy.start, fy.end, "2026-27")
    assert annual.due_date(period) == date(2027, 12, 31)


def test_due_day_is_clamped_to_the_month() -> None:
    assert Recurrence.monthly(31).due_date(
        Period(date(2026, 1, 1), date(2026, 2, 1), "2026-01")
    ) == date(2026, 2, 28)
    assert Recurrence.monthly(31).due_date(
        Period(date(2028, 1, 1), date(2028, 2, 1), "2028-01")
    ) == date(2028, 2, 29)
    assert Recurrence.monthly(30, due_month_offset=1).due_date(
        Period(date(2026, 3, 1), date(2026, 4, 1), "2026-03")
    ) == date(2026, 5, 30)


def test_periods_lists_consecutive_periods() -> None:
    labels = [p.label for p in Recurrence.monthly(20).periods(date(2026, 11, 3), 3)]
    assert labels == ["2026-11", "2026-12", "2027-01"]
    assert Recurrence.monthly(20).periods(date(2026, 11, 3), 0) == ()
    quarters = [p.label for p in Recurrence.quarterly(13).periods(date(2026, 12, 1), 3)]
    assert quarters == ["2026-27 Q3", "2026-27 Q4", "2027-28 Q1"]


def test_previous_period_ends_where_the_period_starts() -> None:
    monthly, quarterly = Recurrence.monthly(20), Recurrence.quarterly(22)
    assert monthly.previous_period(monthly.period_containing(date(2026, 1, 9))).label == "2025-12"
    april = quarterly.period_containing(date(2026, 4, 1))
    assert quarterly.previous_period(april) == Period(
        date(2026, 1, 1), date(2026, 4, 1), "2025-26 Q4"
    )


def labels_due(recurrence: Recurrence, as_of: date, count: int = 2) -> list[str]:
    return [period.label for period in recurrence.periods_due(as_of, count)]


def test_periods_due_keeps_the_return_still_due_from_the_period_before() -> None:
    monthly = Recurrence.monthly(20)
    assert labels_due(monthly, date(2026, 10, 5)) == ["2026-09", "2026-10", "2026-11"]
    assert labels_due(monthly, date(2026, 10, 20)) == ["2026-09", "2026-10", "2026-11"]
    assert labels_due(monthly, date(2026, 10, 21)) == ["2026-10", "2026-11"]
    assert labels_due(monthly, date(2026, 10, 25)) == ["2026-10", "2026-11"]
    assert monthly.due_date(monthly.periods_due(date(2026, 10, 5), 2)[0]) == date(2026, 10, 20)
    assert monthly.periods_due(date(2026, 10, 5), 0) == ()


def test_periods_due_of_quarterly_and_annual_returns() -> None:
    group_a = Recurrence.quarterly(22)
    assert labels_due(group_a, date(2026, 10, 5)) == ["2026-27 Q2", "2026-27 Q3", "2026-27 Q4"]
    assert labels_due(group_a, date(2026, 10, 25)) == ["2026-27 Q3", "2026-27 Q4"]
    assert labels_due(group_a, date(2026, 11, 5)) == ["2026-27 Q3", "2026-27 Q4"]
    assert labels_due(group_a, date(2027, 1, 22)) == ["2026-27 Q3", "2026-27 Q4", "2027-28 Q1"]
    annual = Recurrence.annual(31, due_month_offset=8)
    assert labels_due(annual, date(2026, 10, 5)) == ["2025-26", "2026-27", "2027-28"]
    assert labels_due(annual, date(2027, 1, 1)) == ["2026-27", "2027-28"]


def test_periods_due_reaches_back_as_far_as_the_offset_does() -> None:
    late = Recurrence.monthly(20, due_month_offset=2)
    assert labels_due(late, date(2026, 10, 5)) == [
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
        "2026-11",
    ]
    assert late.due_date(late.periods_due(date(2026, 10, 5), 2)[0]) == date(2026, 10, 20)
    with pytest.raises(InvariantViolationError, match="as_of"):
        late.periods_due("2026-10-05", 2)  # type: ignore[arg-type]


def test_a_version_governs_the_periods_whose_last_day_it_is_in_force_on() -> None:
    monthly = Recurrence.monthly(20)
    september = monthly.period_containing(date(2026, 9, 1))
    october = monthly.period_containing(date(2026, 10, 1))
    superseded = EffectivePeriod(date(2026, 4, 1), date(2026, 10, 1))
    newer = EffectivePeriod(date(2026, 10, 1))
    assert governs(superseded, september)
    assert not governs(superseded, october)
    assert governs(newer, october)
    assert not governs(newer, september), "September ended before the newer version"
    cut_mid_month = EffectivePeriod(date(2026, 4, 1), date(2026, 10, 15))
    assert not governs(cut_mid_month, october), "October's last day is the newer version's"
    with pytest.raises(InvariantViolationError, match="period"):
        governs(superseded, "2026-09")  # type: ignore[arg-type]


def test_a_superseded_version_still_owes_the_returns_due_after_it_ended() -> None:
    monthly = Recurrence.monthly(20)
    superseded = EffectivePeriod(date(2026, 4, 1), date(2026, 10, 1))
    owed = monthly.periods_governed(superseded, date(2026, 10, 5), 2)
    assert [period.label for period in owed] == ["2026-09"]
    assert monthly.due_date(owed[0]) == date(2026, 10, 20)
    assert monthly.periods_governed(superseded, date(2026, 10, 20), 2) == owed
    assert monthly.periods_governed(superseded, date(2026, 10, 25), 2) == ()
    newer = EffectivePeriod(date(2026, 10, 1))
    assert [p.label for p in monthly.periods_governed(newer, date(2026, 10, 5), 2)] == [
        "2026-10",
        "2026-11",
    ]

    annual = Recurrence.annual(31, due_month_offset=8)
    last_year = EffectivePeriod(date(2025, 4, 1), date(2026, 4, 1))
    (year,) = annual.periods_governed(last_year, date(2026, 10, 5), 1)
    assert (year.label, annual.due_date(year)) == ("2025-26", date(2026, 12, 31))
    assert annual.periods_governed(last_year, date(2027, 1, 1), 1) == ()


def test_a_one_off_is_due_its_days_after_the_decision() -> None:
    assert one_off_due_on(date(2026, 10, 5), 30) == date(2026, 11, 4)
    assert one_off_due_on(date(2026, 10, 5), 0) == date(2026, 10, 5)
    assert one_off_due_on(date(2026, 10, 5), None) is None
    assert ObligationTemplate("Display the certificate", due_in_days=45).due_on(
        date(2026, 10, 1)
    ) == date(2026, 11, 15)
    assert ObligationTemplate("Display the certificate").due_on(date(2026, 10, 1)) is None
    with pytest.raises(InvariantViolationError, match="due_in_days"):
        one_off_due_on(date(2026, 10, 5), -1)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"frequency": "monthly"}, "frequency"),
        ({"due_day": 0}, "due_day"),
        ({"due_day": 32}, "due_day"),
        ({"due_month_offset": -1}, "due_month_offset"),
        ({"due_month_offset": 25}, "due_month_offset"),
    ],
)
def test_recurrence_invariants(kwargs: dict[str, object], message: str) -> None:
    fields: dict[str, object] = {"frequency": Frequency.MONTHLY, "due_day": 20}
    fields.update(kwargs)
    with pytest.raises(InvariantViolationError, match=message):
        Recurrence(**fields)  # type: ignore[arg-type]


def test_period_invariants() -> None:
    with pytest.raises(InvariantViolationError, match="end must be after start"):
        Period(date(2026, 2, 1), date(2026, 2, 1), "x")
    with pytest.raises(InvariantViolationError, match="label"):
        Period(date(2026, 1, 1), date(2026, 2, 1), " ")
    with pytest.raises(InvariantViolationError, match="count"):
        Recurrence.monthly(1).periods(date(2026, 1, 1), -1)


@given(_recurrences, _days)
def test_period_contains_its_date_and_tiles_without_gaps(recurrence: Recurrence, day: date) -> None:
    period = recurrence.period_containing(day)
    assert period.contains(day)
    following = recurrence.next_period(period)
    assert following.start == period.end
    assert recurrence.period_containing(period.end - timedelta(days=1)) == period
    assert recurrence.period_containing(period.start) == period
    assert recurrence.due_date(period) >= period.end


@given(_recurrences, _days)
def test_previous_period_undoes_next_period(recurrence: Recurrence, day: date) -> None:
    period = recurrence.period_containing(day)
    assert recurrence.previous_period(recurrence.next_period(period)) == period
    assert recurrence.next_period(recurrence.previous_period(period)) == period
    assert recurrence.due_date(recurrence.previous_period(period)) < recurrence.due_date(period)


@given(_recurrences, _days, st.integers(min_value=1, max_value=4))
def test_periods_due_are_every_period_still_due_through_the_window(
    recurrence: Recurrence, as_of: date, count: int
) -> None:
    due = recurrence.periods_due(as_of, count)
    ahead = recurrence.periods(as_of, count)
    assert due[len(due) - count :] == ahead, "the window from the period containing as_of"
    assert all(recurrence.due_date(period) >= as_of for period in due)
    assert all(later.start == earlier.end for earlier, later in pairwise(due))
    assert recurrence.due_date(recurrence.previous_period(due[0])) < as_of, "nothing still due left"


@given(_recurrences, _days)
def test_due_date_moves_with_the_offset(recurrence: Recurrence, day: date) -> None:
    period = recurrence.period_containing(day)
    due = recurrence.due_date(period)
    months = (due.year - period.end.year) * 12 + (due.month - period.end.month)
    assert months == recurrence.due_month_offset
    assert due.day <= recurrence.due_day
    assert due.day == recurrence.due_day or due == last_day_of_month(due)


def last_day_of_month(day: date) -> date:
    following = day.replace(day=28) + timedelta(days=4)
    return following - timedelta(days=following.day)


@given(_recurrences, _days, st.integers(min_value=1, max_value=400), st.integers(1, 4))
def test_consecutive_versions_share_no_period_and_an_ended_one_owes_the_same_at_any_count(
    recurrence: Recurrence, as_of: date, days_ago: int, count: int
) -> None:
    replaced_on = as_of - timedelta(days=days_ago)
    older = EffectivePeriod(replaced_on - timedelta(days=800), replaced_on)
    newer = EffectivePeriod(replaced_on)
    for period in recurrence.periods_due(as_of, count):
        assert governs(older, period) is not governs(newer, period)
    owed = recurrence.periods_governed(older, as_of, count)
    assert owed == recurrence.periods_governed(older, as_of, 1)
    assert all(period.end <= replaced_on for period in owed)
    assert all(recurrence.due_date(period) >= as_of for period in owed)
