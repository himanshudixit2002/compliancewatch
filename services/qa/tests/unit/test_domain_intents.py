"""The two phrasings the structured layer answers, and what passes them by."""

from datetime import date

import pytest

from qa.domain.intents import DueForForm, DueInWindow, match_intent

AS_OF = date(2026, 3, 10)


@pytest.mark.parametrize(
    ("question", "form"),
    [
        ("When is my GSTR-3B due?", "GSTR-3B"),
        ("when is my gstr 3b due", "GSTR-3B"),
        ("When is our GSTR3B return due?", "GSTR-3B"),
        ("When is the next GSTR\u20131 due?", "GSTR-1"),
        ("  when is my form CMP-08 due ?  ", "CMP-08"),
    ],
)
def test_the_due_date_of_a_form(question: str, form: str) -> None:
    assert match_intent(question, AS_OF) == DueForForm(form)


@pytest.mark.parametrize(
    ("question", "window"),
    [
        ("What is due this month?", DueInWindow(date(2026, 3, 1), date(2026, 3, 31), "this month")),
        ("what's due next month", DueInWindow(date(2026, 4, 1), date(2026, 4, 30), "next month")),
        (
            "What\u2019s due for me this month?",
            DueInWindow(date(2026, 3, 1), date(2026, 3, 31), "this month"),
        ),
    ],
)
def test_what_is_due_in_a_month(question: str, window: DueInWindow) -> None:
    assert match_intent(question, AS_OF) == window


def test_next_month_crosses_the_year() -> None:
    assert match_intent("what is due next month", date(2026, 12, 31)) == DueInWindow(
        date(2027, 1, 1), date(2027, 1, 31), "next month"
    )


@pytest.mark.parametrize(
    "question",
    [
        "When is my tax due?",
        "When is my GSTR-3B due and what is the late fee?",
        "Which notification extended the GSTR-3B due date?",
        "What is due?",
        "what was due last month",
        "",
    ],
)
def test_anything_else_passes(question: str) -> None:
    assert match_intent(question, AS_OF) is None
