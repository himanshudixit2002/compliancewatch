from datetime import UTC, datetime, time

import pytest

from domain_kernel.channels import Channel
from domain_kernel.errors import InvariantViolationError
from notification.application.preferences import GetPreference, SetOptIn
from notification.domain.errors import InvalidAddressError
from notification.domain.preferences import (
    DEFAULT_QUIET_HOURS,
    IST,
    ChannelPreference,
    ConsentSource,
    QuietHours,
)
from notification.infrastructure.memory import MemoryStore
from notification.testing import NIGHT_IST, NOON_IST


def test_default_quiet_hours_cross_midnight() -> None:
    assert DEFAULT_QUIET_HOURS.is_quiet(NIGHT_IST)
    assert not DEFAULT_QUIET_HOURS.is_quiet(NOON_IST)
    assert DEFAULT_QUIET_HOURS.is_quiet(datetime(2026, 9, 28, 2, 0, tzinfo=IST))
    assert not DEFAULT_QUIET_HOURS.is_quiet(datetime(2026, 9, 28, 8, 0, tzinfo=IST))
    assert DEFAULT_QUIET_HOURS.is_quiet(datetime(2026, 9, 28, 21, 0, tzinfo=IST))


def test_next_allowed_is_the_window_end_in_utc() -> None:
    held = DEFAULT_QUIET_HOURS.next_allowed(NIGHT_IST)
    assert held == datetime(2026, 9, 29, 2, 30, tzinfo=UTC)
    assert DEFAULT_QUIET_HOURS.next_allowed(NOON_IST) == NOON_IST
    early = datetime(2026, 9, 28, 3, 0, tzinfo=IST)
    assert DEFAULT_QUIET_HOURS.next_allowed(early) == datetime(2026, 9, 28, 8, 0, tzinfo=IST)


def test_a_daytime_window_and_an_empty_one() -> None:
    lunch = QuietHours.parse("13:00", "14:00")
    assert lunch.is_quiet(datetime(2026, 9, 28, 13, 30, tzinfo=IST))
    assert not lunch.is_quiet(datetime(2026, 9, 28, 14, 0, tzinfo=IST))
    assert not QuietHours(time(9), time(9)).is_quiet(NIGHT_IST)


@pytest.mark.parametrize(("start", "end"), [("24:00", "08:00"), ("21:00", "8am"), ("", "08:00")])
def test_quiet_hours_that_are_not_clock_times_are_refused(start: str, end: str) -> None:
    with pytest.raises(InvariantViolationError):
        QuietHours.parse(start, end)


def test_naive_times_are_refused() -> None:
    with pytest.raises(InvariantViolationError):
        DEFAULT_QUIET_HOURS.is_quiet(datetime(2026, 9, 28, 1, 0))


def test_set_opt_in_keeps_language_and_quiet_hours_across_toggles() -> None:
    store = MemoryStore()
    use_case = SetOptIn(store, clock=lambda: NOON_IST)
    first = use_case.run(
        Channel.WHATSAPP,
        "919876543210",
        opted_in=True,
        source=ConsentSource.WEB_ONBOARDING,
        language="hi",
        quiet_hours=QuietHours.parse("22:00", "07:00"),
    )
    assert first.language == "hi"
    assert first.address == "+919876543210"
    second = use_case.run(
        Channel.WHATSAPP, "+91 98765 43210", opted_in=False, source=ConsentSource.WHATSAPP_KEYWORD
    )
    assert not second.opted_in
    assert second.language == "hi"
    assert second.quiet_hours == QuietHours.parse("22:00", "07:00")
    read = GetPreference(store)
    assert read.run(Channel.WHATSAPP, "919876543210") == second
    assert read.run(Channel.EMAIL, "owner@example.com") is None


def test_an_email_preference_is_keyed_in_lower_case() -> None:
    store = MemoryStore()
    SetOptIn(store, clock=lambda: NOON_IST).run(
        Channel.EMAIL, " Owner@Example.COM ", opted_in=True, source=ConsentSource.WEB_ONBOARDING
    )
    found = GetPreference(store).run(Channel.EMAIL, "owner@example.com")
    assert found is not None
    assert found.address == "owner@example.com"


def test_an_address_that_cannot_be_normalised_is_refused() -> None:
    store = MemoryStore()
    with pytest.raises(InvalidAddressError):
        SetOptIn(store).run(Channel.WHATSAPP, "call me", opted_in=True, source=ConsentSource.API)
    with pytest.raises(InvalidAddressError):
        GetPreference(store).run(Channel.EMAIL, "not-an-address")


def test_preference_invariants() -> None:
    with pytest.raises(InvariantViolationError):
        ChannelPreference(Channel.WHATSAPP, "", True, ConsentSource.API, NOON_IST)
