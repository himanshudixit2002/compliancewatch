"""Tracking an obligation on the memory store: reading it whole, starting, completing and waiving
it, giving it to an assignee and commenting on it, each change with its change row and its audit
entry in the same unit of work, and nothing written when a change is refused."""

from datetime import date
from typing import Any
from uuid import UUID

import pytest

from domain_kernel.access import Role
from domain_kernel.audit import AuditActor
from domain_kernel.errors import InvalidTransitionError, InvariantViolationError
from domain_kernel.ids import CorrelationId, ObligationId, TenantId, UserId
from domain_kernel.rules import RuleVersionSnapshot
from domain_kernel.status import ClosureReason, ObligationStatus
from obligation.application.materialise import MaterialiseObligations, MaterialiseRequest
from obligation.application.tracking import (
    ASSIGN_ACTION,
    COMMENT_ACTION,
    COMPLETE_ACTION,
    START_ACTION,
    WAIVE_ACTION,
    Acting,
    AddComment,
    Assignment,
    AssignObligation,
    ChangeStatus,
    NewComment,
    ReadObligation,
    StatusAction,
    StatusChange,
    correlation_of,
)
from obligation.domain.errors import (
    AssigneeNotMemberError,
    IdentityUnavailableError,
    ObligationClosedError,
    ObligationNotFoundError,
    RulebookUnavailableError,
)
from obligation.domain.events import ObligationClosed
from obligation.domain.history import ChangeKind
from obligation.domain.model import Obligation
from obligation.infrastructure.memory import MemoryStore
from obligation.testing import (
    BUSINESS,
    DECISION,
    OTHER_TENANT,
    TENANT,
    FakeRuleVersionReader,
    FakeTenantMembers,
    clock,
    ref_of,
    rule,
)
from py_common.audit import MemoryAuditSink

OWNER = UserId(UUID(int=0x0E1))
STAFF = UserId(UUID(int=0x5AF))
OUTSIDER = UserId(UUID(int=0x0D7))
REQUEST_ID = "0123456789abcdef0123456789abcdef"
AS_OWNER = Acting(
    TENANT,
    AuditActor.user(OWNER, [Role.OWNER]),
    user_id=OWNER,
    verified=True,
    correlation_id=REQUEST_ID,
)
UNVERIFIED = Acting(TENANT, AuditActor.system("obligation"))
WAIVER = "Filed by the head office under the group registration (synthetic)"


class World:
    """Two open obligations of a monthly rule for one business, made from profile version 4, and
    the tracking use cases on the store."""

    def __init__(self, *, members: FakeTenantMembers | None = None, cached: bool = True) -> None:
        self.store = MemoryStore()
        self.rule: RuleVersionSnapshot = rule()
        self.reader = FakeRuleVersionReader([self.rule])
        self.members = members or FakeTenantMembers([(TENANT, OWNER), (TENANT, STAFF)])
        made = MaterialiseObligations(self.store, clock=clock).run(
            MaterialiseRequest(
                TENANT, BUSINESS, DECISION, self.rule, date(2026, 9, 28), profile_version=4
            )
        )
        self.first, self.second = made.created
        # Materialising wrote one obligation.created entry per obligation; the tests here count
        # what tracking writes after it.
        assert [e.action for e in self.store.audit] == ["obligation.created"] * 2
        self.store.audit.clear()
        if cached:
            self.store.rule_versions[self.rule.rule_version_id] = ref_of(self.rule)
        self.read = ReadObligation(self.store, self.reader)
        self.status = ChangeStatus(self.store, clock=clock)
        self.assign = AssignObligation(self.store, self.members, clock=clock)
        self.comment = AddComment(self.store, clock=clock)

    def obligation(self, obligation_id: ObligationId) -> Obligation:
        return self.store.obligations[obligation_id]

    def change(self, action: StatusAction, reason: str = "", **kwargs: Any) -> Obligation:
        acting = kwargs.get("acting", AS_OWNER)
        target = kwargs.get("obligation_id", self.first)
        return self.status.run(StatusChange(acting, target, action, reason))

    def kinds(self, obligation_id: ObligationId) -> list[ChangeKind]:
        return [c.kind for c in self.store.changes if c.obligation_id == obligation_id]

    def written(self) -> tuple[int, int, int, int]:
        """How many changes, events, comments and audit entries the store holds."""
        store = self.store
        return len(store.changes), len(store.events), len(store.comments), len(store.audit)


@pytest.fixture
def world() -> World:
    return World()


# ---------------------------------------------------------------- status


def test_start_then_complete_records_each_change_and_its_audit_entry(world: World) -> None:
    started = world.change(StatusAction.START)
    assert started.status is ObligationStatus.IN_PROGRESS
    assert world.obligation(world.first) == started
    created, start = [c for c in world.store.changes if c.obligation_id == world.first]
    assert (created.kind, start.kind) == (ChangeKind.CREATED, ChangeKind.STARTED)
    assert (start.status_after, start.actor, start.reason) == (
        ObligationStatus.IN_PROGRESS,
        OWNER,
        "",
    )
    assert start.correlation_id == CorrelationId(UUID(REQUEST_ID))

    done = world.change(StatusAction.COMPLETE, "Filed on the portal (synthetic)")
    assert (done.status, done.closed_by, done.closed_reason) == (
        ObligationStatus.DONE,
        OWNER,
        ClosureReason.COMPLETED,
    )
    closed = world.store.changes[-1]
    assert (closed.kind, closed.reason, closed.note) == (
        ChangeKind.CLOSED,
        "completed",
        "Filed on the portal (synthetic)",
    )
    (event,) = [e for e in world.store.events if isinstance(e, ObligationClosed)]
    assert (event.reason.value, event.closed_by, event.event_id) == ("completed", OWNER, closed.id)
    assert event.correlation_id == closed.correlation_id == start.correlation_id

    start_entry, complete_entry = world.store.audit
    assert (start_entry.action, complete_entry.action) == (START_ACTION, COMPLETE_ACTION)
    assert start_entry.actor == AuditActor.user(OWNER, [Role.OWNER])
    assert (start_entry.tenant_id, start_entry.subject_type, start_entry.subject_id) == (
        TENANT,
        "obligation",
        str(world.first),
    )
    assert dict(start_entry.before or {}) == {"status": "open"}
    assert dict(start_entry.after or {}) == {"status": "in_progress", "closed_reason": None}
    assert dict(complete_entry.after or {}) == {"status": "done", "closed_reason": "completed"}
    assert complete_entry.reason == "Filed on the portal (synthetic)"
    assert complete_entry.correlation_id == REQUEST_ID


def test_a_waiver_needs_a_reason_and_keeps_it(world: World) -> None:
    with pytest.raises(InvariantViolationError, match="at least 10"):
        world.change(StatusAction.WAIVE, "  too short ")
    assert world.written() == (2, 2, 0, 0)
    waived = world.change(StatusAction.WAIVE, f"  {WAIVER}  ")
    assert (waived.status, waived.closed_reason) == (
        ObligationStatus.WAIVED,
        ClosureReason.WAIVED_BY_USER,
    )
    change = world.store.changes[-1]
    assert (change.kind, change.reason, change.note) == (
        ChangeKind.CLOSED,
        "waived_by_user",
        WAIVER,
    )
    (entry,) = world.store.audit
    assert (entry.action, entry.reason) == (WAIVE_ACTION, WAIVER)


def test_a_closed_obligation_refuses_every_change_and_writes_nothing(world: World) -> None:
    world.change(StatusAction.COMPLETE)
    before = world.written()
    for action in StatusAction:
        with pytest.raises(ObligationClosedError):
            world.change(action, WAIVER)
    with pytest.raises(ObligationClosedError):
        world.assign.run(Assignment(AS_OWNER, world.first, STAFF))
    assert world.written() == before
    assert world.members.asked == []


def test_starting_twice_is_an_invalid_transition(world: World) -> None:
    world.change(StatusAction.START)
    before = world.written()
    with pytest.raises(InvalidTransitionError):
        world.change(StatusAction.START)
    assert world.written() == before
    assert world.change(StatusAction.WAIVE, WAIVER).status is ObligationStatus.WAIVED


def test_another_tenants_obligation_is_not_found(world: World) -> None:
    theirs = Acting(OTHER_TENANT, AuditActor.user(OWNER, [Role.OWNER]), user_id=OWNER)
    with pytest.raises(ObligationNotFoundError):
        world.read.run(OTHER_TENANT, world.first)
    with pytest.raises(ObligationNotFoundError):
        world.change(StatusAction.START, acting=theirs)
    with pytest.raises(ObligationNotFoundError):
        world.assign.run(Assignment(theirs, world.first, None))
    with pytest.raises(ObligationNotFoundError):
        world.comment.run(NewComment(theirs, world.first, "Example comment (synthetic)"))
    with pytest.raises(ObligationNotFoundError):
        world.change(StatusAction.START, obligation_id=ObligationId.new())
    assert world.written() == (2, 2, 0, 0)
    assert world.obligation(world.first).status is ObligationStatus.OPEN


def test_a_change_whose_audit_entry_fails_rolls_back_whole(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(sink: MemoryAuditSink, *args: object) -> None:
        raise RuntimeError("audit.event refused the row (synthetic)")

    monkeypatch.setattr(MemoryAuditSink, "write", refuse)
    with pytest.raises(RuntimeError, match="refused"):
        world.change(StatusAction.COMPLETE)
    with pytest.raises(RuntimeError, match="refused"):
        world.assign.run(Assignment(AS_OWNER, world.first, STAFF))
    with pytest.raises(RuntimeError, match="refused"):
        world.comment.run(NewComment(AS_OWNER, world.first, "Example comment (synthetic)"))
    assert world.written() == (2, 2, 0, 0)
    assert world.obligation(world.first).status is ObligationStatus.OPEN
    assert world.obligation(world.first).assignee_id is None


# ---------------------------------------------------------------- assignee


def test_a_verified_caller_assigns_a_member_and_unassigns(world: World) -> None:
    assigned = world.assign.run(Assignment(AS_OWNER, world.first, STAFF))
    assert assigned.assignee_id == STAFF
    assert world.members.asked == [(TENANT, STAFF)]
    again = world.assign.run(Assignment(AS_OWNER, world.first, STAFF))
    assert again == assigned
    assert world.members.asked == [(TENANT, STAFF)], "the assignee it has needs no check"
    unassigned = world.assign.run(Assignment(AS_OWNER, world.first, None))
    assert unassigned.assignee_id is None
    assert world.kinds(world.first) == [
        ChangeKind.CREATED,
        ChangeKind.ASSIGNED,
        ChangeKind.UNASSIGNED,
    ]
    give, take = world.store.changes[-2:]
    assert (give.previous_assignee_id, give.new_assignee_id, give.actor) == (None, STAFF, OWNER)
    assert (take.previous_assignee_id, take.new_assignee_id) == (STAFF, None)
    assert [(e.action, dict(e.before or {}), dict(e.after or {})) for e in world.store.audit] == [
        (ASSIGN_ACTION, {"assignee_id": None}, {"assignee_id": str(STAFF)}),
        (ASSIGN_ACTION, {"assignee_id": str(STAFF)}, {"assignee_id": None}),
    ]


@pytest.mark.parametrize(
    ("members", "error"),
    [
        (FakeTenantMembers([(TENANT, OWNER)]), AssigneeNotMemberError),
        (FakeTenantMembers([(OTHER_TENANT, STAFF)]), AssigneeNotMemberError),
        (FakeTenantMembers([(TENANT, STAFF)], disabled=[STAFF]), AssigneeNotMemberError),
        (FakeTenantMembers([(TENANT, STAFF)], down=True), IdentityUnavailableError),
    ],
    ids=["not-a-user", "of-another-tenant", "disabled", "identity-down"],
)
def test_a_verified_caller_cannot_assign_anyone_but_an_active_member(
    members: FakeTenantMembers, error: type[Exception]
) -> None:
    world = World(members=members)
    with pytest.raises(error):
        world.assign.run(Assignment(AS_OWNER, world.first, STAFF))
    assert world.obligation(world.first).assignee_id is None
    assert world.written() == (2, 2, 0, 0)


def test_an_unverified_caller_assigns_without_asking_identity(world: World) -> None:
    assigned = world.assign.run(Assignment(UNVERIFIED, world.first, OUTSIDER))
    assert assigned.assignee_id == OUTSIDER
    assert world.members.asked == []
    change = world.store.changes[-1]
    assert (change.kind, change.actor) == (ChangeKind.ASSIGNED, None)
    (entry,) = world.store.audit
    assert entry.actor == AuditActor.system("obligation")
    assert entry.correlation_id is None


# ---------------------------------------------------------------- comments


def test_comments_keep_their_author_and_the_audit_names_them_only(world: World) -> None:
    world.change(StatusAction.COMPLETE)
    first = world.comment.run(
        NewComment(AS_OWNER, world.first, "  Acknowledgement filed (synthetic)  ")
    )
    second = world.comment.run(NewComment(UNVERIFIED, world.first, "Example note (synthetic)"))
    assert (first.author_id, first.author_label, first.body) == (
        OWNER,
        "owner",
        "Acknowledgement filed (synthetic)",
    )
    assert (second.author_id, second.author_label) == (None, "system:obligation")
    assert world.store.comments == [first, second]
    comment_entries = [e for e in world.store.audit if e.action == COMMENT_ACTION]
    assert [dict(e.after or {}) for e in comment_entries] == [
        {"comment_id": str(first.id)},
        {"comment_id": str(second.id)},
    ]
    assert all(e.before is None and e.reason == "" for e in comment_entries)
    assert ChangeKind.CLOSED in world.kinds(world.first), "comments are not changes"
    assert len(world.kinds(world.first)) == 2


# ---------------------------------------------------------------- reading


def test_the_detail_has_the_cached_facts_the_history_and_the_comments(world: World) -> None:
    world.change(StatusAction.START)
    world.comment.run(NewComment(AS_OWNER, world.first, "Example comment (synthetic)"))
    detail = world.read.run(TENANT, world.first)
    assert detail.obligation.status is ObligationStatus.IN_PROGRESS
    assert detail.obligation.profile_version == 4
    assert detail.ref == ref_of(world.rule)
    assert [c.kind for c in detail.history] == [ChangeKind.CREATED, ChangeKind.STARTED]
    assert [c.body for c in detail.comments] == ["Example comment (synthetic)"]
    assert world.reader.reads == []


def test_a_missing_cache_row_is_filled_from_the_rulebook_once() -> None:
    world = World(cached=False)
    detail = world.read.run(TENANT, world.first)
    assert detail.ref is not None
    assert detail.ref.citations
    assert world.store.rule_versions[world.rule.rule_version_id] == detail.ref
    assert world.read.run(TENANT, world.second).ref == detail.ref
    assert world.reader.reads == [world.rule.rule_version_id]


def test_a_version_the_rulebook_lacks_leaves_the_facts_out() -> None:
    world = World(cached=False)
    world.reader.versions.clear()
    detail = world.read.run(TENANT, world.first)
    assert detail.ref is None
    assert world.store.rule_versions == {}
    world.reader.down = True
    with pytest.raises(RulebookUnavailableError):
        world.read.run(TENANT, world.first)


# ---------------------------------------------------------------- helpers


def test_the_request_id_becomes_the_changes_correlation_id() -> None:
    assert correlation_of(REQUEST_ID) == CorrelationId(UUID(REQUEST_ID))
    assert correlation_of("not-a-uuid") != correlation_of("not-a-uuid")
    assert isinstance(correlation_of(None), CorrelationId)


def test_obligations_keep_the_profile_version_of_their_decision(world: World) -> None:
    assert {o.profile_version for o in world.store.obligations.values()} == {4}
    tenant = TenantId.new()
    made = MaterialiseObligations(world.store, clock=clock).run(
        MaterialiseRequest(tenant, BUSINESS, DECISION, rule(), date(2026, 9, 28))
    )
    assert {world.obligation(o).profile_version for o in made.created} == {None}
