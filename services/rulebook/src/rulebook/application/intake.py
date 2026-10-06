"""The rule candidate intake: each rule.candidate.created the pipeline publishes becomes one
stored candidate and one review task of kind ``candidate``, in one transaction.

``IngestRuleCandidate.run(payload, event_id)`` is what the rulebook worker's consumer of group
``rulebook.rule-candidates`` calls for every message (``rulebook.worker``), in the transaction
that also records the event as processed:

- the payload is read as ``CandidateIntake.from_payload`` reads it; one the contract refuses is
  ``CandidatePayloadInvalidError``, which the consumer retries and then dead-letters;
- a candidate id stored already changes nothing, whatever event carried it, so a redelivery or a
  replay opens no second task;
- the candidate's document must be stored (the pipeline registers a document before it extracts
  from it): an unknown one is ``UnknownDocumentError``, which the consumer retries and then
  dead-letters, and a replay of the dead letter succeeds once the document is registered;
- the suggested rule key is the payload's when a rule has that key, else the one rule key the
  document's relation candidates name when they name exactly one (staging checked those against
  the rulebook; a candidate an analyst rejected is left out), else the payload's as a proposal
  for a new rule; the pipeline's key is a ``<form>_<cadence>`` heuristic, never a lookup;
- the task is queued under the candidate's regulator in lower case, at the candidate's priority
  (``CandidateIntake.priority``).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from rulebook.application.alignment import Clock, default_clock
from rulebook.domain.errors import UnknownDocumentError
from rulebook.domain.intake import CandidateIntake, RuleCandidate
from rulebook.domain.relations import CandidateStatus
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory
from rulebook.domain.review_tasks import ReviewTask

RELATION_PAGE = 200


@dataclass(frozen=True, slots=True)
class Intake:
    """What one event did: the candidate as stored, the task it opened, and whether this call
    stored them (False for a candidate stored before)."""

    candidate: RuleCandidate
    task: ReviewTask | None
    created: bool


class IngestRuleCandidate:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory, clock: Clock = default_clock):
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, payload: Mapping[str, object], event_id: UUID) -> Intake:
        intake = CandidateIntake.from_payload(payload)
        now = self._clock()
        with self._unit_of_work() as uow:
            stored = uow.rule_candidates.get(intake.candidate_id)
            if stored is not None:
                return Intake(stored, None, created=False)
            if uow.documents.get(intake.document_id) is None:
                raise UnknownDocumentError(str(intake.document_id))
            candidate = RuleCandidate.received(
                intake, event_id=event_id, at=now, suggested_rule_key=suggestion(uow, intake)
            )
            if not uow.rule_candidates.add(candidate):  # pragma: no cover - a concurrent intake
                found = uow.rule_candidates.get(intake.candidate_id)
                return Intake(found or candidate, None, created=False)
            task = ReviewTask.for_candidate(
                candidate.candidate_id,
                regulator=candidate.regulator,
                priority=intake.priority(),
                at=now,
            )
            uow.review_tasks.add(task)
            return Intake(candidate, task, created=True)


def suggestion(uow: KnowledgeUnitOfWork, intake: CandidateIntake) -> str | None:
    """The rule key to suggest for the candidate: the payload's when a rule has it, else the
    single rule key the document's relation candidates name (a rejected one left out), else the
    payload's (a key for a new rule), else none."""
    proposed = intake.suggested_rule_key
    if proposed is not None and uow.rules.rule_id(proposed) is not None:
        return proposed
    named = relation_rule_keys(uow, intake)
    if len(named) == 1:
        return next(iter(named))
    return proposed


def relation_rule_keys(uow: KnowledgeUnitOfWork, intake: CandidateIntake) -> frozenset[str]:
    """The distinct rule keys the document's relation candidates name, open or approved: an
    analyst rejected the others, often for naming the wrong target."""
    keys: set[str] = set()
    after: UUID | None = None
    while True:
        page = uow.candidates.page(None, intake.document_id, RELATION_PAGE, after)
        keys.update(
            c.target_rule_key
            for c in page
            if c.target_rule_key is not None and c.status is not CandidateStatus.REJECTED
        )
        if len(page) < RELATION_PAGE:
            return frozenset(keys)
        after = page[-1].candidate_id
