"""Decide one batch of a fan-out: a page of the business directory, one tenant at a time.

``EvaluateBatch.run(request)`` reads the published version from the rulebook, then the next page
of the directory for the version's level (``request.limit`` entries after ``request.after``, by
tenant then node) in a read of its own. Entries of one tenant sit together on the page, and each
tenant's group is handled in two steps, so no HTTP call is made while a transaction is open:

1. for each business, its snapshot from the profile service for the current financial year in
   India, with no unit of work open, and the version evaluated against it; a business the profile
   service no longer has is skipped;
2. in one unit of work of the tenant, each decision appended unless it is already stored, with
   the trigger ``rule_published`` and ``trigger_ref`` ``rule.published:<event id>``, so its id
   derives from the event, the business and the version, and a retried batch stores nothing
   twice. It publishes ``applicability.decided`` under the same rule as a recompute
   (``recompute.publishes``: it applies, or its result or need for review differs from the
   previous decision of its business and version), caused by the rule.published event, and keeps
   the review queue in step (``track_review``).

When the version supersedes others, each business decided is compared with the latest decision
of the superseded versions for the same business: ``flips_compared`` counts the businesses that
had one, ``flips`` those whose result changed. The counts cover every business decided, stored now
or before, so a retried batch counts the same. ``progress`` is called after each tenant group (the
workflow's activity heartbeats meanwhile).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import groupby

from applicability_engine.application.recompute import publishes
from applicability_engine.application.review import track_review
from applicability_engine.domain.directory import DirectoryEntry, DirectoryKey
from applicability_engine.domain.errors import (
    RuleVersionNotFoundError,
    RuleVersionNotPublishedError,
)
from applicability_engine.domain.evaluation import evaluate
from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.fanout import BATCH_SIZE, FanOutStart
from applicability_engine.domain.model import (
    Decision,
    RuleVersionSpec,
    Trigger,
    decision_id_for,
)
from applicability_engine.domain.ports import ProfileReader, RulebookReader
from applicability_engine.domain.repository import (
    BusinessDirectoryReader,
    UnitOfWork,
    UnitOfWorkFactory,
)
from domain_kernel._validation import require_int
from domain_kernel.events import utc_now
from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import Ontology
from domain_kernel.predicates import Applicability
from domain_kernel.status import RuleVersionStatus

IST = timezone(timedelta(hours=5, minutes=30))
"""Financial years are India's."""


@dataclass(frozen=True, slots=True)
class BatchRequest:
    start: FanOutStart
    after: DirectoryKey | None = None
    limit: int = BATCH_SIZE

    def __post_init__(self) -> None:
        require_int(self.limit, "limit", minimum=1)


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """``read`` is the directory entries the page held, ``evaluated`` the businesses decided of
    them (the others are ``skipped``: the profile service no longer has them), ``appended`` the
    decisions stored now and ``published`` those whose event went out. ``last`` is where the next
    page starts, and ``done`` says the page was the directory's last."""

    read: int = 0
    evaluated: int = 0
    applies: int = 0
    flips_compared: int = 0
    flips: int = 0
    appended: int = 0
    published: int = 0
    skipped: int = 0
    last: DirectoryKey | None = None
    done: bool = True


@dataclass(frozen=True, slots=True)
class _Stored:
    applies: int = 0
    flips_compared: int = 0
    flips: int = 0
    appended: int = 0
    published: int = 0


class EvaluateBatch:
    def __init__(
        self,
        directory: BusinessDirectoryReader,
        unit_of_work: UnitOfWorkFactory,
        profiles: ProfileReader,
        rulebook: RulebookReader,
        ontology: Ontology,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._directory = directory
        self._unit_of_work = unit_of_work
        self._profiles = profiles
        self._rulebook = rulebook
        self._ontology = ontology
        self._clock = clock

    def run(
        self, request: BatchRequest, *, progress: Callable[[], None] = lambda: None
    ) -> BatchOutcome:
        start = request.start
        rule = self._rulebook.rule_version(start.rule_version_id)
        if rule is None:
            raise RuleVersionNotFoundError(str(start.rule_version_id))
        if rule.status is not RuleVersionStatus.PUBLISHED:
            raise RuleVersionNotPublishedError(str(rule.rule_version_id), rule.status.value)
        entries = self._directory.entries(
            level=start.level, after=request.after, limit=request.limit
        )
        now = self._clock()
        fy = FinancialYear.for_date(now.astimezone(IST).date())
        evaluated = 0
        totals = _Stored()
        for tenant_id, group in groupby(entries, key=lambda entry: entry.tenant_id):
            decided = self._decide(start, rule, tenant_id, list(group), fy, now)
            evaluated += len(decided)
            stored = self._store(tenant_id, start, decided, now)
            totals = _Stored(
                applies=totals.applies + stored.applies,
                flips_compared=totals.flips_compared + stored.flips_compared,
                flips=totals.flips + stored.flips,
                appended=totals.appended + stored.appended,
                published=totals.published + stored.published,
            )
            progress()
        return BatchOutcome(
            read=len(entries),
            evaluated=evaluated,
            applies=totals.applies,
            flips_compared=totals.flips_compared,
            flips=totals.flips,
            appended=totals.appended,
            published=totals.published,
            skipped=len(entries) - evaluated,
            last=DirectoryKey.of(entries[-1]) if entries else request.after,
            done=len(entries) < request.limit,
        )

    def _decide(
        self,
        start: FanOutStart,
        rule: RuleVersionSpec,
        tenant_id: TenantId,
        entries: Sequence[DirectoryEntry],
        fy: FinancialYear,
        now: datetime,
    ) -> list[Decision]:
        """The reads and the evaluations: HTTP only, no unit of work open."""
        decided: list[Decision] = []
        for entry in entries:
            snapshot = self._profiles.snapshot(tenant_id, entry.business_id, fy)
            if snapshot is None:
                continue
            evaluation = evaluate(rule.specification, snapshot.attributes, self._ontology)
            decided.append(
                Decision(
                    decision_id=decision_id_for(
                        start.trigger_ref, entry.business_id, start.rule_version_id
                    ),
                    tenant_id=tenant_id,
                    business_id=entry.business_id,
                    rule_version_id=start.rule_version_id,
                    result=evaluation.result,
                    confidence=evaluation.confidence,
                    evaluated=evaluation.evaluated,
                    profile_version=snapshot.version,
                    decided_at=now,
                    trigger=Trigger.RULE_PUBLISHED,
                    as_of_fy=snapshot.as_of_fy,
                    trigger_ref=start.trigger_ref,
                )
            )
        return decided

    def _store(
        self, tenant_id: TenantId, start: FanOutStart, decided: Sequence[Decision], now: datetime
    ) -> _Stored:
        """The writes of one tenant's group, in one unit of work."""
        if not decided:
            return _Stored()
        applies = flips_compared = flips = appended = published = 0
        with self._unit_of_work(tenant_id) as uow:
            for decision in decided:
                applies += decision.result is Applicability.APPLIES
                superseded = _superseded(uow, decision.business_id, start)
                if superseded is not None:
                    flips_compared += 1
                    flips += superseded.result is not decision.result
                previous = uow.decisions.latest(decision.business_id, decision.rule_version_id)
                if not uow.decisions.add_if_absent(decision):
                    continue
                appended += 1
                if publishes(decision, previous):
                    uow.events.publish(
                        ApplicabilityDecided.of(
                            decision,
                            correlation_id=start.correlation_id,
                            causation_id=start.trigger_event_id,
                        )
                    )
                    published += 1
                track_review(uow, decision, at=now)
        return _Stored(applies, flips_compared, flips, appended, published)


def _superseded(uow: UnitOfWork, business_id: BusinessId, start: FanOutStart) -> Decision | None:
    """The latest decision of the business under any version ``start`` supersedes."""
    found = [
        decision
        for superseded in start.supersedes
        if (decision := uow.decisions.latest(business_id, superseded)) is not None
    ]
    if not found:
        return None
    return max(found, key=lambda decision: (decision.decided_at, decision.decision_id.value))
