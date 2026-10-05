"""What the people of a tenant do with an obligation (guide F11): read it whole, start, complete or
waive it, give it to an assignee, and comment on it.

- ``ReadObligation``: the obligation with the facts of its rule version (title, rule key, seed
  status, the approvers of the round it was published from and when), its verified citations,
  its history (the change log, oldest first) and its comments. The facts come from the
  ``rule_version_ref`` cache. An obligation made before the cache existed may find no row: the
  rulebook is then read with no unit of work open and the cache filled from the read, as the
  decision consumer fills it (``guard.admit``), and a version the rulebook does not have leaves
  the facts out.
- ``ChangeStatus``: ``start`` moves an open obligation to in progress (change ``started``, no
  event); ``complete`` closes it as ``completed`` and ``waive`` as ``waived_by_user`` with a
  reason of at least ``MIN_WAIVER_CHARS`` characters, each publishing ``obligation.closed`` with
  its change row (``audit.record``). The row is locked for the change, so two requests about one
  obligation run one after the other. A closed obligation is ``ObligationClosedError`` (409); a
  move the kernel's table refuses, such as starting one already in progress, is
  ``InvalidTransitionError`` (422).
- ``AssignObligation``: gives an open obligation to a user of the tenant, or to nobody (changes
  ``assigned`` and ``unassigned``). When the caller was verified, the identity service is asked
  whether the assignee is an active user of the tenant first, with no unit of work open; an
  unverified caller (``header`` mode, or ``dual`` without a token) cannot be held to a tenant's
  users, so the assignee is kept as the request names it. Naming the assignee it has already
  changes nothing.
- ``AddComment``: a comment by the caller on any obligation of the tenant, open or closed.

Every change writes an audit entry (``domain_kernel.audit``) in the unit of work that makes it,
as ``obligation.status.start``, ``.complete`` or ``.waive``, ``obligation.assign`` and
``obligation.comment``, with the actor of the request and its correlation id. A comment's entry
names the comment, never its text.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import CorrelationId, ObligationId, TenantId, UserId
from domain_kernel.status import ClosureReason
from obligation.application.audit import record
from obligation.domain.comments import CommentId, ObligationComment
from obligation.domain.errors import (
    AssigneeNotMemberError,
    ObligationClosedError,
    ObligationNotFoundError,
)
from obligation.domain.history import (
    MAX_NOTE_CHARS,
    ObligationChange,
    assignment_change,
    started_change,
)
from obligation.domain.model import Obligation
from obligation.domain.ports import RuleVersionReader, TenantMembers
from obligation.domain.repository import UnitOfWork, UnitOfWorkFactory
from obligation.domain.rule_versions import RuleVersionRef

MIN_WAIVER_CHARS: Final = 10
"""The shortest reason a waiver takes."""
SUBJECT: Final = "obligation"
START_ACTION: Final = "obligation.status.start"
COMPLETE_ACTION: Final = "obligation.status.complete"
WAIVE_ACTION: Final = "obligation.status.waive"
ASSIGN_ACTION: Final = "obligation.assign"
COMMENT_ACTION: Final = "obligation.comment"


class StatusAction(StrEnum):
    START = "start"
    COMPLETE = "complete"
    WAIVE = "waive"


STATUS_ACTIONS: Final = {
    StatusAction.START: START_ACTION,
    StatusAction.COMPLETE: COMPLETE_ACTION,
    StatusAction.WAIVE: WAIVE_ACTION,
}
"""The audit action of each status action."""


def correlation_of(text: str | None) -> CorrelationId:
    """The request's correlation id as the change log keeps it: the id itself when it is a UUID
    (``py_common.request_context`` mints 32 hex digits), else a new one."""
    if text is not None:
        try:
            return CorrelationId.parse(text)
        except InvariantViolationError:
            pass
    return CorrelationId.new()


def waiver_reason(reason: str) -> str:
    """A waiver's reason, trimmed: at least ``MIN_WAIVER_CHARS`` characters, at most
    ``MAX_NOTE_CHARS``."""
    text = reason.strip()
    if len(text) < MIN_WAIVER_CHARS:
        raise InvariantViolationError(
            f"a waiver needs a reason of at least {MIN_WAIVER_CHARS} characters"
        )
    if len(text) > MAX_NOTE_CHARS:
        raise InvariantViolationError(f"a reason has at most {MAX_NOTE_CHARS} characters")
    return text


@dataclass(frozen=True, slots=True)
class Acting:
    """Who changes an obligation of which tenant: the actor the audit log names, the user a
    verified token named (None for anyone else), whether a verified token named the caller at
    all, and the request's correlation id."""

    tenant_id: TenantId
    actor: AuditActor
    user_id: UserId | None = None
    verified: bool = False
    correlation_id: str | None = None


# ---------------------------------------------------------------- reading


@dataclass(frozen=True, slots=True)
class ObligationDetail:
    """An obligation with what its page shows: ``ref`` is None when the rulebook has no such
    version, and its citations are the verified ones."""

    obligation: Obligation
    ref: RuleVersionRef | None
    history: tuple[ObligationChange, ...]
    comments: tuple[ObligationComment, ...]


class ReadObligation:
    def __init__(self, unit_of_work: UnitOfWorkFactory, rules: RuleVersionReader) -> None:
        self._unit_of_work = unit_of_work
        self._rules = rules

    def run(self, tenant_id: TenantId, obligation_id: ObligationId) -> ObligationDetail:
        with self._unit_of_work(tenant_id) as uow:
            obligation = _found(uow, obligation_id)
            ref = uow.rule_versions.get(obligation.rule_version_id)
            history = tuple(uow.history.for_obligation(obligation_id))
            comments = tuple(uow.comments.for_obligation(obligation_id))
        if ref is None:
            ref = self._fill(tenant_id, obligation)
        return ObligationDetail(obligation, ref, history, comments)

    def _fill(self, tenant_id: TenantId, obligation: Obligation) -> RuleVersionRef | None:
        """Read the version with no unit of work open, then cache it."""
        read = self._rules.read(obligation.rule_version_id)
        if read is None:
            return None
        with self._unit_of_work(tenant_id) as uow:
            return uow.rule_versions.merge(read.ref)


# ---------------------------------------------------------------- status


@dataclass(frozen=True, slots=True)
class StatusChange:
    acting: Acting
    obligation_id: ObligationId
    action: StatusAction
    reason: str = ""
    """Why: required for a waiver, kept as the change's note and the audit entry's reason."""


class ChangeStatus:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, change: StatusChange) -> Obligation:
        acting = change.acting
        reason = change.reason.strip()
        if change.action is StatusAction.WAIVE:
            reason = waiver_reason(reason)
        elif len(reason) > MAX_NOTE_CHARS:
            raise InvariantViolationError(f"a reason has at most {MAX_NOTE_CHARS} characters")
        now = self._clock()
        correlation = correlation_of(acting.correlation_id)
        with self._unit_of_work(acting.tenant_id) as uow:
            before = _found(uow, change.obligation_id, lock=True)
            if change.action is StatusAction.START:
                after = before.start(now)
                uow.obligations.save(after)
                uow.history.append(
                    started_change(
                        after,
                        at=now,
                        actor=acting.user_id,
                        correlation_id=correlation,
                        note=reason,
                    )
                )
            else:
                closure = (
                    ClosureReason.COMPLETED
                    if change.action is StatusAction.COMPLETE
                    else ClosureReason.WAIVED_BY_USER
                )
                after, event = before.close(
                    closure, at=now, by=acting.user_id, correlation_id=correlation
                )
                uow.obligations.save(after)
                record(uow, event, after, note=reason)
            uow.audit.write(
                _entry(
                    STATUS_ACTIONS[change.action],
                    acting,
                    after,
                    before={"status": before.status.value},
                    after_state={
                        "status": after.status.value,
                        "closed_reason": None
                        if after.closed_reason is None
                        else after.closed_reason.value,
                    },
                    reason=reason,
                    at=now,
                )
            )
        return after


# ---------------------------------------------------------------- assignee


@dataclass(frozen=True, slots=True)
class Assignment:
    acting: Acting
    obligation_id: ObligationId
    assignee_id: UserId | None


class AssignObligation:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        members: TenantMembers,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._members = members
        self._clock = clock

    def run(self, assignment: Assignment) -> Obligation:
        acting, wanted = assignment.acting, assignment.assignee_id
        with self._unit_of_work(acting.tenant_id) as uow:
            current = _open(_found(uow, assignment.obligation_id))
        if current.assignee_id == wanted:
            return current
        if wanted is not None and acting.verified:
            self._require_member(acting.tenant_id, wanted)
        now = self._clock()
        with self._unit_of_work(acting.tenant_id) as uow:
            before = _open(_found(uow, assignment.obligation_id, lock=True))
            if before.assignee_id == wanted:
                return before
            after = before.assign(wanted, at=now)
            uow.obligations.save(after)
            uow.history.append(
                assignment_change(
                    before,
                    after,
                    at=now,
                    actor=acting.user_id,
                    correlation_id=correlation_of(acting.correlation_id),
                )
            )
            uow.audit.write(
                _entry(
                    ASSIGN_ACTION,
                    acting,
                    after,
                    before={"assignee_id": _text(before.assignee_id)},
                    after_state={"assignee_id": _text(after.assignee_id)},
                    at=now,
                )
            )
        return after

    def _require_member(self, tenant_id: TenantId, user_id: UserId) -> None:
        """Ask the identity service, with no unit of work open."""
        membership = self._members.membership(tenant_id, user_id)
        if membership is None or not membership.active or membership.tenant_id != tenant_id:
            raise AssigneeNotMemberError(str(user_id))


# ---------------------------------------------------------------- comments


@dataclass(frozen=True, slots=True)
class NewComment:
    acting: Acting
    obligation_id: ObligationId
    body: str


class AddComment:
    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, new: NewComment) -> ObligationComment:
        acting = new.acting
        now = self._clock()
        with self._unit_of_work(acting.tenant_id) as uow:
            obligation = _found(uow, new.obligation_id)
            comment = ObligationComment(
                id=CommentId.new(),
                tenant_id=acting.tenant_id,
                obligation_id=obligation.id,
                author_id=acting.user_id,
                author_label=acting.actor.label,
                body=new.body.strip(),
                created_at=now,
            )
            uow.comments.add(comment)
            uow.audit.write(
                _entry(
                    COMMENT_ACTION,
                    acting,
                    obligation,
                    before=None,
                    after_state={"comment_id": str(comment.id)},
                    at=now,
                )
            )
        return comment


# ---------------------------------------------------------------- shared


def _found(uow: UnitOfWork, obligation_id: ObligationId, *, lock: bool = False) -> Obligation:
    obligation = uow.obligations.get(obligation_id, lock=lock)
    if obligation is None:
        raise ObligationNotFoundError(str(obligation_id))
    return obligation


def _open(obligation: Obligation) -> Obligation:
    if not obligation.is_open:
        raise ObligationClosedError(str(obligation.id), obligation.status.value)
    return obligation


def _text(user_id: UserId | None) -> str | None:
    return None if user_id is None else str(user_id)


def _entry(
    action: str,
    acting: Acting,
    obligation: Obligation,
    *,
    before: dict[str, object] | None,
    after_state: dict[str, object] | None,
    at: datetime,
    reason: str = "",
) -> AuditEntry:
    return AuditEntry(
        action=action,
        tenant_id=acting.tenant_id,
        subject_type=SUBJECT,
        subject_id=str(obligation.id),
        actor=acting.actor,
        reason=reason,
        before=before,
        after=after_state,
        occurred_at=at,
        correlation_id=acting.correlation_id,
    )
