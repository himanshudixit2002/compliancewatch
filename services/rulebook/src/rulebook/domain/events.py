"""Events the rulebook publishes; payload fields follow packages/contracts/events.

Rule events are regulatory: they carry no tenant, and the outbox keys them by rule so a
consumer sees one rule's events in order. The events of one publication share a correlation id,
and the ones that follow from it (a replaced version moving, a deadline change) name the
``rule.published`` event as their cause.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import ClassVar

from domain_kernel._validation import require_date, require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import ClauseId, RuleId, RuleVersionId, UserId
from domain_kernel.ontology import ATTRIBUTE_KEY_PATTERN


class DeadlineChangeReason(StrEnum):
    DEADLINE_EXTENDED = "deadline_extended"
    CORRECTED = "corrected"


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleEvent(DomainEvent):
    """Base of the rule events: the rule they are about, which is also their partition key."""

    rule_id: RuleId

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.tenant_id is not None:
            raise InvariantViolationError(f"{type(self).topic} is regulatory: no tenant")
        require_instance(self.rule_id, RuleId, "rule_id")

    @property
    def partition_key(self) -> str:
        return str(self.rule_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class RulePublished(RuleEvent):
    topic: ClassVar[str] = "rule.published"
    schema_version: ClassVar[str] = "1.0.0"

    rule_version_id: RuleVersionId
    version: int
    regulator: str
    title: str
    summary: str
    effective_from: date
    effective_to: date | None
    supersedes: tuple[RuleVersionId, ...]
    approved_by: tuple[UserId, ...]
    high_impact: bool
    attribute_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        RuleEvent.__post_init__(self)
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_int(self.version, "version", minimum=1)
        require_text(self.regulator, "regulator")
        require_text(self.title, "title")
        require_instance(self.summary, str, "summary")
        require_date(self.effective_from, "effective_from")
        if self.effective_to is not None:
            require_date(self.effective_to, "effective_to")
        for superseded in require_instance(self.supersedes, tuple, "supersedes"):
            require_instance(superseded, RuleVersionId, "supersedes[]")
        if len(set(self.supersedes)) != len(self.supersedes):
            raise InvariantViolationError("supersedes lists each version once")
        approvers = require_instance(self.approved_by, tuple, "approved_by")
        for approver in approvers:
            require_instance(approver, UserId, "approved_by[]")
        if not approvers or len(set(approvers)) != len(approvers):
            raise InvariantViolationError("approved_by lists at least one approver, each once")
        require_instance(self.high_impact, bool, "high_impact")
        keys = require_instance(self.attribute_keys, tuple, "attribute_keys")
        for key in keys:
            if not ATTRIBUTE_KEY_PATTERN.fullmatch(require_text(key, "attribute_keys[]")):
                raise InvariantViolationError(f"attribute key {key!r} is not snake_case")
        if len(set(keys)) != len(keys):
            raise InvariantViolationError("attribute_keys lists each key once")


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleSuperseded(RuleEvent):
    topic: ClassVar[str] = "rule.superseded"
    schema_version: ClassVar[str] = "1.0.0"

    rule_version_id: RuleVersionId
    superseded_by_rule_version_id: RuleVersionId
    effective_from: date

    def __post_init__(self) -> None:
        RuleEvent.__post_init__(self)
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(
            self.superseded_by_rule_version_id, RuleVersionId, "superseded_by_rule_version_id"
        )
        require_date(self.effective_from, "effective_from")


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleWithdrawn(RuleEvent):
    """``withdrawn_by_rule_version_id`` is the version whose ``withdraws`` relation took effect,
    or ``None`` when an analyst withdrew the version directly."""

    topic: ClassVar[str] = "rule.withdrawn"
    schema_version: ClassVar[str] = "1.0.0"

    rule_version_id: RuleVersionId
    withdrawn_by_rule_version_id: RuleVersionId | None
    effective_from: date

    def __post_init__(self) -> None:
        RuleEvent.__post_init__(self)
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        if self.withdrawn_by_rule_version_id is not None:
            require_instance(
                self.withdrawn_by_rule_version_id, RuleVersionId, "withdrawn_by_rule_version_id"
            )
        require_date(self.effective_from, "effective_from")


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleDeadlineChanged(RuleEvent):
    """The due date of ``rule_version_id`` (Y) moves because ``caused_by_rule_version_id`` (X)
    was published; ``period_label`` names the period of a recurring Y."""

    topic: ClassVar[str] = "rule.deadline_changed"
    schema_version: ClassVar[str] = "1.0.0"

    rule_version_id: RuleVersionId
    caused_by_rule_version_id: RuleVersionId
    period_label: str | None
    new_due_on: date
    reason: DeadlineChangeReason
    evidence_clause_id: ClauseId

    def __post_init__(self) -> None:
        RuleEvent.__post_init__(self)
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_instance(self.caused_by_rule_version_id, RuleVersionId, "caused_by_rule_version_id")
        if self.period_label is not None:
            require_text(self.period_label, "period_label")
        require_date(self.new_due_on, "new_due_on")
        require_instance(self.reason, DeadlineChangeReason, "reason")
        require_instance(self.evidence_clause_id, ClauseId, "evidence_clause_id")
