"""Read rule versions: the ones in force on a date, every version of one rule in any status, one
version in any status with its citations (and, once published, its approvers), and the citations
alone.

The Q&A service answers from exactly what ``ListRulesInForce`` returns for the question's date,
so a draft, a version under review or a withdrawn one never reaches an answer.
``ListRuleVersions`` is the editorial view: the drafts the seed command writes and the versions
past them, which is how a workbench finds a version to cite and submit.
"""

from collections.abc import Sequence
from datetime import date

from domain_kernel.ids import RuleId, RuleVersionId
from rulebook.domain.errors import UnknownRuleError, UnknownRuleVersionError
from rulebook.domain.repository import KnowledgeUnitOfWorkFactory
from rulebook.domain.rule_versions import CitationRecord, RuleVersionDetail, RuleVersionRecord

MAX_VERSIONS = 500


class ListRulesInForce:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(
        self,
        as_of: date,
        *,
        rule_key: str | None = None,
        regulator: str | None = None,
        limit: int = 100,
        after: str | None = None,
    ) -> Sequence[RuleVersionRecord]:
        with self._unit_of_work() as uow:
            return uow.rule_versions.in_force(
                as_of,
                rule_key=rule_key,
                regulator=regulator,
                limit=min(max(limit, 1), MAX_VERSIONS),
                after=after,
            )


class ListRuleVersions:
    """Every version of the rule with ``rule_key``, by version number, in any status."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, rule_key: str) -> Sequence[RuleVersionRecord]:
        with self._unit_of_work() as uow:
            rule_id = uow.rules.rule_id(rule_key)
            if rule_id is None:
                raise UnknownRuleError(rule_key)
            return uow.rule_versions.of_rule(RuleId(rule_id))


class ReadRuleVersion:
    """One version in any status with its citations. A version that has been published also
    names the approvers of the round it was published from: the decision audit's approvals
    since its ``submitted_at``, which publication froze, so the answer does not depend on which
    event a reader saw first."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, rule_version_id: RuleVersionId) -> RuleVersionDetail:
        with self._unit_of_work() as uow:
            record = uow.rule_versions.get(rule_version_id)
            if record is None:
                raise UnknownRuleVersionError(str(rule_version_id))
            approvers = (
                uow.rule_versions.approvers(rule_version_id, record.submitted_at)
                if record.published_at is not None and record.submitted_at is not None
                else frozenset()
            )
            return RuleVersionDetail(
                record,
                uow.citations.for_version(rule_version_id),
                tuple(sorted(approvers, key=str)),
            )


class ListCitations:
    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, rule_version_id: RuleVersionId) -> tuple[CitationRecord, ...]:
        with self._unit_of_work() as uow:
            if uow.rule_versions.get(rule_version_id) is None:
                raise UnknownRuleVersionError(str(rule_version_id))
            return uow.citations.for_version(rule_version_id)
