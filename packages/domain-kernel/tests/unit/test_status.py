from enum import StrEnum

import pytest

from domain_kernel.errors import (
    InvalidTransitionError,
    InvariantViolationError,
    UnknownClosureReasonError,
)
from domain_kernel.status import (
    OBLIGATION_TRANSITIONS,
    RULE_VERSION_TRANSITIONS,
    ClosureReason,
    ObligationStatus,
    RuleVersionStatus,
    TransitionTable,
    close_obligation,
    closing_status,
    parse_closure_reason,
)

RV = RuleVersionStatus
OB = ObligationStatus


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (RV.DRAFT, RV.IN_REVIEW),
        (RV.IN_REVIEW, RV.APPROVED),
        (RV.IN_REVIEW, RV.DRAFT),
        (RV.APPROVED, RV.PUBLISHED),
        (RV.PUBLISHED, RV.SUPERSEDED),
        (RV.PUBLISHED, RV.WITHDRAWN),
    ],
)
def test_rule_version_allowed_transitions(current: RV, new: RV) -> None:
    assert RULE_VERSION_TRANSITIONS.can(current, new)
    RULE_VERSION_TRANSITIONS.assert_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (RV.DRAFT, RV.DRAFT),
        (RV.DRAFT, RV.APPROVED),
        (RV.DRAFT, RV.PUBLISHED),
        (RV.IN_REVIEW, RV.PUBLISHED),
        (RV.APPROVED, RV.DRAFT),
        (RV.APPROVED, RV.IN_REVIEW),
        (RV.PUBLISHED, RV.PUBLISHED),
        (RV.PUBLISHED, RV.DRAFT),
        (RV.SUPERSEDED, RV.PUBLISHED),
        (RV.WITHDRAWN, RV.DRAFT),
        (RV.WITHDRAWN, RV.WITHDRAWN),
    ],
)
def test_rule_version_forbidden_transitions(current: RV, new: RV) -> None:
    assert not RULE_VERSION_TRANSITIONS.can(current, new)
    with pytest.raises(InvalidTransitionError) as info:
        RULE_VERSION_TRANSITIONS.assert_transition(current, new)
    assert (info.value.current, info.value.new) == (current.value, new.value)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (OB.OPEN, OB.IN_PROGRESS),
        (OB.OPEN, OB.DONE),
        (OB.OPEN, OB.WAIVED),
        (OB.OPEN, OB.CLOSED_NOT_APPLICABLE),
        (OB.IN_PROGRESS, OB.DONE),
        (OB.IN_PROGRESS, OB.WAIVED),
        (OB.IN_PROGRESS, OB.CLOSED_NOT_APPLICABLE),
    ],
)
def test_obligation_allowed_transitions(current: OB, new: OB) -> None:
    assert OBLIGATION_TRANSITIONS.can(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (OB.OPEN, OB.OPEN),
        (OB.IN_PROGRESS, OB.OPEN),
        (OB.IN_PROGRESS, OB.IN_PROGRESS),
        (OB.DONE, OB.OPEN),
        (OB.DONE, OB.DONE),
        (OB.WAIVED, OB.IN_PROGRESS),
        (OB.CLOSED_NOT_APPLICABLE, OB.DONE),
    ],
)
def test_obligation_forbidden_transitions(current: OB, new: OB) -> None:
    assert not OBLIGATION_TRANSITIONS.can(current, new)
    with pytest.raises(InvalidTransitionError):
        OBLIGATION_TRANSITIONS.assert_transition(current, new)


def test_terminal_states_and_successors() -> None:
    assert RULE_VERSION_TRANSITIONS.terminal_states == {RV.SUPERSEDED, RV.WITHDRAWN}
    assert OBLIGATION_TRANSITIONS.terminal_states == {OB.DONE, OB.WAIVED, OB.CLOSED_NOT_APPLICABLE}
    assert RULE_VERSION_TRANSITIONS.is_terminal(RV.WITHDRAWN)
    assert not RULE_VERSION_TRANSITIONS.is_terminal(RV.PUBLISHED)
    assert RULE_VERSION_TRANSITIONS.successors(RV.IN_REVIEW) == {RV.APPROVED, RV.DRAFT}
    assert RULE_VERSION_TRANSITIONS.successors(RV.SUPERSEDED) == frozenset()
    assert OBLIGATION_TRANSITIONS.successors(OB.IN_PROGRESS) == {
        OB.DONE,
        OB.WAIVED,
        OB.CLOSED_NOT_APPLICABLE,
    }
    assert not hasattr(OBLIGATION_TRANSITIONS, "__dict__")


class _Light(StrEnum):
    RED = "red"
    GREEN = "green"


class _Other(StrEnum):
    BLUE = "blue"


def test_table_requires_a_row_for_every_member() -> None:
    with pytest.raises(InvariantViolationError, match="no row for green"):
        TransitionTable(_Light, {_Light.RED: {_Light.GREEN}})


def test_table_rejects_unknown_targets_and_rows() -> None:
    with pytest.raises(InvariantViolationError, match="unknown targets"):
        TransitionTable(_Light, {_Light.RED: {_Other.BLUE}, _Light.GREEN: set()})  # type: ignore[misc]
    with pytest.raises(InvariantViolationError, match="rows for unknown states"):
        TransitionTable(
            _Light,
            {_Light.RED: set(), _Light.GREEN: set(), _Other.BLUE: set()},
        )


def test_self_transitions_only_when_listed() -> None:
    table = TransitionTable(_Light, {_Light.RED: {_Light.RED, _Light.GREEN}, _Light.GREEN: set()})
    assert table.can(_Light.RED, _Light.RED)
    assert not table.can(_Light.GREEN, _Light.GREEN)
    assert table.terminal_states == {_Light.GREEN}


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        (ClosureReason.COMPLETED, OB.DONE),
        (ClosureReason.WAIVED_BY_USER, OB.WAIVED),
        (ClosureReason.PROFILE_CHANGED, OB.CLOSED_NOT_APPLICABLE),
        (ClosureReason.RULE_WITHDRAWN, OB.CLOSED_NOT_APPLICABLE),
        (ClosureReason.RULE_SUPERSEDED, OB.CLOSED_NOT_APPLICABLE),
    ],
)
def test_closing_status_for_every_reason(reason: ClosureReason, status: OB) -> None:
    assert closing_status(reason) is status
    assert OBLIGATION_TRANSITIONS.is_terminal(status)


def test_closing_status_table_is_complete() -> None:
    assert {
        closing_status(reason) for reason in ClosureReason
    } == OBLIGATION_TRANSITIONS.terminal_states


@pytest.mark.parametrize("current", [OB.OPEN, OB.IN_PROGRESS])
def test_close_obligation_from_an_open_state(current: OB) -> None:
    assert close_obligation(current, ClosureReason.COMPLETED) is OB.DONE
    assert close_obligation(current, "waived_by_user") is OB.WAIVED
    assert close_obligation(current, "rule_withdrawn") is OB.CLOSED_NOT_APPLICABLE


@pytest.mark.parametrize("current", [OB.DONE, OB.WAIVED, OB.CLOSED_NOT_APPLICABLE])
def test_close_obligation_refuses_terminal_states(current: OB) -> None:
    with pytest.raises(InvalidTransitionError):
        close_obligation(current, ClosureReason.PROFILE_CHANGED)


def test_parse_closure_reason_accepts_member_and_value() -> None:
    assert parse_closure_reason(ClosureReason.COMPLETED) is ClosureReason.COMPLETED
    assert parse_closure_reason("completed") is ClosureReason.COMPLETED
    with pytest.raises(UnknownClosureReasonError, match="nope") as info:
        parse_closure_reason("nope")
    assert info.value.reason == "nope"
    assert isinstance(info.value.__cause__, ValueError)
    with pytest.raises(UnknownClosureReasonError):
        close_obligation(OB.OPEN, "Completed")
