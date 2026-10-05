"""Builders for tests of this service and of services that consume its events: fixed ids, a
fixed clock, a sample recurring rule version, the facts the cache keeps of it, a rulebook reader
from a dict, the identity service's members from a set, and the profile service's nodes from a
set."""

from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from domain_kernel.ids import BusinessId, DecisionId, RuleId, RuleVersionId, TenantId, UserId
from domain_kernel.operators import Operator
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Predicate
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate, RuleVersionSnapshot
from domain_kernel.status import RuleVersionStatus
from obligation.domain.errors import (
    IdentityUnavailableError,
    ProfileUnavailableError,
    RulebookUnavailableError,
)
from obligation.domain.ports import Membership
from obligation.domain.rule_versions import Citation, RuleVersionRead, RuleVersionRef

TENANT = TenantId.new()
OTHER_TENANT = TenantId.new()
BUSINESS = BusinessId.new()
DECISION = DecisionId.new()
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
ANALYST = UserId(UUID(int=0xA11))
"""A synthetic approver."""
CITATION = Citation(
    citation_id=UUID(int=0xC17),
    clause_id=UUID(int=0xC1A),
    document_id=UUID(int=0xD0C),
    clause_ref="en.p1",
    quote="Example clause text (synthetic)",
    match_score=1.0,
    verified_at=NOW,
)
"""A synthetic verified citation."""


def clock() -> datetime:
    return NOW


MONTHLY_ON_THE_20TH = Recurrence.monthly(20)


def rule(
    *,
    recurrence: Recurrence | None = MONTHLY_ON_THE_20TH,
    due_in_days: int | None = None,
    effective_from: date = date(2026, 4, 1),
) -> RuleVersionSnapshot:
    return RuleVersionSnapshot(
        rule_id=RuleId.new(),
        rule_version_id=RuleVersionId.new(),
        version=1,
        regulator="cbic",
        title="File GSTR-3B every month",
        specification=Predicate("registration_type", Operator.EQ, "regular"),
        effective=EffectivePeriod(effective_from),
        obligation_template=ObligationTemplate(
            "File GSTR-3B", ("Reconcile", "File"), due_in_days, "filing_acknowledgement"
        ),
        recurrence=recurrence,
    )


def ref_of(snapshot: RuleVersionSnapshot, **overrides: Any) -> RuleVersionRef:
    """The facts the cache keeps of ``snapshot``: published, approved by ``ANALYST``, citing
    ``CITATION``, read at ``NOW``; ``overrides`` replace any of them."""
    ref = RuleVersionRef(
        rule_version_id=snapshot.rule_version_id,
        rule_key="gstr3b_monthly",
        status=RuleVersionStatus.PUBLISHED,
        title=snapshot.title,
        effective_from=snapshot.effective.start,
        effective_to=snapshot.effective.end,
        seed_status="needs_review",
        approved_by=(ANALYST,),
        published_at=NOW,
        citations=(CITATION,),
        fetched_at=NOW,
    )
    return replace(ref, **overrides)


class FakeRuleVersionReader:
    """The rulebook's versions from a dict; ``down`` makes every read fail as an outage would.
    A version reads with ``refs[id]`` when given, else with ``ref_of`` its snapshot, stamped
    with ``clock``. ``reads`` lists every read, ``fresh`` the ones that asked for a fresh read."""

    def __init__(
        self,
        versions: Iterable[RuleVersionSnapshot] = (),
        *,
        refs: Iterable[RuleVersionRef] = (),
        down: bool = False,
        clock: Callable[[], datetime] = clock,
    ) -> None:
        self.versions = {version.rule_version_id: version for version in versions}
        self.refs = {ref.rule_version_id: ref for ref in refs}
        self.down = down
        self.clock = clock
        self.reads: list[RuleVersionId] = []
        self.fresh: list[RuleVersionId] = []

    def read(
        self, rule_version_id: RuleVersionId, *, fresh: bool = False
    ) -> RuleVersionRead | None:
        self.reads.append(rule_version_id)
        if fresh:
            self.fresh.append(rule_version_id)
        if self.down:
            raise RulebookUnavailableError("rulebook unreachable (fake)")
        snapshot = self.versions.get(rule_version_id)
        if snapshot is None:
            return None
        ref = self.refs.get(rule_version_id) or ref_of(snapshot, fetched_at=self.clock())
        return RuleVersionRead(snapshot, ref)

    def end(
        self,
        rule_version_id: RuleVersionId,
        status: RuleVersionStatus,
        effective_to: date | None = None,
    ) -> RuleVersionRef:
        """Move a version the way the rulebook does when it is superseded or withdrawn; the
        reads after it say so."""
        snapshot = self.versions[rule_version_id]
        current = self.refs.get(rule_version_id) or ref_of(snapshot, fetched_at=self.clock())
        ended = replace(current.ended(status, effective_to), fetched_at=self.clock())
        self.refs[rule_version_id] = ended
        return ended


class FakeTenantMembers:
    """The users of each tenant from a set of ``(tenant, user)``; ``disabled`` users belong to
    their tenant but may no longer sign in, and ``down`` makes every call fail as an outage
    would. ``asked`` lists every call."""

    def __init__(
        self,
        members: Iterable[tuple[TenantId, UserId]] = (),
        *,
        disabled: Iterable[UserId] = (),
        down: bool = False,
    ) -> None:
        self.members = set(members)
        self.disabled = set(disabled)
        self.down = down
        self.asked: list[tuple[TenantId, UserId]] = []

    def membership(self, tenant_id: TenantId, user_id: UserId) -> Membership | None:
        self.asked.append((tenant_id, user_id))
        if self.down:
            raise IdentityUnavailableError("identity unreachable (fake)")
        if (tenant_id, user_id) not in self.members:
            return None
        return Membership(user_id, tenant_id, active=user_id not in self.disabled)


class FakeProfileNodes:
    """The profile nodes of each tenant from a set of ``(tenant, business)``; ``down`` makes
    every call fail as an outage would. ``asked`` lists every call."""

    def __init__(
        self, nodes: Iterable[tuple[TenantId, BusinessId]] = (), *, down: bool = False
    ) -> None:
        self.nodes = set(nodes)
        self.down = down
        self.asked: list[tuple[TenantId, BusinessId]] = []

    def exists(self, tenant_id: TenantId, business_id: BusinessId) -> bool:
        self.asked.append((tenant_id, business_id))
        if self.down:
            raise ProfileUnavailableError("profile unreachable (fake)")
        return (tenant_id, business_id) in self.nodes
