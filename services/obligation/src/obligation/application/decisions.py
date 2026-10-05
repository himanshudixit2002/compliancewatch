"""Act on one applicability decision: materialise the obligations it implies, or close the ones
it no longer supports.

The applicability engine publishes ``applicability.decided`` for one business and one rule
version. ``ApplyDecision`` turns it into obligations in two steps, so no transaction is open while
the rulebook is read (``plan`` reads, ``apply`` writes, ``run`` does both):

- ``applies`` without ``needs_review``: ``plan`` reads the rule version (``RuleVersionReader``);
  ``apply`` puts the read through the guard (``guard.admit``: the ``rule_version_ref`` cache is
  filled when the version is missing, and a version the cache or the rulebook says is withdrawn,
  or that cites no verified clause, makes nothing) and then materialises the business's
  obligations of the version as of the day the decision was made in India, without the periods a
  superseded version no longer governs. Idempotent on (business, rule version, period), so a
  redelivered decision creates nothing new.
- ``not_applicable`` without ``needs_review``: every open obligation of the business and the
  rule version is closed with reason ``profile_changed``, each with its ``obligation.closed``
  event and change row. A closed obligation is never touched again, so a redelivery closes
  nothing more.
- anything that needs review (``unsure``, or a confidence under the engine's threshold): nothing
  happens until a person decides; the review flow publishes the decision it settles on.

Each applies or not_applicable decision is recorded as the business's latest for the version
(``obligation_decision``), which the rolling window reads. One made before the latest already
recorded changes nothing (``STALE``): a late decision cannot undo a newer one.

Every write happens in one unit of work of the decision's tenant from the factory given, which
for the consumer joins its inbox transaction.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain_kernel._validation import require_aware
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, TenantId
from domain_kernel.predicates import Applicability
from domain_kernel.status import ClosureReason
from obligation.application.audit import record
from obligation.application.guard import admit
from obligation.application.materialise import IST, MaterialiseRequest, materialise_in
from obligation.domain.errors import RuleVersionNotFoundError
from obligation.domain.ports import RuleVersionReader
from obligation.domain.repository import UnitOfWork, UnitOfWorkFactory
from obligation.domain.rule_versions import (
    AppliedDecision,
    Refusal,
    RuleVersionRead,
    RuleVersionRef,
)


@dataclass(frozen=True, slots=True)
class Decision:
    """What the service reads from one ``applicability.decided`` event."""

    tenant_id: TenantId
    decision_id: DecisionId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    result: Applicability
    needs_review: bool
    decided_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.decided_at, "decided_at")

    @property
    def awaits_review(self) -> bool:
        return self.needs_review or self.result is Applicability.UNSURE

    @property
    def materialises(self) -> bool:
        return not self.awaits_review and self.result is Applicability.APPLIES

    def applied(self) -> AppliedDecision:
        return AppliedDecision(
            tenant_id=self.tenant_id,
            business_id=self.business_id,
            rule_version_id=self.rule_version_id,
            decision_id=self.decision_id,
            applies=self.result is Applicability.APPLIES,
            decided_at=self.decided_at,
        )


class DecisionOutcome(StrEnum):
    MATERIALISED = "materialised"
    CLOSED = "closed"
    AWAITING_REVIEW = "awaiting_review"
    REFUSED = "refused"
    """The guard made nothing: the version is withdrawn or cites no verified clause."""
    STALE = "stale"
    """A later decision of the business and rule version was applied already."""


@dataclass(frozen=True, slots=True)
class DecisionPlan:
    """A decision and, for one that materialises, the version as the reader gave it."""

    decision: Decision
    read: RuleVersionRead | None = None


@dataclass(frozen=True, slots=True)
class DecisionApplied:
    """What a decision did. ``refusal`` says why the guard made nothing, or, with
    ``refused_periods``, why it left those periods out; ``ref`` is what the cache held of the
    version, and ``cached`` that this decision filled it."""

    outcome: DecisionOutcome
    created: tuple[ObligationId, ...] = ()
    closed: tuple[ObligationId, ...] = ()
    refusal: Refusal | None = None
    refused_periods: tuple[str, ...] = ()
    ref: RuleVersionRef | None = None
    cached: bool = False

    @property
    def guarded(self) -> bool:
        """Whether the guard kept anything from being made."""
        return self.refusal is not None


class ApplyDecision:
    def __init__(
        self,
        rules: RuleVersionReader,
        *,
        window: int = 2,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._rules = rules
        self._window = window
        self._clock = clock

    def plan(self, decision: Decision) -> DecisionPlan:
        """The reads, with no unit of work open: the rule version of a decision that
        materialises; ``RuleVersionNotFoundError`` when the rulebook has no such version."""
        if not decision.materialises:
            return DecisionPlan(decision)
        read = self._rules.read(decision.rule_version_id)
        if read is None:
            raise RuleVersionNotFoundError(str(decision.rule_version_id))
        return DecisionPlan(decision, read)

    def apply(self, plan: DecisionPlan, unit_of_work: UnitOfWorkFactory) -> DecisionApplied:
        """The writes, in one unit of work of the decision's tenant."""
        decision = plan.decision
        if decision.awaits_review:
            return DecisionApplied(DecisionOutcome.AWAITING_REVIEW)
        with unit_of_work(decision.tenant_id) as uow:
            if not uow.decisions.record(decision.applied()):
                return DecisionApplied(DecisionOutcome.STALE)
            if decision.result is Applicability.NOT_APPLICABLE:
                return DecisionApplied(DecisionOutcome.CLOSED, closed=self._close(uow, decision))
            return self._materialise(uow, plan)

    def run(self, decision: Decision, unit_of_work: UnitOfWorkFactory) -> DecisionApplied:
        return self.apply(self.plan(decision), unit_of_work)

    def _materialise(self, uow: UnitOfWork, plan: DecisionPlan) -> DecisionApplied:
        decision, read = plan.decision, plan.read
        if read is None:
            raise InvariantViolationError("an applying decision is applied with its rule version")
        admission = admit(uow, read.ref)
        if admission.refusal is not None:
            return DecisionApplied(
                DecisionOutcome.REFUSED,
                refusal=admission.refusal,
                ref=admission.ref,
                cached=admission.filled,
            )
        result = materialise_in(
            uow,
            MaterialiseRequest(
                tenant_id=decision.tenant_id,
                business_id=decision.business_id,
                decision_id=decision.decision_id,
                rule=read.snapshot,
                as_of=decision.decided_at.astimezone(IST).date(),
                ref=admission.ref,
            ),
            window=self._window,
            now=self._clock(),
        )
        return DecisionApplied(
            DecisionOutcome.MATERIALISED,
            created=result.created,
            refusal=Refusal.RULE_SUPERSEDED if result.refused else None,
            refused_periods=result.refused,
            ref=admission.ref,
            cached=admission.filled,
        )

    def _close(self, uow: UnitOfWork, decision: Decision) -> tuple[ObligationId, ...]:
        now = self._clock()
        closed: list[ObligationId] = []
        for obligation in uow.obligations.open_for_rule_version(
            decision.rule_version_id, business_id=decision.business_id
        ):
            done, event = obligation.close(ClosureReason.PROFILE_CHANGED, at=now)
            uow.obligations.save(done)
            record(uow, event, done)
            closed.append(done.id)
        return tuple(closed)
