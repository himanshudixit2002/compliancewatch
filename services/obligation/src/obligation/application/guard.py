"""The guard in front of materialisation: what the cache and the rulebook together say of a rule
version before any obligation of it is made.

An applicability decision, or the rolling window, can still reach a version after the rulebook
has withdrawn or superseded it: a fan-out batch in flight, a consumer behind on its topic, or a
read the reader kept from a minute ago. ``admit(uow, fetched)`` merges the version as the reader
fetched it into the ``rule_version_ref`` cache (filling it when the version is missing) and judges
what the cache holds after that merge. The cache only ever moves a version forward, and the rule
events consumer writes into it what each rule event says, so either view that knows the version
has ended wins:

- withdrawn: nothing is made (``Refusal.RULE_WITHDRAWN``);
- no verified citation: nothing is made (``Refusal.UNCITED``), since every obligation shows the
  clause it comes from;
- superseded, or cut short by a published replacement: only the periods it still governs are
  made (``MaterialiseRequest.ref``); the others are refused as ``Refusal.RULE_SUPERSEDED``.

``merge`` keeps the version's cache row locked until the transaction ends, so a decision and a
rule event about the same version run one after the other: a withdrawal waits for the decision
being applied and then closes what it made, and a decision applied after the withdrawal sees it.
"""

from dataclasses import dataclass

from obligation.domain.repository import UnitOfWork
from obligation.domain.rule_versions import Refusal, RuleVersionRef, refusal


@dataclass(frozen=True, slots=True)
class Admission:
    """What the cache holds of the version after the merge, why nothing of it may be made (None
    when some may), and whether this unit cached it first."""

    ref: RuleVersionRef
    refusal: Refusal | None
    filled: bool


def admit(uow: UnitOfWork, fetched: RuleVersionRef) -> Admission:
    cached = uow.rule_versions.get(fetched.rule_version_id, lock=True)
    ref = uow.rule_versions.merge(fetched)
    return Admission(ref, refusal(ref), filled=cached is None)
