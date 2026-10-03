"""Evaluate one rule version against one business's profile and record the decision.

The rule version comes from the rulebook and must be published; the profile snapshot comes from
the profile service, for the financial year asked (the current one in India when none is). The
specification is evaluated deterministically (``domain.evaluation``): free text and anything the
ontology cannot decide is unsure and the decision goes to review, never a guess. Every run
appends a new decision, even when nothing changed since the last one, and writes its
``applicability.decided`` event in the same transaction, so the obligation service hears of
every decision that was stored and of no other.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from applicability_engine.domain.errors import (
    BusinessNotFoundError,
    RuleVersionNotFoundError,
    RuleVersionNotPublishedError,
)
from applicability_engine.domain.evaluation import evaluate
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.model import Decision, Trigger
from applicability_engine.domain.ports import ProfileReader, RulebookReader
from applicability_engine.domain.repository import UnitOfWorkFactory
from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.ontology import Ontology
from domain_kernel.status import RuleVersionStatus

IST = timezone(timedelta(hours=5, minutes=30))
"""Financial years are Indian; the default one is the year that contains today in India."""


@dataclass(frozen=True, slots=True)
class EvaluateRequest:
    tenant_id: TenantId
    business_id: BusinessId
    rule_version_id: RuleVersionId
    trigger: Trigger = Trigger.MANUAL
    fy: FinancialYear | None = None


class EvaluateRule:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        profiles: ProfileReader,
        rulebook: RulebookReader,
        ontology: Ontology,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._profiles = profiles
        self._rulebook = rulebook
        self._ontology = ontology
        self._clock = clock

    def run(self, request: EvaluateRequest) -> Decision:
        rule = self._rulebook.rule_version(request.rule_version_id)
        if rule is None:
            raise RuleVersionNotFoundError(str(request.rule_version_id))
        if rule.status is not RuleVersionStatus.PUBLISHED:
            raise RuleVersionNotPublishedError(str(rule.rule_version_id), rule.status.value)
        now = self._clock()
        fy = request.fy or FinancialYear.for_date(now.astimezone(IST).date())
        snapshot = self._profiles.snapshot(request.tenant_id, request.business_id, fy)
        if snapshot is None:
            raise BusinessNotFoundError(str(request.business_id))
        evaluation = evaluate(rule.specification, snapshot.attributes, self._ontology)
        decision = Decision(
            decision_id=DecisionId.new(),
            tenant_id=request.tenant_id,
            business_id=request.business_id,
            rule_version_id=rule.rule_version_id,
            result=evaluation.result,
            confidence=evaluation.confidence,
            evaluated=evaluation.evaluated,
            profile_version=snapshot.version,
            decided_at=now,
            trigger=request.trigger,
            as_of_fy=snapshot.as_of_fy,
        )
        with self._unit_of_work(request.tenant_id) as uow:
            uow.decisions.add(decision)
            uow.events.publish(ApplicabilityDecided.of(decision))
        return decision
