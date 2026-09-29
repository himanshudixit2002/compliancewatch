import string

import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from notification.domain.errors import MissingPlaceholderError, UnknownTemplateError
from notification.domain.templates import (
    CHANGE_TEMPLATES,
    PHRASES,
    SILENT_CHANGES,
    SUMMARY_LINES,
    TEMPLATES,
    TemplateStatus,
    find_template,
    one_line,
    ordered_params,
    phrase,
    render,
    summary_line,
    template_for_change,
)

KEY = DedupeKey("a" * 64)
PARAMS = {
    "business_name": "Acme",
    "title": "File GSTR-3B",
    "due_date": "20 Oct 2026",
    "steps": "Reconcile, pay, file",
}


def test_every_template_is_a_draft_with_a_language_pair_for_whatsapp() -> None:
    keys = {(t.key, t.channel) for t in TEMPLATES}
    for key, channel in keys:
        if channel is Channel.WHATSAPP:
            languages = {t.language for t in TEMPLATES if (t.key, t.channel) == (key, channel)}
            assert languages == {"en", "hi"}, key
    assert all(t.status is TemplateStatus.DRAFT for t in TEMPLATES)
    assert all(
        t.meta_name
        for t in TEMPLATES
        if t.channel is Channel.WHATSAPP and t.key.startswith("obligation_")
    )


def test_render_fills_placeholders_and_keeps_the_stop_line() -> None:
    message = render(
        "obligation_due_soon",
        Channel.WHATSAPP,
        "en",
        PARAMS,
        recipient="919876543210",
        dedupe_key=KEY,
    )
    assert message.body.startswith("Acme: File GSTR-3B is due on 20 Oct 2026.")
    assert message.body.endswith("STOP to opt out.")
    assert message.language == "en"
    assert message.dedupe_key == KEY


def test_hindi_and_fallback_to_english() -> None:
    hindi = render(
        "obligation_due_soon", Channel.WHATSAPP, "hi", PARAMS, recipient="9", dedupe_key=KEY
    )
    assert hindi.language == "hi"
    assert "STOP" in hindi.body
    fallback = render(
        "obligation_due_soon", Channel.EMAIL, "hi", PARAMS, recipient="a@b.c", dedupe_key=KEY
    )
    assert fallback.language == "en"
    assert fallback.subject == "File GSTR-3B is due on 20 Oct 2026"


def test_an_email_subject_is_one_line_whatever_its_values_hold() -> None:
    message = render(
        "obligation_due_soon",
        Channel.EMAIL,
        "en",
        {**PARAMS, "title": "File GSTR-3B\r\nfor Unit 2"},
        recipient="a@b.c",
        dedupe_key=KEY,
    )
    assert message.subject == "File GSTR-3B for Unit 2 is due on 20 Oct 2026"
    assert "File GSTR-3B\r\nfor Unit 2" in message.body, "the body keeps the value as given"


def test_missing_placeholder_and_unknown_template() -> None:
    with pytest.raises(MissingPlaceholderError, match="title"):
        render(
            "obligation_due_soon",
            Channel.WHATSAPP,
            "en",
            {"business_name": "x"},
            recipient="9",
            dedupe_key=KEY,
        )
    with pytest.raises(UnknownTemplateError):
        find_template("nope", Channel.WHATSAPP, "en")
    assert find_template("opt_in_confirmed", Channel.WHATSAPP, "hi").placeholders == ()


CHANGE_KEYS = ("obligation_deadline_extended", "obligation_corrected", "obligation_withdrawn")
CHANGE_PARAMS = {
    "business_name": "Acme",
    "title": "File GSTR-3B (2026-09)",
    "previous_due_date": "20 Oct 2026",
    "new_due_date": "25 Oct 2026",
    "source_ref": "Notification 99/2026",
}


@pytest.mark.parametrize("key", CHANGE_KEYS)
def test_each_deadline_change_has_whatsapp_in_two_languages_and_email_all_draft(key: str) -> None:
    found = {(t.channel, t.language): t for t in TEMPLATES if t.key == key}
    assert set(found) == {(Channel.WHATSAPP, "en"), (Channel.WHATSAPP, "hi"), (Channel.EMAIL, "en")}
    assert all(t.status is TemplateStatus.DRAFT for t in found.values())
    for language in ("en", "hi"):
        assert found[Channel.WHATSAPP, language].meta_name == f"cw_{key}_{language}"
    dated = key != "obligation_withdrawn"
    expected = {"business_name", "title", "source_ref"} | (
        {"previous_due_date", "new_due_date"} if dated else set()
    )
    for template in found.values():
        assert set(template.placeholders) == expected, (template.channel, template.language)
        assert not template.body.startswith("{"), "open with what changed, not a placeholder"


def test_every_subject_uses_only_placeholders_of_its_body() -> None:
    for template in TEMPLATES:
        subject = {name for _, name, _, _ in string.Formatter().parse(template.subject) if name}
        assert subject <= set(template.placeholders), template.key


def test_deadline_change_messages_render_both_dates_and_the_source() -> None:
    extended = render(
        "obligation_deadline_extended",
        Channel.WHATSAPP,
        "en",
        CHANGE_PARAMS,
        recipient="919876543210",
        dedupe_key=KEY,
    )
    assert "was due on 20 Oct 2026 and is now due on 25 Oct 2026" in extended.body
    assert "Source: Notification 99/2026." in extended.body
    assert extended.body.endswith("STOP to opt out.")
    corrected = render(
        "obligation_corrected",
        Channel.EMAIL,
        "en",
        CHANGE_PARAMS,
        recipient="a@b.c",
        dedupe_key=KEY,
    )
    assert corrected.subject == "Due date corrected: File GSTR-3B (2026-09) is due on 25 Oct 2026"
    withdrawn = render(
        "obligation_withdrawn", Channel.WHATSAPP, "hi", CHANGE_PARAMS, recipient="9", dedupe_key=KEY
    )
    assert withdrawn.language == "hi"
    assert "Notification 99/2026" in withdrawn.body
    assert "20 Oct 2026" not in withdrawn.body


def test_change_templates_map_topic_and_reason_to_a_key() -> None:
    assert dict(CHANGE_TEMPLATES) == {
        ("obligation.rescheduled", "deadline_extended"): "obligation_deadline_extended",
        ("obligation.rescheduled", "corrected"): "obligation_corrected",
        ("obligation.closed", "rule_withdrawn"): "obligation_withdrawn",
    }
    for (topic, reason), key in CHANGE_TEMPLATES.items():
        assert template_for_change(topic, reason) == key
        assert find_template(key, Channel.WHATSAPP, "hi").language == "hi"


def test_a_manual_reschedule_has_no_customer_message() -> None:
    assert ("obligation.rescheduled", "manual") not in CHANGE_TEMPLATES
    assert ("obligation.rescheduled", "manual") in SILENT_CHANGES
    assert template_for_change("obligation.rescheduled", "manual") is None


@pytest.mark.parametrize(
    ("topic", "reason"),
    [
        ("obligation.rescheduled", "postponed"),
        ("obligation.closed", "deadline_extended"),
        ("obligation.created", ""),
    ],
)
def test_an_unknown_change_raises(topic: str, reason: str) -> None:
    with pytest.raises(UnknownTemplateError, match=reason or "created"):
        template_for_change(topic, reason)


CONFIRMATIONS = {"opt_in_confirmed", "opt_out_confirmed"}
"""Replies inside a conversation the person started: free text, no Meta template."""

NEW_TEMPLATES = {
    "change_card": {"business_name", "summary", "applies_from", "steps", "due_date", "link"},
    "obligation_closed": {"business_name", "title", "closed_on", "reason"},
    "batch_summary": {"business_name", "count", "lines", "link"},
    "daily_digest": {"count", "lines", "link"},
    "ca_digest": {"org_label", "count", "client_count", "lines", "link"},
}


@pytest.mark.parametrize(("key", "placeholders"), sorted(NEW_TEMPLATES.items()))
def test_each_new_template_is_a_meta_ready_draft_in_two_languages_and_email(
    key: str, placeholders: set[str]
) -> None:
    found = {(t.channel, t.language): t for t in TEMPLATES if t.key == key}
    assert set(found) == {(Channel.WHATSAPP, "en"), (Channel.WHATSAPP, "hi"), (Channel.EMAIL, "en")}
    for template in found.values():
        assert template.status is TemplateStatus.DRAFT
        assert set(template.placeholders) == placeholders, (template.channel, template.language)
        assert not template.body.startswith("{"), "Meta refuses a body that opens with a value"
        assert not template.body.rstrip().endswith("}"), "Meta refuses a body that ends with one"
    for language in ("en", "hi"):
        assert found[Channel.WHATSAPP, language].meta_name == f"cw_{key}_{language}"
        assert "STOP" in found[Channel.WHATSAPP, language].body
    assert found[Channel.EMAIL, "en"].subject
    assert "\n" not in found[Channel.WHATSAPP, "en"].body


def test_every_business_initiated_whatsapp_template_carries_its_meta_name() -> None:
    for template in TEMPLATES:
        if template.channel is Channel.WHATSAPP and template.key not in CONFIRMATIONS:
            assert template.meta_name == f"cw_{template.key}_{template.language}", template.key


def test_ordered_params_follow_the_placeholder_order_on_one_line() -> None:
    template = find_template("change_card", Channel.WHATSAPP, "en")
    params = {
        "link": "https://app.example/o/1",
        "due_date": "20 Oct 2026",
        "steps": "Reconcile;\nfile",
        "applies_from": "1 Apr 2026",
        "summary": "Monthly return",
        "business_name": "Acme  Traders",
    }
    assert ordered_params(template, params) == (
        "Acme Traders",
        "Monthly return",
        "1 Apr 2026",
        "Reconcile; file",
        "20 Oct 2026",
        "https://app.example/o/1",
    )
    email = find_template("change_card", Channel.EMAIL, "en")
    assert ordered_params(email, params)[3] == "Reconcile;\nfile"
    with pytest.raises(MissingPlaceholderError, match="link"):
        ordered_params(template, {k: v for k, v in params.items() if k != "link"})
    assert one_line(" a\tb\n\n c      d ") == "a b c d"


def test_the_change_card_renders_what_changed_when_and_what_to_do() -> None:
    params = {
        "business_name": "Acme",
        "summary": "A monthly filer files FORM GSTR-3B",
        "applies_from": "1 Apr 2026",
        "steps": "Reconcile; pay; file",
        "due_date": "20 Oct 2026",
        "link": "https://app.example/obligations/1",
    }
    message = render("change_card", Channel.WHATSAPP, "en", params, recipient="9", dedupe_key=KEY)
    assert message.body.startswith("What changed for Acme: A monthly filer files FORM GSTR-3B.")
    assert "It applies to you from 1 Apr 2026. What to do: Reconcile; pay; file." in message.body
    assert "Open https://app.example/obligations/1 for details." in message.body
    email = render("change_card", Channel.EMAIL, "hi", params, recipient="a@b.c", dedupe_key=KEY)
    assert email.language == "en"
    assert email.subject == "What changed for Acme: applies from 1 Apr 2026"


def test_phrases_and_summary_lines_come_in_english_and_hindi() -> None:
    for table in (PHRASES, SUMMARY_LINES):
        names = {name for name, _ in table}
        for name in names:
            assert {language for n, language in table if n == name} == {"en", "hi"}, name
    assert phrase("no_due_date", "hi") == "कोई तय तिथि नहीं"
    assert phrase("firm", "ta") == "your firm"
    with pytest.raises(UnknownTemplateError):
        phrase("nothing", "en")
    extended = {"title": "GSTR-3B", "new_due_date": "25 Oct"}
    assert (
        summary_line("obligation_deadline_extended", "en", extended) == "Now due 25 Oct - GSTR-3B"
    )
    assert summary_line("obligation_corrected", "ta", extended) == (
        "Due date corrected to 25 Oct - GSTR-3B"
    )
    assert summary_line("obligation_withdrawn", "hi", extended) == "अब लागू नहीं - GSTR-3B"
