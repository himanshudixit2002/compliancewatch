"""Cite, review and publish rule versions, withdraw them, and move replaced versions when their
replacement takes effect.

A version is drafted (the seed calendar writes drafts), cited, submitted for review, approved by
one analyst or two different ones when it is high impact, and published (ADR-006). Each step is
one transaction: it locks the version, checks the move against the kernel's transition table,
writes the new state and appends a row to the decision audit. Publishing writes its events to
the outbox in the same transaction; ``rulebook.domain.publication`` decides what it changes.

Days are days in India: "today" is the date in Asia/Kolkata when the step runs. A replacement
dated in the future cuts the replaced version's ``effective_to`` at publication and moves its
status when the day comes, which ``ApplyDueTransitions`` does once a day.

``CW_RULEBOOK_PUBLISH_ENABLED`` gates publishing, withdrawing and the sweep (``enabled``). Citing
and review work with it off, so analysts can prepare versions before publication is turned on.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, CorrelationId, RuleVersionId, UserId
from domain_kernel.knowledge import RelationKind
from domain_kernel.status import RULE_VERSION_TRANSITIONS, RuleVersionStatus
from rulebook.application.alignment import Clock, default_clock
from rulebook.domain.errors import (
    CitationNotVerifiedError,
    DuplicateApproverError,
    PublishingDisabledError,
    RuleVersionNotEditableError,
    UnknownClauseError,
    UnknownRuleVersionError,
)
from rulebook.domain.events import RuleEvent
from rulebook.domain.graph import RelationQuery, RelationRecord
from rulebook.domain.ids import citation_id_for
from rulebook.domain.publication import (
    REPLACING,
    DecisionAction,
    PendingReplacement,
    PublicationPlan,
    RuleVersionDecision,
    check_withdrawal,
    plan_due_transitions,
    plan_publication,
    required_approvals,
    transition_event,
)
from rulebook.domain.relations import EDITABLE_FROM_STATUSES
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord, check_quote
from rulebook.domain.seed import SeedStatus

IST = timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")
"""India keeps one offset all year, so a fixed zone gives the same dates as Asia/Kolkata."""
MAX_CITATIONS = 50
MAX_RELATIONS = 1_000


def today_in_india(now: datetime) -> date:
    return now.astimezone(IST).date()


@dataclass(frozen=True, slots=True)
class CitationInput:
    clause_id: ClauseId
    quote: str


@dataclass(frozen=True, slots=True)
class CitationReport:
    added: int
    unchanged: int
    citations: tuple[CitationRecord, ...]


@dataclass(frozen=True, slots=True)
class VersionState:
    """A version after a step, with the approvers of its current review round and the events
    the step wrote."""

    record: RuleVersionRecord
    approvers: tuple[UserId, ...] = ()
    events: tuple[RuleEvent, ...] = ()

    @property
    def required_approvals(self) -> int:
        return required_approvals(self.record.high_impact)


@dataclass(frozen=True, slots=True)
class Publication:
    plan: PublicationPlan
    events: tuple[RuleEvent, ...]
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class SweepReport:
    as_of: date
    transitions: tuple[PendingReplacement, ...]
    events: tuple[RuleEvent, ...]


def _locked(uow: KnowledgeUnitOfWork, rule_version_id: RuleVersionId) -> RuleVersionRecord:
    record = uow.rule_versions.lock(rule_version_id)
    if record is None:
        raise UnknownRuleVersionError(str(rule_version_id))
    return record


def _own_relations(
    uow: KnowledgeUnitOfWork, rule_version_id: RuleVersionId
) -> Sequence[RelationRecord]:
    """The relations from the version, whether or not it has been published."""
    return uow.relations.find(
        RelationQuery(
            from_rule_version_id=rule_version_id, published_only=False, limit=MAX_RELATIONS
        )
    )


def _decision(
    record: RuleVersionRecord,
    action: DecisionAction,
    to_status: RuleVersionStatus,
    at: datetime,
    *,
    actor_id: UserId | None = None,
    caused_by: RuleVersionId | None = None,
    note: str = "",
) -> RuleVersionDecision:
    return RuleVersionDecision(
        decision_id=uuid4(),
        rule_version_id=record.rule_version_id,
        action=action,
        from_status=record.status,
        to_status=to_status,
        decided_at=at,
        actor_id=actor_id,
        caused_by=caused_by,
        note=note,
    )


class AddCitations:
    """Cite clauses for a version before publication. All or nothing: every quote must be in its
    clause (a fuzzy score of at least 0.85 and every number, form code and month name present),
    otherwise nothing is stored. A citation's id derives from the version, clause and quote, so
    sending the same one again changes nothing."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self, rule_version_id: RuleVersionId, citations: Sequence[CitationInput]
    ) -> CitationReport:
        if not 1 <= len(citations) <= MAX_CITATIONS:
            raise InvariantViolationError(f"send 1 to {MAX_CITATIONS} citations at a time")
        now = self._clock()
        with self._unit_of_work() as uow:
            version = _locked(uow, rule_version_id)
            if version.status not in EDITABLE_FROM_STATUSES:
                raise RuleVersionNotEditableError(
                    f"rule version {rule_version_id} is {version.status.value}"
                )
            records: dict[UUID, CitationRecord] = {}
            unknown: list[str] = []
            failures: list[str] = []
            for citation in citations:
                detail = uow.documents.clause(citation.clause_id)
                if detail is None:
                    unknown.append(str(citation.clause_id))
                    continue
                check = check_quote(citation.quote, detail.clause.text)
                if not check.verified:
                    missing = f", missing {', '.join(check.missing)}" if check.missing else ""
                    failures.append(
                        f"{detail.clause.clause_ref} of {detail.clause.document_id}: score "
                        f"{check.score:.2f}{missing}"
                    )
                    continue
                citation_id = citation_id_for(rule_version_id, citation.clause_id, citation.quote)
                records[citation_id] = CitationRecord(
                    citation_id=citation_id,
                    rule_version_id=rule_version_id,
                    clause_id=citation.clause_id,
                    document_id=detail.clause.document_id,
                    clause_ref=detail.clause.clause_ref,
                    quote=citation.quote,
                    verified=True,
                    match_score=round(check.score, 3),
                    verified_at=now,
                )
            if unknown:
                raise UnknownClauseError(
                    f"{len(unknown)} clauses are not stored: " + ", ".join(sorted(unknown)[:5])
                )
            if failures:
                raise CitationNotVerifiedError(
                    f"{len(failures)} quotes are not in their clause: " + "; ".join(failures[:5])
                )
            added = sum(uow.citations.add(record) for record in records.values())
            return CitationReport(
                added=added,
                unchanged=len(records) - added,
                citations=uow.citations.for_version(rule_version_id),
            )


class SubmitForReview:
    """Start a review round. ``high_impact`` tags the version for two approvers; once set, a
    later submission cannot clear it (ADR-006)."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        rule_version_id: RuleVersionId,
        *,
        actor_id: UserId,
        high_impact: bool = False,
        note: str = "",
    ) -> VersionState:
        now = self._clock()
        with self._unit_of_work() as uow:
            version = _locked(uow, rule_version_id)
            RULE_VERSION_TRANSITIONS.assert_transition(version.status, RuleVersionStatus.IN_REVIEW)
            submitted = replace(
                version,
                status=RuleVersionStatus.IN_REVIEW,
                submitted_at=now,
                high_impact=version.high_impact or high_impact,
            )
            uow.rule_versions.save_lifecycle(submitted)
            uow.rule_versions.record_decision(
                _decision(
                    version,
                    DecisionAction.SUBMITTED,
                    submitted.status,
                    now,
                    actor_id=actor_id,
                    note=note,
                )
            )
        return VersionState(submitted)


class ReturnToDraft:
    """Send a version under review back to draft. Its approvals stay in the audit but no longer
    count: the next submission starts a new round."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self, rule_version_id: RuleVersionId, *, actor_id: UserId, note: str = ""
    ) -> VersionState:
        now = self._clock()
        with self._unit_of_work() as uow:
            version = _locked(uow, rule_version_id)
            RULE_VERSION_TRANSITIONS.assert_transition(version.status, RuleVersionStatus.DRAFT)
            returned = replace(version, status=RuleVersionStatus.DRAFT, submitted_at=None)
            uow.rule_versions.save_lifecycle(returned)
            uow.rule_versions.record_decision(
                _decision(
                    version,
                    DecisionAction.RETURNED,
                    returned.status,
                    now,
                    actor_id=actor_id,
                    note=note,
                )
            )
        return VersionState(returned)


class ApproveVersion:
    """Record one approval of the current round. The approval that completes the round (the
    first, or the second different approver of a high-impact version) moves the version to
    approved and marks its seed status reviewed."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self, rule_version_id: RuleVersionId, *, actor_id: UserId, note: str = ""
    ) -> VersionState:
        now = self._clock()
        with self._unit_of_work() as uow:
            version = _locked(uow, rule_version_id)
            RULE_VERSION_TRANSITIONS.assert_transition(version.status, RuleVersionStatus.APPROVED)
            if version.submitted_at is None:
                raise InvariantViolationError(
                    f"rule version {rule_version_id} has no review round: return it to draft "
                    "and submit it again"
                )
            earlier = uow.rule_versions.approvers(rule_version_id, version.submitted_at)
            if actor_id in earlier:
                raise DuplicateApproverError(
                    f"{actor_id} already approved rule version {rule_version_id} in this round"
                )
            approvers = earlier | {actor_id}
            after = version
            if len(approvers) >= required_approvals(version.high_impact):
                after = replace(
                    version, status=RuleVersionStatus.APPROVED, seed_status=SeedStatus.REVIEWED
                )
                uow.rule_versions.save_lifecycle(after)
            uow.rule_versions.record_decision(
                _decision(
                    version,
                    DecisionAction.APPROVED,
                    after.status,
                    now,
                    actor_id=actor_id,
                    note=note,
                )
            )
        return VersionState(after, tuple(sorted(approvers, key=str)))


class PublishVersion:
    """Publish an approved version, apply its relations and write the events."""

    def __init__(
        self,
        unit_of_work: KnowledgeUnitOfWorkFactory,
        *,
        enabled: bool,
        clock: Clock = default_clock,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._enabled = enabled
        self._clock = clock

    def run(
        self, rule_version_id: RuleVersionId, *, actor_id: UserId, note: str = ""
    ) -> Publication:
        if not self._enabled:
            raise PublishingDisabledError()
        now = self._clock()
        with self._unit_of_work() as uow:
            uow.rule_versions.lock_publication()
            version = _locked(uow, rule_version_id)
            relations = _own_relations(uow, rule_version_id)
            replaced = [
                r.to_rule_version_id
                for r in relations
                if r.relation in REPLACING and r.to_rule_version_id is not None
            ]
            changed = [
                r.to_rule_version_id
                for r in relations
                if r.relation is RelationKind.EXTENDS_DEADLINE and r.to_rule_version_id is not None
            ]
            plan = plan_publication(
                version,
                relations=relations,
                targets=uow.rule_versions.lock_many([*replaced, *changed]),
                replaced_elsewhere=uow.rule_versions.replaced_by_others(
                    replaced, excluding=rule_version_id
                ),
                siblings=uow.rule_versions.of_rule(version.rule_id),
                approvers=frozenset()
                if version.submitted_at is None
                else uow.rule_versions.approvers(rule_version_id, version.submitted_at),
                citations=uow.citations.for_version(rule_version_id),
                today=today_in_india(now),
                published_at=now,
            )
            uow.rule_versions.save_lifecycle(plan.published)
            uow.rule_versions.record_decision(
                _decision(
                    version,
                    DecisionAction.PUBLISHED,
                    plan.published.status,
                    now,
                    actor_id=actor_id,
                    note=note,
                )
            )
            for replacement in plan.replacements:
                uow.rule_versions.save_lifecycle(replacement.updated)
                if replacement.due:
                    uow.rule_versions.record_decision(
                        _decision(
                            replacement.target,
                            DecisionAction(replacement.moves_to.value),
                            replacement.moves_to,
                            now,
                            caused_by=rule_version_id,
                        )
                    )
            correlation_id = CorrelationId.new()
            events = plan.events(correlation_id=correlation_id, occurred_at=now)
            for event in events:
                uow.events.publish(event)
        return Publication(plan=plan, events=events, correlation_id=correlation_id)


class WithdrawVersion:
    """Withdraw a published version directly: ``rule.withdrawn`` with no withdrawing version,
    effective today. A version that another one replaces is withdrawn by publishing that one
    with a ``withdraws`` relation instead. A version whose own replacements have not taken
    effect yet is refused (``check_withdrawal``)."""

    def __init__(
        self,
        unit_of_work: KnowledgeUnitOfWorkFactory,
        *,
        enabled: bool,
        clock: Clock = default_clock,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._enabled = enabled
        self._clock = clock

    def run(
        self, rule_version_id: RuleVersionId, *, actor_id: UserId, note: str = ""
    ) -> VersionState:
        if not self._enabled:
            raise PublishingDisabledError()
        now = self._clock()
        with self._unit_of_work() as uow:
            uow.rule_versions.lock_publication()
            version = _locked(uow, rule_version_id)
            RULE_VERSION_TRANSITIONS.assert_transition(version.status, RuleVersionStatus.WITHDRAWN)
            relations = _own_relations(uow, rule_version_id)
            check_withdrawal(
                version,
                relations,
                uow.rule_versions.lock_many(
                    [
                        r.to_rule_version_id
                        for r in relations
                        if r.relation in REPLACING and r.to_rule_version_id is not None
                    ]
                ),
            )
            withdrawn = replace(version, status=RuleVersionStatus.WITHDRAWN)
            uow.rule_versions.save_lifecycle(withdrawn)
            uow.rule_versions.record_decision(
                _decision(
                    version,
                    DecisionAction.WITHDRAWN,
                    withdrawn.status,
                    now,
                    actor_id=actor_id,
                    note=note,
                )
            )
            event = transition_event(
                version.rule_id,
                version.rule_version_id,
                RuleVersionStatus.WITHDRAWN,
                by=None,
                effective_from=today_in_india(now),
                correlation_id=CorrelationId.new(),
                causation_id=None,
                occurred_at=now,
            )
            uow.events.publish(event)
        return VersionState(withdrawn, events=(event,))


class ApplyDueTransitions:
    """The daily sweep: every published version whose replacement has taken effect by ``as_of``
    (today in India by default) moves to superseded or withdrawn, with its event. Running it
    twice moves nothing twice. It never runs ahead of today."""

    def __init__(
        self,
        unit_of_work: KnowledgeUnitOfWorkFactory,
        *,
        enabled: bool,
        clock: Clock = default_clock,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._enabled = enabled
        self._clock = clock

    def run(self, as_of: date | None = None) -> SweepReport:
        if not self._enabled:
            raise PublishingDisabledError()
        now = self._clock()
        today = today_in_india(now)
        day = today if as_of is None else as_of
        if day > today:
            raise InvariantViolationError(f"as_of {day} is after today ({today}) in India")
        applied: list[PendingReplacement] = []
        events: list[RuleEvent] = []
        correlation_id = CorrelationId.new()
        with self._unit_of_work() as uow:
            uow.rule_versions.lock_publication()
            due = plan_due_transitions(uow.rule_versions.pending_replacements(day), day)
            targets = uow.rule_versions.lock_many([transition.target_id for transition in due])
            for transition in due:
                target = targets.get(transition.target_id)
                if target is None or target.status is not RuleVersionStatus.PUBLISHED:
                    continue
                uow.rule_versions.save_lifecycle(replace(target, status=transition.moves_to))
                uow.rule_versions.record_decision(
                    _decision(
                        target,
                        DecisionAction(transition.moves_to.value),
                        transition.moves_to,
                        now,
                        caused_by=transition.replacing_id,
                    )
                )
                event = transition_event(
                    transition.target_rule_id,
                    transition.target_id,
                    transition.moves_to,
                    by=transition.replacing_id,
                    effective_from=transition.replacing_from,
                    correlation_id=correlation_id,
                    causation_id=None,
                    occurred_at=now,
                )
                uow.events.publish(event)
                applied.append(transition)
                events.append(event)
        return SweepReport(as_of=day, transitions=tuple(applied), events=tuple(events))
