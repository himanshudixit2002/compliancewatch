from datetime import UTC, date, datetime

import pytest

from domain_kernel.errors import InvariantViolationError
from notification.domain.ports import RuleVersionFacts
from notification.domain.values import format_date, message_values

FACTS = RuleVersionFacts(
    title="File FORM GSTR-3B every month",
    summary="A monthly filer furnishes FORM GSTR-3B.",
    effective_from=date(2026, 4, 1),
    steps=("Reconcile", "File"),
    source_ref="CGST Rules, 2017, rule 61(1)",
)
EXTENSION = RuleVersionFacts(
    title="Extension", summary="", effective_from=date(2026, 10, 1), source_ref="N. 01/2026"
)
LINK = "https://app.example/obligations/1"


def test_dates_are_the_day_in_ist() -> None:
    assert format_date("2026-10-25T23:59:59+05:30", "en") == "25 Oct 2026"
    assert format_date("2026-10-25T20:00:00Z", "en") == "26 Oct 2026", "01:30 IST next day"
    assert format_date(datetime(2026, 10, 25, 12, 0, tzinfo=UTC), "hi") == "25 अक्टूबर 2026"
    assert format_date(datetime(2026, 1, 2, 3, 4), "ta") == "2 Jan 2026"
    assert format_date(date(2026, 4, 1), "en") == "1 Apr 2026"
    assert format_date("2026-04-01", "en") == "1 Apr 2026"
    for bad in ("tomorrow", 20261025, "2026-13-01"):
        with pytest.raises(InvariantViolationError):
            format_date(bad, "en")


def test_a_change_card_states_the_rule_facts_and_the_obligations() -> None:
    key, values = message_values(
        "change_card",
        "en",
        {"title": "File GSTR-3B", "steps": [], "due_at": "2026-10-20T23:59:59+05:30"},
        business_name="Acme Traders",
        link=LINK,
        rule=FACTS,
    )
    assert key == "change_card"
    assert {name: values[name] for name in ("business_name", "summary", "applies_from")} == {
        "business_name": "Acme Traders",
        "summary": "A monthly filer furnishes FORM GSTR-3B",
        "applies_from": "1 Apr 2026",
    }
    assert (values["steps"], values["due_date"], values["link"]) == (
        "Reconcile; File",
        "20 Oct 2026",
        LINK,
    )
    assert values["source_ref"] == "CGST Rules, 2017, rule 61(1)"


def test_what_is_missing_gets_a_phrase_and_a_change_card_without_facts_is_a_creation() -> None:
    key, values = message_values(
        "change_card", "hi", {"title": "Display", "due_at": None}, business_name="", link=LINK
    )
    assert key == "obligation_created"
    assert (values["business_name"], values["due_date"], values["steps"]) == (
        "आपका व्यवसाय",
        "कोई तय तिथि नहीं",
        "विवरण देखें",
    )
    assert values["source_ref"] == "ComplianceWatch नियम-पुस्तिका"


def test_a_change_cites_the_version_that_made_it_and_keeps_given_values() -> None:
    _, values = message_values(
        "obligation_deadline_extended",
        "en",
        {
            "previous_due_at": "2026-10-20T23:59:59+05:30",
            "new_due_at": "2026-10-25T23:59:59+05:30",
            "steps": "Pay; file",
            "business_name": "Given",
        },
        business_name="Acme Traders",
        link=LINK,
        rule=FACTS,
        source=EXTENSION,
    )
    assert (values["previous_due_date"], values["new_due_date"]) == ("20 Oct 2026", "25 Oct 2026")
    assert (values["source_ref"], values["title"], values["steps"]) == (
        "N. 01/2026",
        "File FORM GSTR-3B every month",
        "Pay; file",
    )
    assert values["business_name"] == "Given"
    _, empty = message_values(
        "obligation_withdrawn", "en", {}, business_name="", link=LINK, rule=EXTENSION
    )
    assert (empty["summary"], empty["source_ref"]) == ("Extension", "N. 01/2026")


def test_a_closure_says_why_in_words() -> None:
    _, values = message_values(
        "obligation_closed",
        "en",
        {"closed_at": "2026-10-02T09:12:50+05:30", "close_reason": "rule_superseded"},
        business_name="Acme",
        link=LINK,
    )
    assert (values["closed_on"], values["reason"]) == (
        "2 Oct 2026",
        "a newer version of the rule replaced it",
    )
    _, other = message_values(
        "obligation_closed", "en", {"close_reason": "odd"}, business_name="", link=LINK
    )
    assert other["reason"] == "odd"
