"""The changes feed: the published changes newest first, each with what a reader shows of its
version (``rulebook.domain.changes``).

``ListChanges`` reads one page in one transaction: the changes the decision log records, then for
each version they are about its record, the approvers of the round it was published from, its
verified citations and its relations to the versions publication acts on. A version two changes
of the page are about is read once. The feed is the same for every tenant.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from domain_kernel.ids import RuleVersionId, UserId
from rulebook.domain.changes import (
    MAX_CHANGES,
    Change,
    ChangeQuery,
    change_relations,
)
from rulebook.domain.errors import UnknownRuleVersionError
from rulebook.domain.graph import RelationQuery, RelationRecord
from rulebook.domain.repository import KnowledgeUnitOfWork, KnowledgeUnitOfWorkFactory
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord

MAX_RELATIONS = 1_000


@dataclass(frozen=True, slots=True)
class _Facts:
    version: RuleVersionRecord
    approved_by: tuple[UserId, ...]
    citations: tuple[CitationRecord, ...]
    relations: tuple[RelationRecord, ...]


class ListChanges:
    """One page of the feed: at most ``MAX_CHANGES``, and one more when the query asks for it to
    tell that another page follows."""

    def __init__(self, unit_of_work: KnowledgeUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, query: ChangeQuery) -> Sequence[Change]:
        limited = ChangeQuery(
            limit=min(query.limit, MAX_CHANGES + 1),
            since=query.since,
            regulator=query.regulator,
            after=query.after,
        )
        with self._unit_of_work() as uow:
            entries = uow.rule_versions.changes(limited)
            known: dict[RuleVersionId, _Facts] = {}
            changes: list[Change] = []
            for entry in entries:
                facts = known.get(entry.rule_version_id)
                if facts is None:
                    facts = known[entry.rule_version_id] = _facts_of(uow, entry.rule_version_id)
                changes.append(
                    Change(
                        entry=entry,
                        version=facts.version,
                        approved_by=facts.approved_by,
                        citations=facts.citations,
                        relations=facts.relations,
                    )
                )
            return changes


def _facts_of(uow: KnowledgeUnitOfWork, rule_version_id: RuleVersionId) -> _Facts:
    record = uow.rule_versions.get(rule_version_id)
    if record is None:  # pragma: no cover - the decision log's foreign key keeps the version
        raise UnknownRuleVersionError(str(rule_version_id))
    approvers = (
        uow.rule_versions.approvers(rule_version_id, record.submitted_at)
        if record.published_at is not None and record.submitted_at is not None
        else frozenset()
    )
    citations = tuple(
        citation for citation in uow.citations.for_version(rule_version_id) if citation.verified
    )
    relations = uow.relations.find(
        RelationQuery(
            from_rule_version_id=rule_version_id, published_only=False, limit=MAX_RELATIONS
        )
    )
    return _Facts(
        version=record,
        approved_by=tuple(sorted(approvers, key=str)),
        citations=citations,
        relations=change_relations(relations),
    )
