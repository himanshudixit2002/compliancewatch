"""Relation candidates: stage what the pipeline proposed, list them, approve or reject one.

Staging aligns each candidate's target the same way mentions are aligned; an unaligned target
stays a name and the candidate carries the issue ``target_unaligned`` until the entity review
for that name is decided. Nothing the pipeline sent is dropped: proposals it could not turn into
candidates are kept verbatim in the run's issues.

Approval needs the rule version the relation starts from, still before publication, and for a
relation that must target a rule version the version it targets. It writes one ``rule_relation``
row pointing back at the candidate; a supersession that would close a cycle is refused.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from domain_kernel.ids import CanonicalEntityId, DocumentId, RuleVersionId
from domain_kernel.knowledge import EntityType, RelationKind
from rulebook.application.alignment import Clock, default_clock
from rulebook.domain.alignment import Resolved, resolve
from rulebook.domain.errors import (
    CandidateClosedError,
    CandidateNotFoundError,
    RuleVersionNotEditableError,
    SupersessionCycleError,
    UnknownClauseError,
    UnknownDocumentError,
    UnknownRuleVersionError,
)
from rulebook.domain.ids import candidate_id_for, rule_relation_id_for, run_id_for
from rulebook.domain.relations import (
    EDITABLE_FROM_STATUSES,
    CandidateIssue,
    CandidateRejectReason,
    CandidateStatus,
    RelationCandidate,
    find_supersedes_cycle,
    to_rule_relation,
)
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory
from rulebook.domain.runs import ExtractionRun, RuleSummary

MAX_PAGE = 200


@dataclass(frozen=True, slots=True)
class SubmittedCandidate:
    relation: RelationKind
    target_type: EntityType
    target_name: str
    target_clause_ref: str
    target_span_start: int
    target_span_end: int
    evidence_clause_ref: str
    evidence_quote: str
    quote_score: float
    confidence: float
    needs_review: bool
    rule_key: str | None = None
    period_label: str | None = None
    new_due_on: date | None = None
    issues: tuple[CandidateIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class RelationSubmission:
    extractor: str
    model: str
    outcome: str
    candidates: tuple[SubmittedCandidate, ...] = ()
    run_issues: tuple[Mapping[str, str], ...] = field(default=())


@dataclass(frozen=True, slots=True)
class StagingReport:
    created: int
    unchanged: int
    candidate_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class Approval:
    candidate_id: UUID
    rule_relation_id: UUID


class StageRelationCandidates:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, document_id: DocumentId, submission: RelationSubmission) -> StagingReport:
        created = unchanged = 0
        ids: list[UUID] = []
        with self._unit_of_work() as uow:
            if uow.documents.get(document_id) is None:
                raise UnknownDocumentError(str(document_id))
            clauses = {c.clause_ref: c for c in uow.documents.clauses(document_id)}
            for submitted in submission.candidates:
                target_clause = clauses.get(submitted.target_clause_ref)
                evidence_clause = clauses.get(submitted.evidence_clause_ref)
                if target_clause is None or evidence_clause is None:
                    raise UnknownClauseError(
                        f"{submitted.target_clause_ref} or {submitted.evidence_clause_ref} is "
                        f"not a clause of document {document_id}"
                    )
                issues = list(submitted.issues)
                entity_id = uow.mentions.entity_at(
                    target_clause.clause_id, submitted.target_span_start, submitted.target_type
                )
                if entity_id is None:
                    outcome = resolve(submitted.target_type, submitted.target_name, uow.entities)
                    if isinstance(outcome, Resolved):
                        entity_id = outcome.entity_id
                    else:
                        issues.append(CandidateIssue("target_unaligned", outcome.reason.value))
                rule_key, rule_id = submitted.rule_key, None
                if rule_key is not None:
                    rule_id = uow.rules.rule_id(rule_key)
                    if rule_id is None:
                        issues.append(CandidateIssue("rule_key_unknown", rule_key))
                        rule_key = None
                candidate = RelationCandidate(
                    candidate_id=candidate_id_for(
                        document_id,
                        submitted.relation,
                        submitted.target_type,
                        submitted.target_name,
                        evidence_clause.clause_id,
                    ),
                    document_id=document_id,
                    relation=submitted.relation,
                    target_type=submitted.target_type,
                    target_name=submitted.target_name,
                    target_clause_id=target_clause.clause_id,
                    target_span_start=submitted.target_span_start,
                    target_span_end=submitted.target_span_end,
                    target_entity_id=entity_id,
                    target_rule_key=rule_key,
                    target_rule_id=rule_id,
                    evidence_clause_id=evidence_clause.clause_id,
                    evidence_quote=submitted.evidence_quote,
                    quote_score=submitted.quote_score,
                    period_label=submitted.period_label,
                    new_due_on=submitted.new_due_on,
                    prompt_version=submission.extractor,
                    model=submission.model,
                    confidence=submitted.confidence,
                    issues=tuple(issues),
                    needs_review=submitted.needs_review or bool(issues),
                )
                added = uow.candidates.add(candidate)
                created, unchanged = created + added, unchanged + (not added)
                ids.append(candidate.candidate_id)
            uow.runs.record(
                ExtractionRun(
                    run_id=run_id_for(document_id, "relations", submission.extractor),
                    document_id=document_id,
                    stage="relations",
                    extractor=submission.extractor,
                    model=submission.model,
                    outcome=submission.outcome,
                    counts={"created": created, "unchanged": unchanged},
                    issues=submission.run_issues,
                )
            )
        return StagingReport(created=created, unchanged=unchanged, candidate_ids=tuple(ids))


class ListRelationCandidates:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        status: CandidateStatus | None = CandidateStatus.OPEN,
        document_id: DocumentId | None = None,
        limit: int = 50,
        after: UUID | None = None,
    ) -> Sequence[RelationCandidate]:
        with self._unit_of_work() as uow:
            return uow.candidates.page(status, document_id, min(max(limit, 1), MAX_PAGE), after)


class ApproveRelationCandidate:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        candidate_id: UUID,
        from_rule_version_id: RuleVersionId,
        target_rule_version_id: RuleVersionId | None,
        *,
        decided_by: str,
        note: str = "",
    ) -> Approval:
        now = self._clock()
        with self._unit_of_work() as uow:
            candidate = uow.candidates.lock(candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(f"relation candidate {candidate_id} does not exist")
            if candidate.status is not CandidateStatus.OPEN:
                raise CandidateClosedError(f"candidate {candidate_id} is {candidate.status.value}")
            status = uow.rules.version_status(from_rule_version_id)
            if status is None:
                raise UnknownRuleVersionError(str(from_rule_version_id))
            if status not in EDITABLE_FROM_STATUSES:
                raise RuleVersionNotEditableError(
                    f"rule version {from_rule_version_id} is {status.value}"
                )
            if (
                target_rule_version_id is not None
                and uow.rules.version_status(target_rule_version_id) is None
            ):
                raise UnknownRuleVersionError(str(target_rule_version_id))
            target_entity = None
            if target_rule_version_id is None:
                target_entity = self._target_entity(uow, candidate)
            relation = to_rule_relation(
                candidate, from_rule_version_id, target_rule_version_id, target_entity
            )
            if relation.relation is RelationKind.SUPERSEDES and target_rule_version_id:
                uow.relations.lock_supersession()
                cycle = find_supersedes_cycle(
                    uow.relations.supersedes_edges(), from_rule_version_id, target_rule_version_id
                )
                if cycle is not None:
                    raise SupersessionCycleError(
                        " -> ".join(str(version) for version in cycle)
                        + f" -> {target_rule_version_id}"
                    )
            relation_id = rule_relation_id_for(
                from_rule_version_id.value,
                relation.relation,
                relation.to_kind,
                relation.to_ref,
                candidate.evidence_clause_id,
            )
            uow.relations.add(relation, relation_id=relation_id, candidate_id=candidate_id)
            uow.candidates.save(candidate.approve(decided_by=decided_by, at=now, note=note))
        return Approval(candidate_id=candidate_id, rule_relation_id=relation_id)

    @staticmethod
    def _target_entity(
        uow: KnowledgeUnitOfWork, candidate: RelationCandidate
    ) -> tuple[CanonicalEntityId, str] | None:
        """The entity the candidate's target is now aligned to, with its canonical name: the
        one staging found, else the one recorded for the target mention since, else the one its
        name resolves to now. ``None`` while the target is not aligned."""
        entity_id = candidate.target_entity_id or uow.mentions.entity_at(
            candidate.target_clause_id, candidate.target_span_start, candidate.target_type
        )
        if entity_id is None:
            outcome = resolve(candidate.target_type, candidate.target_name, uow.entities)
            entity_id = outcome.entity_id if isinstance(outcome, Resolved) else None
        if entity_id is None:
            return None
        found = uow.entities.get(entity_id)
        return None if found is None else (entity_id, found[1])


class RejectRelationCandidate:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        candidate_id: UUID,
        reason: CandidateRejectReason,
        *,
        decided_by: str,
        note: str = "",
    ) -> RelationCandidate:
        now = self._clock()
        with self._unit_of_work() as uow:
            candidate = uow.candidates.lock(candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(f"relation candidate {candidate_id} does not exist")
            if candidate.status is not CandidateStatus.OPEN:
                raise CandidateClosedError(f"candidate {candidate_id} is {candidate.status.value}")
            rejected = candidate.reject(reason, decided_by=decided_by, at=now, note=note)
            uow.candidates.save(rejected)
        return rejected


class ListRules:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self) -> tuple[RuleSummary, ...]:
        with self._unit_of_work() as uow:
            return uow.rules.list_rules()
