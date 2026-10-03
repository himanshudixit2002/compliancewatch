"""Act on one applicability decision: materialise the obligations it implies, or close the ones
it no longer supports.

The applicability engine publishes ``applicability.decided`` for one business and one rule
version. ``ApplyDecision.run`` turns it into obligations:

- ``applies`` without ``needs_review``: ``MaterialiseObligations`` for the business and the rule
  version, read from the rulebook (``RuleVersionReader``), as of the day the decision was made in
  India. Idempotent on (business, rule version, period), so a redelivered decision creates
  nothing new.
- ``not_applicable`` without ``needs_review``: every open obligation of the business and the
  rule version is closed with reason ``profile_changed``, each with its ``obligation.closed``
  event and change row. A closed obligation is never touched again, so a redelivery closes
  nothing more.
- anything that needs review (``unsure``, or a confidence under the engine's threshold): nothing
  happens until a person decides; the review flow publishes the decision it settles on.

Every write happens in units of work of the decision's tenant from the factory given, which for
the consumer joins its inbox transaction.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from domain_kernel._validation import require_aware
from domain_kernel.events import utc_now
from domain_kernel.ids import BusinessId, DecisionId, ObligationId, RuleVersionId, TenantId
from domain_kernel.predicates import Applicability
from domain_kernel.status import ClosureReason
from obligation.application.audit import record
from obligation.application.materialise import IST, MaterialiseObligations, MaterialiseRequest
from obligation.domain.errors import RuleVersionNotFoundError
from obligation.domain.ports import RuleVersionReader
from obligation.domain.repository import UnitOfWorkFactory


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


class DecisionOutcome(StrEnum):
    MATERIALISED = "materialised"
    CLOSED = "closed"
    AWAITING_REVIEW = "awaiting_review"


@dataclass(frozen=True, slots=True)
class DecisionApplied:
    outcome: DecisionOutcome
    created: tuple[ObligationId, ...] = ()
    closed: tuple[ObligationId, ...] = ()


class ApplyDecision:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        rules: RuleVersionReader,
        *,
        window: int = 2,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._rules = rules
        self._materialise = MaterialiseObligations(unit_of_work, window=window, clock=clock)
        self._clock = clock

    def run(self, decision: Decision) -> DecisionApplied:
        if decision.needs_review or decision.result is Applicability.UNSURE:
            return DecisionApplied(DecisionOutcome.AWAITING_REVIEW)
        if decision.result is Applicability.NOT_APPLICABLE:
            return DecisionApplied(DecisionOutcome.CLOSED, closed=self._close(decision))
        rule = self._rules.get(decision.rule_version_id)
        if rule is None:
            raise RuleVersionNotFoundError(str(decision.rule_version_id))
        result = self._materialise.run(
            MaterialiseRequest(
                tenant_id=decision.tenant_id,
                business_id=decision.business_id,
                decision_id=decision.decision_id,
                rule=rule,
                as_of=decision.decided_at.astimezone(IST).date(),
            )
        )
        return DecisionApplied(DecisionOutcome.MATERIALISED, created=result.created)

    def _close(self, decision: Decision) -> tuple[ObligationId, ...]:
        now = self._clock()
        closed: list[ObligationId] = []
        with self._unit_of_work(decision.tenant_id) as uow:
            for obligation in uow.obligations.open_for_rule_version(
                decision.rule_version_id, business_id=decision.business_id
            ):
                done, event = obligation.close(ClosureReason.PROFILE_CHANGED, at=now)
                uow.obligations.save(done)
                record(uow, event, done)
                closed.append(done.id)
        return tuple(closed)
