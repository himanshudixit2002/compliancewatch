from datetime import date

import pytest

from pipeline.domain.numbers import (
    date_forms,
    normalise,
    number_forms,
    ordinal,
    small_number_forms,
    text_has,
    words,
)


def test_normalise_flattens_pdf_artefacts() -> None:
    assert normalise("twenty -first  day of April, 2026") == "twenty-first day of april 2026"
    assert normalise("Rs. 2,00,00,000 \u2013 Central Tax") == "rs. 20000000-central tax"


def test_words_and_ordinals() -> None:
    assert words(21) == "twenty-one"
    assert words(7) == "seven"
    assert ordinal(21) == "twenty-first"
    assert ordinal(30) == "thirtieth"
    assert ordinal(12) == "twelfth"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (20000000, "aggregate turnover of Rs. 2 crore"),
        (20000000, "two crore rupees"),
        (20000000, "Rs. 2,00,00,000"),
        (15000000, "1.5 crore"),
        (4000000, "forty lakh rupees"),
        (50000, "Rs. 50,000"),
        (250, "two hundred and fifty rupees or 250"),
    ],
)
def test_number_forms_find_the_amount(value: int, text: str) -> None:
    assert text_has(text, number_forms(value))


def test_number_forms_do_not_match_a_different_amount() -> None:
    assert not text_has("Rs. 5 crore", number_forms(20000000))


@pytest.mark.parametrize(
    "text",
    [
        "till the twenty -first day of April, 2026",
        "on 21.04.2026",
        "21st April, 2026",
        "April 21, 2026",
        "2026-04-21",
        "21/04/2026",
    ],
)
def test_date_forms(text: str) -> None:
    assert text_has(text, date_forms(date(2026, 4, 21)))
    assert not text_has(text, date_forms(date(2026, 4, 22)))


def test_small_numbers_for_due_days() -> None:
    assert text_has("by the 20th of the following month", small_number_forms(20))
    assert text_has("within thirty days", small_number_forms(30))
    assert not text_has("by the 20th", small_number_forms(22))
