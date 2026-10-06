"""Read model of a published rule version. The Rule aggregate stays in the rulebook service."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Self

from domain_kernel._validation import (
    require_date,
    require_instance,
    require_int,
    require_mapping,
    require_text,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import RuleId, RuleVersionId
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Specification
from domain_kernel.recurrence import Recurrence


def one_off_due_on(as_of: date, due_in_days: int | None) -> date | None:
    """The due day of a one-off duty decided on ``as_of``: ``due_in_days`` later, or None when
    it has no due date."""
    require_date(as_of, "as_of")
    if due_in_days is None:
        return None
    return as_of + timedelta(days=require_int(due_in_days, "due_in_days", minimum=0))


@dataclass(frozen=True, slots=True)
class ObligationTemplate:
    """What a business has to do when the rule applies."""

    title: str
    steps: tuple[str, ...] = ()
    due_in_days: int | None = None
    evidence_type: str = ""

    def __post_init__(self) -> None:
        require_text(self.title, "title")
        for index, step in enumerate(require_instance(self.steps, tuple, "steps")):
            require_text(step, f"steps[{index}]")
        if self.due_in_days is not None:
            require_int(self.due_in_days, "due_in_days", minimum=0)
        require_instance(self.evidence_type, str, "evidence_type")

    def due_on(self, as_of: date) -> date | None:
        """The due day of the one-off obligation a decision made on ``as_of`` implies:
        ``due_in_days`` later, or None (undated) when the template sets none. The obligation
        belongs to the rule version in force on that day."""
        return one_off_due_on(as_of, self.due_in_days)

    def to_mapping(self) -> dict[str, object]:
        """JSON-ready form, the inverse of ``from_mapping``."""
        return {
            "title": self.title,
            "steps": list(self.steps),
            "due_in_days": self.due_in_days,
            "evidence_type": self.evidence_type,
        }

    @classmethod
    def from_mapping(cls, data: object) -> Self:
        mapping = require_mapping(data, "obligation_template")
        unknown = set(mapping) - {"title", "steps", "due_in_days", "evidence_type"}
        if unknown:
            raise InvariantViolationError(f"obligation_template has unknown keys {sorted(unknown)}")
        steps = mapping.get("steps", ())
        if isinstance(steps, str) or not isinstance(steps, Sequence):
            raise InvariantViolationError("obligation_template.steps must be a list")
        due_in_days = mapping.get("due_in_days")
        return cls(
            title=require_text(mapping.get("title"), "obligation_template.title"),
            steps=tuple(require_text(step, "obligation_template.steps[]") for step in steps),
            due_in_days=None
            if due_in_days is None
            else require_int(due_in_days, "obligation_template.due_in_days", minimum=0),
            evidence_type=require_instance(
                mapping.get("evidence_type", ""), str, "obligation_template.evidence_type"
            ),
        )


@dataclass(frozen=True, slots=True)
class RuleVersionSnapshot:
    """A rule version as the applicability engine reads it.

    ``recurrence`` is set for a duty that repeats (a monthly return); the obligation service
    then materialises one obligation per period. A one-off duty leaves it ``None`` and uses the
    template's ``due_in_days``.
    """

    rule_id: RuleId
    rule_version_id: RuleVersionId
    version: int
    regulator: str
    title: str
    specification: Specification
    effective: EffectivePeriod
    obligation_template: ObligationTemplate
    recurrence: Recurrence | None = None

    def __post_init__(self) -> None:
        require_instance(self.rule_id, RuleId, "rule_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_int(self.version, "version", minimum=1)
        require_text(self.regulator, "regulator")
        require_text(self.title, "title")
        _require_specification(self.specification)
        require_instance(self.effective, EffectivePeriod, "effective")
        require_instance(self.obligation_template, ObligationTemplate, "obligation_template")
        if self.recurrence is not None:
            require_instance(self.recurrence, Recurrence, "recurrence")

    def is_effective_on(self, as_of: date) -> bool:
        return self.effective.contains(as_of)


def _require_specification(value: object) -> None:
    if not isinstance(value, Specification):
        raise InvariantViolationError(
            f"specification must be a Specification, got {value.__class__.__name__}"
        )
