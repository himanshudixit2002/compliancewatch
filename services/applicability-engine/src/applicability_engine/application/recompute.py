"""Recompute a business's decisions when its profile changes: the profile.updated consumer.

``ApplyProfileUpdate`` works in two phases, so no HTTP call is ever made inside a database
transaction:

- ``plan(update)`` reads over HTTP only. It reads the changed node's snapshot (its level and its
  lineage) and, when the node is a legal entity, the registrations under it: the nodes the
  directory records. With recompute on (flag ``applicability.recompute``) it also reads each
  node's snapshot for the current financial year in India and the rule versions in force for
  the node's level, and evaluates every pair. The versions are the ones in force today in India
  and, with ``lookahead_days``, the ones in force that many days from now: a version published
  to take effect later already makes obligations for the periods of the obligation service's
  window that it governs, so its decision has to follow the profile before it takes effect.
  With ``superseded_lookback_days`` they also include the versions superseded within that many
  days that still govern a duty due today or later (``RuleVersionSpec.still_governs``): a
  version governs the periods whose last day it is in force on, so superseded from 1 October a
  monthly return's version still governs September, due 20 October, and a business that comes
  on 5 October owes it under that version, which nothing else would decide for it. On 25
  October nothing of it is due, and it is left out.
  Locations have no listing route in the profile service, so a change on a registration or an
  entity does not reach the locations under it; a change on a location recomputes the location.
- ``apply(plan, unit_of_work)`` writes in one unit of work of the tenant: the directory entries
  it does not hold yet, then each decision unless it is already stored. A decision's id derives
  from the event (``trigger_ref`` ``profile.updated:<event id>``), the business and the rule
  version, so handling the same event again stores nothing and publishes nothing. A stored
  decision publishes ``applicability.decided`` when its result is ``applies`` (the obligation
  service makes any period of the window still missing, idempotently) or when its result or its
  need for review differs from the previous decision of its business and rule version (none
  before counts as different); an unchanged not_applicable or unsure decision is stored without
  an event. Each stored decision then keeps the review queue in step (``track_review``).

With recompute off the plan holds the directory entries alone: the directory stays complete
while nothing is evaluated.
"""

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from applicability_engine.application.review import ReviewChange, track_review
from applicability_engine.domain.directory import DirectoryEntry
from applicability_engine.domain.evaluation import evaluate
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.model import Decision, RuleInForce, Trigger, decision_id_for
from applicability_engine.domain.ports import ProfileReader, RulebookReader
from applicability_engine.domain.repository import UnitOfWorkFactory
from domain_kernel._validation import require_int
from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, CorrelationId, DecisionId, EventId, TenantId
from domain_kernel.ontology import AttributeLevel, Ontology
from domain_kernel.predicates import Applicability
from domain_kernel.profiles import ProfileSnapshot

IST = timezone(timedelta(hours=5, minutes=30))
"""Rules are in force on days in India, and the financial year is India's."""


@dataclass(frozen=True, slots=True)
class ProfileUpdate:
    """What the engine reads from one profile.updated event."""

    tenant_id: TenantId
    event_id: EventId
    business_id: BusinessId
    profile_version: int
    changed_attributes: tuple[str, ...] = ()
    correlation_id: CorrelationId | None = None

    def __post_init__(self) -> None:
        require_int(self.profile_version, "profile_version", minimum=1)

    @property
    def trigger_ref(self) -> str:
        return f"profile.updated:{self.event_id}"


@dataclass(frozen=True, slots=True)
class RecomputePlan:
    """What the reads found: ``found`` is False when the tenant has no such node any more, and
    ``evaluated`` False when recompute is off."""

    update: ProfileUpdate
    found: bool
    evaluated: bool
    directory: tuple[DirectoryEntry, ...] = ()
    decisions: tuple[Decision, ...] = ()


@dataclass(frozen=True, slots=True)
class Recomputed:
    """What ``apply`` stored: the new directory entries, the decisions it appended (none of a
    replayed event), the ones whose event it published and how the review queue moved."""

    plan: RecomputePlan
    listed: int = 0
    appended: tuple[Decision, ...] = ()
    published: tuple[DecisionId, ...] = ()
    reviews: Mapping[ReviewChange, int] = field(default_factory=dict)


def publishes(decision: Decision, previous: Decision | None) -> bool:
    """Whether a recomputed decision publishes ``applicability.decided``: it applies, or its
    result or its need for review differs from the previous decision of its pair."""
    if decision.result is Applicability.APPLIES or previous is None:
        return True
    return (previous.result, previous.needs_review) != (decision.result, decision.needs_review)


def entry_of(snapshot: ProfileSnapshot, level: AttributeLevel) -> DirectoryEntry:
    """The directory entry of the node a snapshot describes, placed by its lineage."""
    lineage = snapshot.lineage
    return DirectoryEntry(
        tenant_id=snapshot.tenant_id,
        business_id=snapshot.business_id,
        level=level,
        parent_id=lineage[-1] if lineage else None,
        entity_id=lineage[0] if lineage else snapshot.business_id,
    )


class ApplyProfileUpdate:
    def __init__(
        self,
        profiles: ProfileReader,
        rulebook: RulebookReader,
        ontology: Ontology,
        *,
        enabled: bool,
        lookahead_days: int = 0,
        superseded_lookback_days: int = 0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._profiles = profiles
        self._rulebook = rulebook
        self._ontology = ontology
        self._enabled = enabled
        self._lookahead = timedelta(days=require_int(lookahead_days, "lookahead_days", minimum=0))
        self._lookback = timedelta(
            days=require_int(superseded_lookback_days, "superseded_lookback_days", minimum=0)
        )
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return self._enabled

    def run(self, update: ProfileUpdate, unit_of_work: UnitOfWorkFactory) -> Recomputed:
        return self.apply(self.plan(update), unit_of_work)

    def plan(self, update: ProfileUpdate) -> RecomputePlan:
        """The reads: every call here goes to another service, and none to the database."""
        now = self._clock()
        today = now.astimezone(IST).date()
        fy = FinancialYear.for_date(today)
        root = self._profiles.snapshot(update.tenant_id, update.business_id, fy)
        if root is None or root.level is None:
            return RecomputePlan(update, found=False, evaluated=False)
        entries = [entry_of(root, root.level)]
        nodes: list[tuple[ProfileSnapshot, AttributeLevel]] = [(root, root.level)]
        if root.level is AttributeLevel.ENTITY:
            for registration_id in (
                self._profiles.registrations(update.tenant_id, root.business_id) or ()
            ):
                entries.append(
                    DirectoryEntry(
                        tenant_id=update.tenant_id,
                        business_id=registration_id,
                        level=AttributeLevel.REGISTRATION,
                        parent_id=root.business_id,
                        entity_id=root.business_id,
                    )
                )
                if self._enabled:
                    snapshot = self._profiles.snapshot(update.tenant_id, registration_id, fy)
                    if snapshot is not None:
                        nodes.append((snapshot, AttributeLevel.REGISTRATION))
        if not self._enabled:
            return RecomputePlan(update, found=True, evaluated=False, directory=tuple(entries))
        rules: dict[AttributeLevel, list[RuleInForce]] = {}
        decisions: list[Decision] = []
        for snapshot, level in nodes:
            if level not in rules:
                rules[level] = self._rules(today, level)
            decisions.extend(self._decide(update, snapshot, rule, now) for rule in rules[level])
        return RecomputePlan(
            update,
            found=True,
            evaluated=True,
            directory=tuple(entries),
            decisions=tuple(decisions),
        )

    def apply(self, plan: RecomputePlan, unit_of_work: UnitOfWorkFactory) -> Recomputed:
        """The writes, in one unit of work of the tenant."""
        update = plan.update
        if not plan.directory and not plan.decisions:
            return Recomputed(plan)
        at = self._clock()
        appended: list[Decision] = []
        published: list[DecisionId] = []
        reviews: Counter[ReviewChange] = Counter()
        with unit_of_work(update.tenant_id) as uow:
            listed = sum(1 for entry in plan.directory if uow.directory.add(entry))
            for decision in plan.decisions:
                previous = uow.decisions.latest(decision.business_id, decision.rule_version_id)
                if not uow.decisions.add_if_absent(decision):
                    continue
                appended.append(decision)
                if publishes(decision, previous):
                    uow.events.publish(
                        ApplicabilityDecided.of(
                            decision,
                            correlation_id=update.correlation_id,
                            causation_id=update.event_id,
                        )
                    )
                    published.append(decision.decision_id)
                change = track_review(uow, decision, at=at)
                if change is not None:
                    reviews[change] += 1
        return Recomputed(
            plan,
            listed=listed,
            appended=tuple(appended),
            published=tuple(published),
            reviews=dict(reviews),
        )

    def _rules(self, today: date, level: AttributeLevel) -> list[RuleInForce]:
        """The versions a node of ``level`` is decided against today: in force today, in force
        at the end of the lookahead, and superseded within the lookback while they still govern
        a duty due today or later; each once, by rule key then start."""
        found = {rule.rule_version_id: rule for rule in self._rulebook.rules_in_force(today, level)}
        if self._lookahead:
            for rule in self._rulebook.rules_in_force(today + self._lookahead, level):
                found.setdefault(rule.rule_version_id, rule)
        if self._lookback:
            for rule in self._rulebook.rules_superseded_since(today - self._lookback, level):
                if rule.spec.still_governs(today):
                    found.setdefault(rule.rule_version_id, rule)
        return sorted(found.values(), key=lambda rule: (rule.rule_key, rule.effective_from))

    def _decide(
        self, update: ProfileUpdate, snapshot: ProfileSnapshot, rule: RuleInForce, now: datetime
    ) -> Decision:
        evaluation = evaluate(rule.spec.specification, snapshot.attributes, self._ontology)
        return Decision(
            decision_id=decision_id_for(
                update.trigger_ref, snapshot.business_id, rule.rule_version_id
            ),
            tenant_id=update.tenant_id,
            business_id=snapshot.business_id,
            rule_version_id=rule.rule_version_id,
            result=evaluation.result,
            confidence=evaluation.confidence,
            evaluated=evaluation.evaluated,
            profile_version=snapshot.version,
            decided_at=now,
            trigger=Trigger.PROFILE_UPDATED,
            as_of_fy=snapshot.as_of_fy,
            trigger_ref=update.trigger_ref,
        )
