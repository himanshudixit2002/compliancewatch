"""Read model of a published rule version. The Rule aggregate stays in the rulebook service."""

from dataclasses import dataclass
from datetime import date

from domain_kernel._validation import require_instance, require_int, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import RuleId, RuleVersionId
from domain_kernel.periods import EffectivePeriod
from domain_kernel.predicates import Specification


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


@dataclass(frozen=True, slots=True)
class RuleVersionSnapshot:
    """A rule version as the applicability engine reads it."""

    rule_id: RuleId
    rule_version_id: RuleVersionId
    version: int
    regulator: str
    title: str
    specification: Specification
    effective: EffectivePeriod
    obligation_template: ObligationTemplate

    def __post_init__(self) -> None:
        require_instance(self.rule_id, RuleId, "rule_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        require_int(self.version, "version", minimum=1)
        require_text(self.regulator, "regulator")
        require_text(self.title, "title")
        _require_specification(self.specification)
        require_instance(self.effective, EffectivePeriod, "effective")
        require_instance(self.obligation_template, ObligationTemplate, "obligation_template")

    def is_effective_on(self, as_of: date) -> bool:
        return self.effective.contains(as_of)


def _require_specification(value: object) -> None:
    if not isinstance(value, Specification):
        raise InvariantViolationError(
            f"specification must be a Specification, got {value.__class__.__name__}"
        )
