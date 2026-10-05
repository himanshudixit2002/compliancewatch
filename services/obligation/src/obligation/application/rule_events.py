"""The rulebook's events the obligation service acts on, and what the worker's consumer of group
``obligation.rules`` does with each. The events carry no tenant: each one is applied to every
tenant of the tenant directory, one unit of work per tenant.

- ``rule.published``: the ``rule_version_ref`` cache gets the version, read fresh from the
  rulebook. Nothing is materialised here: the engine fans the version out and the obligations
  arrive with its applicability.decided events.
- ``rule.withdrawn``: the version is cached as withdrawn and ``WithdrawRule`` closes its open
  obligations with reason ``rule_withdrawn``, each with its ``obligation.closed`` event and change
  row; the notification service turns those into withdrawal notices.
- ``rule.superseded``: the version is cached as superseded and ending on the day the newer one
  took over (the event's ``effective_from``), and ``CloseSupersededPeriods`` closes, with reason
  ``rule_superseded``, the open obligations the newer version takes over; earlier periods stay.
- ``rule.deadline_changed``: ``ApplyDeadlineChange`` moves the open obligations of the version and
  period to the new due date, each with ``obligation.rescheduled`` and its change row.

Each event is handled in two phases, as ``py_common.outbox.read_then_write`` runs them:
``plan(event)`` reads, with no transaction open, and ``apply(plan, ...)`` writes. A withdrawal or
a supersession reads the version fresh so the cache gets all of it; when the rulebook cannot answer
the cached row is moved on its own, and when there is neither a row nor an answer the event fails
and is retried, since a decision arriving later could not tell the version had ended. With the
flag ``obligation.rule_events`` off, ``plan`` returns None and the event changes nothing.

Every use case is idempotent: a closed obligation is never touched again and a moved one is
already at its new date, so a redelivered or replayed event changes nothing more.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import assert_never

from domain_kernel.events import utc_now
from domain_kernel.ids import EventId, ObligationId, RuleVersionId, TenantId
from domain_kernel.status import RuleVersionStatus
from obligation.application.changes import (
    ApplyDeadlineChange,
    ChangeResult,
    CloseSupersededPeriods,
    DeadlineChange,
    Supersession,
    WithdrawRule,
)
from obligation.domain.errors import RulebookUnavailableError
from obligation.domain.events import RescheduleReason
from obligation.domain.ports import RuleVersionReader
from obligation.domain.repository import RuleVersionRefs, TenantDirectory, UnitOfWorkFactory
from obligation.domain.rule_versions import RuleVersionRef


@dataclass(frozen=True, slots=True)
class RulePublished:
    event_id: EventId
    rule_version_id: RuleVersionId


@dataclass(frozen=True, slots=True)
class RuleWithdrawn:
    event_id: EventId
    rule_version_id: RuleVersionId
    effective_from: date


@dataclass(frozen=True, slots=True)
class RuleSuperseded:
    event_id: EventId
    rule_version_id: RuleVersionId
    superseded_by: RuleVersionId
    effective_from: date


@dataclass(frozen=True, slots=True)
class RuleDeadlineChanged:
    event_id: EventId
    rule_version_id: RuleVersionId
    caused_by: RuleVersionId
    period_label: str | None
    new_due_on: date
    reason: RescheduleReason


type RuleEvent = RulePublished | RuleWithdrawn | RuleSuperseded | RuleDeadlineChanged


@dataclass(frozen=True, slots=True)
class RulePlan:
    """What the reads found: the version as the rulebook has it now, or None with ``unread``
    saying why (``unknown`` when the rulebook has no such version, ``unavailable`` when it could
    not answer, ``not needed`` for a deadline change)."""

    event: RuleEvent
    fetched: RuleVersionRef | None = None
    unread: str = ""


@dataclass(frozen=True, slots=True)
class RuleApplied:
    """What an event changed: the tenants visited, the obligations closed or moved, the open
    ones it left as they were, and what the cache holds of the version now."""

    event: RuleEvent
    tenants: int = 0
    changed: tuple[ObligationId, ...] = ()
    unchanged: int = 0
    cached: RuleVersionRef | None = None


class RuleEvents:
    def __init__(
        self,
        rules: RuleVersionReader,
        *,
        enabled: bool,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._rules = rules
        self._enabled = enabled
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return self._enabled

    def plan(self, event: RuleEvent) -> RulePlan | None:
        """The reads, with no unit of work open; None while the flag is off."""
        if not self._enabled:
            return None
        if isinstance(event, RuleDeadlineChanged):
            return RulePlan(event, unread="not needed")
        try:
            read = self._rules.read(event.rule_version_id, fresh=True)
        except RulebookUnavailableError:
            if isinstance(event, RulePublished):
                raise
            return RulePlan(event, unread="unavailable")
        if read is None:
            return RulePlan(event, unread="unknown")
        return RulePlan(event, fetched=read.ref)

    def apply(
        self,
        plan: RulePlan,
        units: UnitOfWorkFactory,
        refs: RuleVersionRefs,
        tenants: TenantDirectory,
    ) -> RuleApplied:
        """The writes: the cache first, its row locked until the transaction ends, then one
        unit of work per tenant of the directory."""
        event = plan.event
        match event:
            case RulePublished():
                cached = None if plan.fetched is None else refs.merge(plan.fetched)
                return RuleApplied(event, cached=cached)
            case RuleWithdrawn():
                return self._withdraw(event, plan, units, refs, tenants)
            case RuleSuperseded():
                return self._supersede(event, plan, units, refs, tenants)
            case RuleDeadlineChanged():
                return self._move(event, units, refs, tenants)
            case _:  # pragma: no cover - the union is exhausted above
                assert_never(event)

    def _withdraw(
        self,
        event: RuleWithdrawn,
        plan: RulePlan,
        units: UnitOfWorkFactory,
        refs: RuleVersionRefs,
        tenants: TenantDirectory,
    ) -> RuleApplied:
        cached = self._end(plan, refs, RuleVersionStatus.WITHDRAWN, None)
        withdraw = WithdrawRule(units, clock=self._clock)
        return _each_tenant(
            event, tenants, lambda tenant: withdraw.run(tenant, event.rule_version_id), cached
        )

    def _supersede(
        self,
        event: RuleSuperseded,
        plan: RulePlan,
        units: UnitOfWorkFactory,
        refs: RuleVersionRefs,
        tenants: TenantDirectory,
    ) -> RuleApplied:
        cached = self._end(plan, refs, RuleVersionStatus.SUPERSEDED, event.effective_from)
        close = CloseSupersededPeriods(units, clock=self._clock)

        def change(tenant: TenantId) -> ChangeResult:
            return close.run(
                Supersession(
                    tenant, event.rule_version_id, event.superseded_by, event.effective_from
                )
            )

        return _each_tenant(event, tenants, change, cached)

    def _move(
        self,
        event: RuleDeadlineChanged,
        units: UnitOfWorkFactory,
        refs: RuleVersionRefs,
        tenants: TenantDirectory,
    ) -> RuleApplied:
        move = ApplyDeadlineChange(units, clock=self._clock)

        def change(tenant: TenantId) -> ChangeResult:
            return move.run(
                DeadlineChange(
                    tenant_id=tenant,
                    rule_version_id=event.rule_version_id,
                    period_label=event.period_label,
                    new_due_on=event.new_due_on,
                    reason=event.reason,
                    caused_by=event.caused_by,
                )
            )

        return _each_tenant(event, tenants, change, refs.get(event.rule_version_id))

    def _end(
        self,
        plan: RulePlan,
        refs: RuleVersionRefs,
        status: RuleVersionStatus,
        effective_to: date | None,
    ) -> RuleVersionRef | None:
        """Cache the version as ``status``, ending by ``effective_to``: the fresh read when there
        is one, else the cached row moved on."""
        rule_version_id = plan.event.rule_version_id
        if plan.fetched is not None:
            return refs.merge(plan.fetched.ended(status, effective_to))
        cached = refs.get(rule_version_id, lock=True)
        if cached is not None:
            return refs.merge(cached.ended(status, effective_to))
        if plan.unread == "unavailable":
            raise RulebookUnavailableError(
                f"rule version {rule_version_id} is neither cached nor readable at the rulebook, "
                f"so it cannot be recorded as {status.value}"
            )
        return None


def _each_tenant(
    event: RuleEvent,
    tenants: TenantDirectory,
    change: Callable[[TenantId], ChangeResult],
    cached: RuleVersionRef | None,
) -> RuleApplied:
    # One transaction holds every tenant's changes for the event, with its inbox row: right while
    # the tenants are few and each unit only reads the version's open obligations. A rule held by
    # thousands of tenants makes that transaction long and its retry all-or-nothing; per-tenant
    # transactions with their own processed mark come later.
    visited = 0
    changed: list[ObligationId] = []
    unchanged = 0
    for tenant in tenants.tenants():
        visited += 1
        result = change(tenant)
        changed.extend(result.changed)
        unchanged += result.unchanged
    return RuleApplied(event, visited, tuple(changed), unchanged, cached)
