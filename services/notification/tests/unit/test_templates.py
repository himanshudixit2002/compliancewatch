import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from notification.domain.errors import MissingPlaceholderError, UnknownTemplateError
from notification.domain.templates import TEMPLATES, TemplateStatus, find_template, render

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
