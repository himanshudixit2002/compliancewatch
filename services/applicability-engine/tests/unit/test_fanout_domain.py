"""A fan-out run's statuses and counters, the flip alarm, the hold and the reasons controls take."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from applicability_engine.domain.errors import FanOutStateError
from applicability_engine.domain.fanout import (
    FLIP_MINIMUM,
    TRANSITIONS,
    FanOutCounters,
    FanOutHold,
    FanOutRun,
    FanOutStart,
    FanOutStatus,
    fan_out_workflow_id,
    flip_alarm,
    published_trigger_ref,
    require_reason,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import EventId, RuleVersionId
from domain_kernel.ontology import AttributeLevel

NOW = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)


def start(**changes: object) -> FanOutStart:
    values: dict[str, object] = {
        "rule_version_id": RuleVersionId.new(),
        "rule_key": "example_rule",
        "level": AttributeLevel.REGISTRATION,
        "trigger_event_id": EventId.new(),
    }
    values.update(changes)
    return FanOutStart(**values)  # type: ignore[arg-type]


def test_a_run_begins_running_with_the_count_or_disabled_and_finished() -> None:
    begun = FanOutRun.begun(start(), at=NOW, businesses_total=12)
    assert (begun.status, begun.counters.businesses_total, begun.finished_at) == (
        FanOutStatus.RUNNING,
        12,
        None,
    )
    disabled = FanOutRun.begun(start(), at=NOW, businesses_total=12, disabled=True)
    assert (disabled.status, disabled.counters.businesses_total, disabled.finished_at) == (
        FanOutStatus.DISABLED,
        0,
        NOW,
    )
    assert "applicability.fanout" in disabled.status_reason


def test_moves_follow_the_transitions_and_finish_when_no_longer_active() -> None:
    run = FanOutRun.begun(start(), at=NOW)
    paused = run.move(FanOutStatus.PAUSED, at=LATER, reason="Checking the flips", by="u-1")
    assert (paused.status, paused.status_reason, paused.status_by, paused.updated_at) == (
        FanOutStatus.PAUSED,
        "Checking the flips",
        "u-1",
        LATER,
    )
    resumed = paused.move(FanOutStatus.RUNNING, at=LATER)
    assert (resumed.status_reason, resumed.finished_at) == ("", None)
    failed = resumed.move(FanOutStatus.FAILED, at=LATER, error="profile down")
    assert (failed.finished_at, failed.last_error) == (LATER, "profile down")
    with pytest.raises(FanOutStateError, match="failed; it cannot become running"):
        failed.move(FanOutStatus.RUNNING, at=LATER)
    for status, allowed in TRANSITIONS.items():
        assert status.is_active == bool(allowed)


def test_a_finished_run_needs_its_finish_and_an_active_one_has_none() -> None:
    run = FanOutRun.begun(start(), at=NOW)
    with pytest.raises(InvariantViolationError, match="has not finished"):
        replace(run, finished_at=NOW)
    with pytest.raises(InvariantViolationError, match="finished_at"):
        replace(run, status=FanOutStatus.COMPLETED)


def test_counters_add_batches_and_refuse_impossible_counts() -> None:
    counters = FanOutCounters(businesses_total=10).plus(
        evaluated=4, applies=2, flips_compared=3, flips=1
    )
    assert counters == FanOutCounters(10, 4, 2, 3, 1)
    assert counters.flip_rate == pytest.approx(1 / 3)
    assert FanOutCounters().flip_rate is None
    for bad in (
        {"evaluated": 1, "applies": 2},
        {"evaluated": 3, "flips_compared": 1, "flips": 2},
        {"evaluated": 1, "flips_compared": 2},
        {"evaluated": -1},
    ):
        with pytest.raises(InvariantViolationError):
            FanOutCounters(**bad)


def test_the_flip_alarm_needs_enough_comparisons_and_more_than_two_percent() -> None:
    def alarm(compared: int, flips: int) -> str | None:
        return flip_alarm(FanOutCounters(evaluated=compared, flips_compared=compared, flips=flips))

    assert alarm(FLIP_MINIMUM - 1, FLIP_MINIMUM - 1) is None, "too few compared"
    assert alarm(FLIP_MINIMUM, 4) is None, "exactly 2% does not pause"
    message = alarm(FLIP_MINIMUM, 5)
    assert message is not None
    assert "5 of 200" in message
    assert "2.5%" in message


def test_reasons_need_ten_characters_once_stripped() -> None:
    assert require_reason("  Checking the flips  ") == "Checking the flips"
    for bad in ("short", "         x", "x" * 2_001):
        with pytest.raises(InvariantViolationError):
            require_reason(bad)


def test_a_hold_says_why_and_who() -> None:
    hold = FanOutHold(reason="Deploy in progress", set_by="system:applicability-engine", set_at=NOW)
    assert hold.reason == "Deploy in progress"
    with pytest.raises(InvariantViolationError):
        FanOutHold(reason="too short", set_by="u-1", set_at=NOW)
    with pytest.raises(InvariantViolationError):
        FanOutHold(reason=" Deploy in progress", set_by="u-1", set_at=NOW)


def test_the_ids_of_a_fan_out_derive_from_the_version_and_the_event() -> None:
    version, event = RuleVersionId.new(), EventId.new()
    assert fan_out_workflow_id(version) == f"applicability-fan-out-{version}"
    assert published_trigger_ref(event) == f"rule.published:{event}"
    assert start(trigger_event_id=event).trigger_ref == f"rule.published:{event}"
    with pytest.raises(InvariantViolationError):
        start(rule_key="x" * 81)
    with pytest.raises(InvariantViolationError):
        start(supersedes=(str(version),))
