import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId
from notification.domain.ids import RecipientId
from notification.domain.occasions import Occasion, OccasionKind, dedupe_key, fallback_key

BUSINESS = BusinessId.new()
RECIPIENT = RecipientId.new()
OTHER_RECIPIENT = RecipientId.new()
OBLIGATION = ObligationId.new()
RULE_VERSION = RuleVersionId.new()
WA = Channel.WHATSAPP
DUE = datetime(2026, 10, 20, 18, 29, tzinfo=UTC)


def test_the_change_card_key_folds_the_guide_key_with_the_recipient() -> None:
    card = DedupeKey.for_notification(RULE_VERSION, BUSINESS, WA)
    expected = hashlib.sha256(f"{card.value}|{RECIPIENT}".encode()).hexdigest()
    occasion = Occasion.change_card(OBLIGATION, RULE_VERSION)
    assert dedupe_key(occasion, BUSINESS, RECIPIENT, WA).value == expected


def test_later_periods_of_a_recurring_rule_share_the_change_card_key() -> None:
    september = Occasion.change_card(ObligationId.new(), RULE_VERSION)
    october = Occasion.change_card(ObligationId.new(), RULE_VERSION)
    assert dedupe_key(september, BUSINESS, RECIPIENT, WA) == dedupe_key(
        october, BUSINESS, RECIPIENT, WA
    )


def test_each_recipient_and_channel_has_its_own_key() -> None:
    occasion = Occasion.change_card(OBLIGATION, RULE_VERSION)
    keys = {
        dedupe_key(occasion, BUSINESS, recipient, channel)
        for recipient in (RECIPIENT, OTHER_RECIPIENT)
        for channel in Channel
    }
    assert len(keys) == 4


def test_each_reminder_index_gives_a_distinct_key() -> None:
    keys = [
        dedupe_key(Occasion.reminder(OBLIGATION, index), BUSINESS, RECIPIENT, WA)
        for index in (1, 2, 3)
    ]
    assert len(set(keys)) == 3


def test_keys_are_stable() -> None:
    occasions = [
        Occasion.change_card(OBLIGATION, RULE_VERSION),
        Occasion.reminder(OBLIGATION, 1),
        Occasion.closure(OBLIGATION),
        Occasion.reschedule(OBLIGATION, DUE),
        Occasion.manual(OBLIGATION, "obligation_due_soon"),
    ]
    first = [dedupe_key(o, BUSINESS, RECIPIENT, WA) for o in occasions]
    again = [dedupe_key(o, BUSINESS, RECIPIENT, WA) for o in occasions]
    assert first == again
    assert len(set(first)) == len(occasions), "no two kinds share a key"


def test_a_reschedule_is_keyed_by_the_instant_whatever_its_offset() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    utc_key = dedupe_key(Occasion.reschedule(OBLIGATION, DUE), BUSINESS, RECIPIENT, WA)
    ist_key = dedupe_key(
        Occasion.reschedule(OBLIGATION, DUE.astimezone(ist)), BUSINESS, RECIPIENT, WA
    )
    later = dedupe_key(
        Occasion.reschedule(OBLIGATION, DUE + timedelta(days=5)), BUSINESS, RECIPIENT, WA
    )
    assert utc_key == ist_key
    assert later != utc_key


def test_the_manual_key_is_the_one_send_has_always_used() -> None:
    material = f"{OBLIGATION}|{BUSINESS}|{WA.value}|obligation_due_soon"
    expected = hashlib.sha256(material.encode()).hexdigest()
    manual = Occasion.manual(OBLIGATION, "obligation_due_soon")
    assert dedupe_key(manual, BUSINESS, None, WA).value == expected
    assert dedupe_key(manual, BUSINESS, RECIPIENT, WA).value != expected


@pytest.mark.parametrize(
    "occasion",
    [
        Occasion.change_card(OBLIGATION, RULE_VERSION),
        Occasion.reminder(OBLIGATION, 1),
        Occasion.closure(OBLIGATION),
        Occasion.reschedule(OBLIGATION, DUE),
    ],
)
def test_fan_out_occasions_need_a_recipient(occasion: Occasion) -> None:
    with pytest.raises(InvariantViolationError):
        dedupe_key(occasion, BUSINESS, None, WA)


@pytest.mark.parametrize(
    "build",
    [
        lambda: Occasion(OccasionKind.CHANGE_CARD, OBLIGATION),
        lambda: Occasion(OccasionKind.REMINDER, OBLIGATION),
        lambda: Occasion(OccasionKind.RESCHEDULE, OBLIGATION),
        lambda: Occasion(OccasionKind.MANUAL, OBLIGATION),
        lambda: Occasion.reminder(OBLIGATION, 0),
        lambda: Occasion.reschedule(OBLIGATION, datetime(2026, 10, 20)),
        lambda: Occasion.manual(OBLIGATION, " padded "),
        lambda: Occasion(OccasionKind.CLOSURE, OBLIGATION, rule_version_id="x"),  # type: ignore[arg-type]
    ],
)
def test_an_occasion_without_its_detail_is_refused(build: Callable[[], Occasion]) -> None:
    with pytest.raises(InvariantViolationError):
        build()


def test_a_fallback_has_a_key_of_its_own_per_channel() -> None:
    key = dedupe_key(Occasion.reminder(OBLIGATION, 1), BUSINESS, RECIPIENT, WA)
    email = fallback_key(key, Channel.EMAIL)
    assert email == fallback_key(key, Channel.EMAIL), "stable"
    assert len({key, email, fallback_key(key, WA)}) == 3
    assert email.value == hashlib.sha256(f"{key.value}|fallback|email".encode()).hexdigest()
