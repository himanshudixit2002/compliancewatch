from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from domain_kernel.errors import InvariantViolationError
from domain_kernel.financial_year import FY_LABEL_PATTERN, FinancialYear

_days = st.dates(min_value=date(1990, 1, 1), max_value=date(2100, 12, 31))


def test_label_start_end_and_contains() -> None:
    fy = FinancialYear(2025)
    assert fy.label == "2025-26" == str(fy)
    assert fy.start == date(2025, 4, 1)
    assert fy.end == date(2026, 4, 1)
    assert fy.contains(date(2025, 4, 1))
    assert fy.contains(date(2026, 3, 31))
    assert not fy.contains(date(2026, 4, 1))
    assert not fy.contains(date(2025, 3, 31))


def test_century_boundary_label() -> None:
    assert FinancialYear(2099).label == "2099-00"
    assert FinancialYear.parse("2099-00") == FinancialYear(2099)


@pytest.mark.parametrize(
    ("text", "start_year"), [("2025-26", 2025), (" 2017-18 ", 2017), ("1999-00", 1999)]
)
def test_parse(text: str, start_year: int) -> None:
    assert FinancialYear.parse(text) == FinancialYear(start_year)
    assert FY_LABEL_PATTERN.fullmatch(text.strip())


@pytest.mark.parametrize("text", ["2025", "2025-2026", "2025-27", "FY2025-26", "", "25-26"])
def test_parse_rejects_bad_labels(text: str) -> None:
    with pytest.raises(InvariantViolationError, match="financial year"):
        FinancialYear.parse(text)


def test_parse_rejects_non_text() -> None:
    with pytest.raises(InvariantViolationError, match="financial year"):
        FinancialYear.parse(2025)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("day", "start_year"),
    [
        (date(2026, 4, 1), 2026),
        (date(2026, 3, 31), 2025),
        (date(2026, 9, 28), 2026),
        (date(2027, 1, 15), 2026),
    ],
)
def test_for_date(day: date, start_year: int) -> None:
    assert FinancialYear.for_date(day) == FinancialYear(start_year)


def test_previous_next_and_order() -> None:
    fy = FinancialYear(2025)
    assert fy.previous() == FinancialYear(2024)
    assert fy.next() == FinancialYear(2026)
    assert fy.previous() < fy < fy.next()
    assert sorted([fy.next(), fy, fy.previous()]) == [fy.previous(), fy, fy.next()]


@pytest.mark.parametrize("year", [1899, 2201, "2025"])
def test_start_year_bounds(year: object) -> None:
    with pytest.raises(InvariantViolationError):
        FinancialYear(year)  # type: ignore[arg-type]


@given(_days)
def test_for_date_contains_the_date_and_only_that_year(day: date) -> None:
    fy = FinancialYear.for_date(day)
    assert fy.contains(day)
    assert not fy.previous().contains(day)
    assert not fy.next().contains(day)
    assert FinancialYear.parse(fy.label) == fy
