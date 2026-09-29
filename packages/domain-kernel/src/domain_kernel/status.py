"""Status machines for rule versions and obligations."""

from collections.abc import Iterable, Mapping
from enum import StrEnum
from types import MappingProxyType

from domain_kernel.errors import (
    InvalidTransitionError,
    InvariantViolationError,
    UnknownClosureReasonError,
)


class RuleVersionStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class ObligationStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    WAIVED = "waived"
    CLOSED_NOT_APPLICABLE = "closed_not_applicable"


class ClosureReason(StrEnum):
    """Why an obligation was closed; decides the closing status."""

    PROFILE_CHANGED = "profile_changed"
    RULE_WITHDRAWN = "rule_withdrawn"
    RULE_SUPERSEDED = "rule_superseded"
    WAIVED_BY_USER = "waived_by_user"
    COMPLETED = "completed"


class TransitionTable[S: StrEnum]:
    """Allowed moves between the members of one status enum.

    Every member needs a row; a state with an empty row is terminal. A self-transition is
    only allowed when the row lists it.
    """

    __slots__ = ("_allowed", "_states")

    def __init__(self, states: type[S], allowed: Mapping[S, Iterable[S]]) -> None:
        members = frozenset(states)
        table: dict[S, frozenset[S]] = {}
        for state in states:
            if state not in allowed:
                raise InvariantViolationError(f"{states.__name__}: no row for {state.value}")
            targets = frozenset(allowed[state])
            unknown = targets - members
            if unknown:
                raise InvariantViolationError(
                    f"{states.__name__}: {state.value} lists unknown targets {sorted(unknown)}"
                )
            table[state] = targets
        extra = frozenset(allowed) - members
        if extra:
            raise InvariantViolationError(
                f"{states.__name__}: rows for unknown states {sorted(extra)}"
            )
        self._states = states
        self._allowed: Mapping[S, frozenset[S]] = MappingProxyType(table)

    def can(self, current: S, new: S) -> bool:
        return new in self._allowed[current]

    def assert_transition(self, current: S, new: S) -> None:
        """Raise InvalidTransitionError unless the move is allowed."""
        if not self.can(current, new):
            raise InvalidTransitionError(current.value, new.value)

    def successors(self, state: S) -> frozenset[S]:
        return self._allowed[state]

    def is_terminal(self, state: S) -> bool:
        return not self._allowed[state]

    @property
    def terminal_states(self) -> frozenset[S]:
        return frozenset(state for state in self._states if self.is_terminal(state))


RULE_VERSION_TRANSITIONS = TransitionTable(
    RuleVersionStatus,
    {
        RuleVersionStatus.DRAFT: {RuleVersionStatus.IN_REVIEW},
        RuleVersionStatus.IN_REVIEW: {RuleVersionStatus.APPROVED, RuleVersionStatus.DRAFT},
        RuleVersionStatus.APPROVED: {RuleVersionStatus.PUBLISHED, RuleVersionStatus.DRAFT},
        RuleVersionStatus.PUBLISHED: {RuleVersionStatus.SUPERSEDED, RuleVersionStatus.WITHDRAWN},
        RuleVersionStatus.SUPERSEDED: set(),
        RuleVersionStatus.WITHDRAWN: set(),
    },
)

OBLIGATION_TRANSITIONS = TransitionTable(
    ObligationStatus,
    {
        ObligationStatus.OPEN: {
            ObligationStatus.IN_PROGRESS,
            ObligationStatus.DONE,
            ObligationStatus.WAIVED,
            ObligationStatus.CLOSED_NOT_APPLICABLE,
        },
        ObligationStatus.IN_PROGRESS: {
            ObligationStatus.DONE,
            ObligationStatus.WAIVED,
            ObligationStatus.CLOSED_NOT_APPLICABLE,
        },
        ObligationStatus.DONE: set(),
        ObligationStatus.WAIVED: set(),
        ObligationStatus.CLOSED_NOT_APPLICABLE: set(),
    },
)


def parse_closure_reason(reason: ClosureReason | str) -> ClosureReason:
    """Accept a member or its value."""
    if isinstance(reason, ClosureReason):
        return reason
    try:
        return ClosureReason(reason)
    except ValueError as exc:
        raise UnknownClosureReasonError(reason) from exc


def closing_status(reason: ClosureReason) -> ObligationStatus:
    """The status an obligation ends in for a reason."""
    match reason:
        case ClosureReason.COMPLETED:
            return ObligationStatus.DONE
        case ClosureReason.WAIVED_BY_USER:
            return ObligationStatus.WAIVED
        case (
            ClosureReason.PROFILE_CHANGED
            | ClosureReason.RULE_WITHDRAWN
            | ClosureReason.RULE_SUPERSEDED
        ):  # pragma: no branch
            return ObligationStatus.CLOSED_NOT_APPLICABLE


def close_obligation(current: ObligationStatus, reason: ClosureReason | str) -> ObligationStatus:
    """The status after closing from ``current`` for ``reason``, or an error if not allowed."""
    target = closing_status(parse_closure_reason(reason))
    OBLIGATION_TRANSITIONS.assert_transition(current, target)
    return target
