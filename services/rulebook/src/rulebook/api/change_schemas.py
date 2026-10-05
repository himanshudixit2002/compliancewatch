"""Response bodies and the page parameters of the changes feed (``GET /v1/changes``).

The names start with ``RuleChange`` or name the deadline: the public API merges every service's
components into one spec, where ``ChangeOut``, ``ChangeKind`` and ``CitationOut`` are already the
obligation service's (``rulebook.domain.changes.RuleChangeKind`` is named so for the same reason).
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Final, Self
from uuid import UUID

from fastapi import Query
from pydantic import AwareDatetime, BaseModel, Field

from domain_kernel.knowledge import RelationKind
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus
from py_common.pagination import MAX_CURSOR_CHARS, decode_cursor
from rulebook.domain.changes import MAX_CHANGES, Change, ChangeKey, RuleChangeKind
from rulebook.domain.graph import RelationRecord
from rulebook.domain.rule_versions import CitationRecord
from rulebook.domain.seed import SeedStatus

DEFAULT_CHANGES: Final = 50


class RuleChangeCitationOut(BaseModel):
    """A verified quote of the clause the version cites."""

    clause_id: UUID
    document_id: UUID
    clause_ref: str = Field(description="The clause's reference in its document, such as en.p3")
    quote: str

    @classmethod
    def from_record(cls, citation: CitationRecord) -> Self:
        return cls(
            clause_id=citation.clause_id.value,
            document_id=citation.document_id.value,
            clause_ref=citation.clause_ref,
            quote=citation.quote,
        )


class DeadlineExtensionOut(BaseModel):
    """A due date the version moves: the version whose date moves, the period (null when that
    version does not recur) and the new due date."""

    rule_version_id: UUID
    period_label: str | None
    new_due_on: date | None


class RuleChangeRelationsOut(BaseModel):
    """The versions the version acts on when it is published: those it supersedes, corrects or
    withdraws (each ends when it takes effect), and the due dates it moves."""

    supersedes: list[UUID]
    corrects: list[UUID]
    withdraws: list[UUID]
    extends_deadline: list[DeadlineExtensionOut]

    @classmethod
    def from_records(cls, relations: tuple[RelationRecord, ...]) -> Self:
        def targets(kind: RelationKind) -> list[UUID]:
            return [
                relation.to_rule_version_id.value
                for relation in relations
                if relation.relation is kind and relation.to_rule_version_id is not None
            ]

        return cls(
            supersedes=targets(RelationKind.SUPERSEDES),
            corrects=targets(RelationKind.CORRECTS),
            withdraws=targets(RelationKind.WITHDRAWS),
            extends_deadline=[
                DeadlineExtensionOut(
                    rule_version_id=relation.to_rule_version_id.value,
                    period_label=relation.period_label,
                    new_due_on=relation.new_due_on,
                )
                for relation in relations
                if relation.relation is RelationKind.EXTENDS_DEADLINE
                and relation.to_rule_version_id is not None
            ],
        )


class RuleDeadlineOut(BaseModel):
    """What a deadline change moved: the period (null when the version does not recur), the new
    due date and the clause that says so."""

    period_label: str | None
    new_due_on: date | None
    evidence_clause_id: UUID | None


class RuleChangeOut(BaseModel):
    """One published change. ``kind`` says what happened to the version ``rule_version_id``:
    ``published``, ``superseded`` or ``withdrawn``, or ``deadline_changed`` when a published
    version moved its due date (``deadline``). ``caused_by_rule_version_id`` is the version whose
    publication caused it, when one did. ``changed_at`` is when the change was published.

    The rest is the version as it stands: its rule, dates and status now; ``seed_status``
    needs_review while no analyst reviewed it (a synthetic approval reviews nothing), the cue for
    a not-yet-reviewed notice; ``approved_by`` the approvers of the round it was published from
    and ``published_at`` when (empty and null for a version never published); its verified
    citations; and the versions it acts on when published (``relations``)."""

    change_id: UUID
    kind: RuleChangeKind
    changed_at: datetime
    rule_version_id: UUID
    rule_key: str
    title: str
    summary: str
    version: int
    regulator: str
    level: AttributeLevel
    status: RuleVersionStatus
    effective_from: date
    effective_to: date | None = Field(description="Exclusive; null while open-ended")
    seed_status: SeedStatus
    approved_by: list[UUID]
    published_at: datetime | None
    citations: list[RuleChangeCitationOut]
    caused_by_rule_version_id: UUID | None
    deadline: RuleDeadlineOut | None
    relations: RuleChangeRelationsOut

    @classmethod
    def from_change(cls, change: Change) -> Self:
        entry, version = change.entry, change.version
        deadline = None
        if entry.kind is RuleChangeKind.DEADLINE_CHANGED:
            deadline = RuleDeadlineOut(
                period_label=entry.period_label,
                new_due_on=entry.new_due_on,
                evidence_clause_id=None
                if entry.evidence_clause_id is None
                else entry.evidence_clause_id.value,
            )
        return cls(
            change_id=entry.change_id,
            kind=entry.kind,
            changed_at=entry.changed_at,
            rule_version_id=version.rule_version_id.value,
            rule_key=version.rule_key,
            title=version.title,
            summary=version.summary,
            version=version.version,
            regulator=version.regulator,
            level=version.level,
            status=version.status,
            effective_from=version.effective_from,
            effective_to=version.effective_to,
            seed_status=version.seed_status,
            approved_by=[approver.value for approver in change.approved_by],
            published_at=version.published_at,
            citations=[RuleChangeCitationOut.from_record(c) for c in change.citations],
            caused_by_rule_version_id=None if entry.caused_by is None else entry.caused_by.value,
            deadline=deadline,
            relations=RuleChangeRelationsOut.from_records(change.relations),
        )


class RuleChangeCursor(BaseModel):
    """Where a page of the feed ends: the last change on it."""

    changed_at: AwareDatetime
    change_id: UUID

    def key(self) -> ChangeKey:
        return ChangeKey(self.changed_at, self.change_id)


@dataclass(frozen=True, slots=True)
class ChangePageParams:
    """``limit`` (1 to 100) and ``cursor``, as ``py_common.pagination`` reads them for its lists
    with a shorter longest page."""

    limit: Annotated[
        int, Query(ge=1, le=MAX_CHANGES, description=f"Changes per page, 1 to {MAX_CHANGES}")
    ] = DEFAULT_CHANGES
    cursor: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=MAX_CURSOR_CHARS,
            description="The next_cursor of the previous page; absent for the first page",
        ),
    ] = None

    def after(self, scope: str) -> ChangeKey | None:
        if self.cursor is None:
            return None
        return decode_cursor(self.cursor, scope, RuleChangeCursor).key()
