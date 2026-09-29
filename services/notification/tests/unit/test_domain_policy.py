from datetime import UTC, datetime, time, timedelta

import pytest

from domain_kernel.errors import InvariantViolationError
from notification.domain.policy import (
    DEFAULT_DIGEST_POLICY,
    DEFAULT_RETENTION_POLICY,
    DigestPolicy,
    RetentionPolicy,
)
from notification.domain.preferences import IST
from notification.testing import NIGHT_IST, NOON_IST

NINE_IST_TODAY = datetime(2026, 9, 28, 3, 30, tzinfo=UTC)
NINE_IST_TOMORROW = NINE_IST_TODAY + timedelta(days=1)


def test_the_digest_goes_out_at_the_next_nine_in_the_morning_ist() -> None:
    early = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)  # 05:30 IST
    assert DEFAULT_DIGEST_POLICY.next_at(early) == NINE_IST_TODAY
    assert DEFAULT_DIGEST_POLICY.next_at(NOON_IST) == NINE_IST_TOMORROW
    assert DEFAULT_DIGEST_POLICY.next_at(NIGHT_IST) == NINE_IST_TOMORROW
    assert DEFAULT_DIGEST_POLICY.next_at(NINE_IST_TODAY) == NINE_IST_TOMORROW, "strictly after"
    assert DEFAULT_DIGEST_POLICY.next_at(NINE_IST_TODAY - timedelta(seconds=1)) == NINE_IST_TODAY
    in_ist = DEFAULT_DIGEST_POLICY.next_at(NOON_IST.astimezone(IST))
    assert in_ist == NINE_IST_TOMORROW
    assert in_ist.tzinfo == IST, "in the time zone it was asked in"


def test_the_digest_time_is_a_setting() -> None:
    assert DigestPolicy.parse("18:30") == DigestPolicy(time(18, 30))
    assert DigestPolicy.parse("18:30").next_at(NOON_IST) == datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
    with pytest.raises(InvariantViolationError, match="HH:MM"):
        DigestPolicy.parse("half past six")
    with pytest.raises(InvariantViolationError, match="wall-clock"):
        DigestPolicy(time(9, 0, tzinfo=IST))
    with pytest.raises(InvariantViolationError):
        DEFAULT_DIGEST_POLICY.next_at(datetime(2026, 9, 28, 12, 0))


def test_retention_keeps_the_record_two_years_and_the_values_thirty_days() -> None:
    assert RetentionPolicy(keep_days=730, params_days=30) == DEFAULT_RETENTION_POLICY
    assert DEFAULT_RETENTION_POLICY.purge_before(NOON_IST) == NOON_IST - timedelta(days=730)
    assert DEFAULT_RETENTION_POLICY.strip_before(NOON_IST) == NOON_IST - timedelta(days=30)
    with pytest.raises(InvariantViolationError, match="params_days"):
        RetentionPolicy(keep_days=10, params_days=30)
    with pytest.raises(InvariantViolationError):
        RetentionPolicy(keep_days=0)
