"""The seed calendar: hand-written rule versions that an analyst reviews before publication.

A seed rule is a draft ``RuleVersionSnapshot`` plus what a reviewer needs: the cited source,
the review status and the open questions. Nothing in a seed reaches a business until the
version is published through the review flow.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from domain_kernel._validation import require_date, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ontology import AttributeLevel
from domain_kernel.predicates import Specification, specification_to_mapping
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate

RULE_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
SEMVER_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class SeedStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"


@dataclass(frozen=True, slots=True)
class SeedSource:
    """The legal text the rule is taken from: the analyst checks the entry against it."""

    instrument: str
    reference: str
    note: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        require_text(self.instrument, "source.instrument")
        require_text(self.reference, "source.reference")
        require_instance(self.note, str, "source.note")
        require_instance(self.url, str, "source.url")

    def to_mapping(self) -> dict[str, str]:
        return {
            "instrument": self.instrument,
            "reference": self.reference,
            "note": self.note,
            "url": self.url,
        }


@dataclass(frozen=True, slots=True)
class SeedRule:
    rule_key: str
    title: str
    summary: str
    regulator: str
    level: AttributeLevel
    specification: Specification
    obligation_template: ObligationTemplate
    recurrence: Recurrence | None
    effective_from: date
    source: SeedSource
    seed_status: SeedStatus
    todo: tuple[str, ...]

    def __post_init__(self) -> None:
        key = require_text(self.rule_key, "rule_key")
        if not RULE_KEY_PATTERN.fullmatch(key):
            raise InvariantViolationError(f"rule_key {key!r} must be lowercase snake_case")
        require_text(self.title, "title")
        require_text(self.summary, "summary")
        require_text(self.regulator, "regulator")
        require_instance(self.level, AttributeLevel, "level")
        if not isinstance(self.specification, Specification):
            raise InvariantViolationError(
                f"specification must be a Specification, got "
                f"{self.specification.__class__.__name__}"
            )
        require_instance(self.obligation_template, ObligationTemplate, "obligation_template")
        if self.recurrence is not None:
            require_instance(self.recurrence, Recurrence, "recurrence")
        elif self.obligation_template.due_in_days is None:
            raise InvariantViolationError(
                f"{key}: a one-off rule needs obligation_template.due_in_days"
            )
        require_date(self.effective_from, "effective_from")
        require_instance(self.source, SeedSource, "source")
        require_instance(self.seed_status, SeedStatus, "seed_status")
        todo = require_instance(self.todo, tuple, "todo")
        for index, question in enumerate(todo):
            require_text(question, f"todo[{index}]")
        if self.seed_status is SeedStatus.NEEDS_REVIEW and not todo:
            raise InvariantViolationError(
                f"{key}: a rule that needs review states at least one question for the analyst"
            )

    @property
    def is_recurring(self) -> bool:
        return self.recurrence is not None


@dataclass(frozen=True, slots=True)
class SeedCalendar:
    version: str
    ontology_version: str
    rules: tuple[SeedRule, ...]

    def __post_init__(self) -> None:
        for name in ("version", "ontology_version"):
            value = require_text(getattr(self, name), name)
            if not SEMVER_PATTERN.fullmatch(value):
                raise InvariantViolationError(f"{name} must be semver, got {value!r}")
        rules = require_instance(self.rules, tuple, "rules")
        if not rules:
            raise InvariantViolationError("a seed calendar has at least one rule")
        seen: set[str] = set()
        for index, rule in enumerate(rules):
            key = require_instance(rule, SeedRule, f"rules[{index}]").rule_key
            if key in seen:
                raise InvariantViolationError(f"duplicate rule_key {key!r}")
            seen.add(key)

    def get(self, rule_key: str) -> SeedRule:
        for rule in self.rules:
            if rule.rule_key == rule_key:
                return rule
        raise KeyError(rule_key)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(rule.rule_key for rule in self.rules)


SEED_CONTENT_KEYS = (
    "title",
    "summary",
    "specification",
    "obligation_template",
    "recurrence",
    "effective_from",
    "source",
    "seed_status",
    "todo",
)
"""The parts of a rule version the seed writes, and the parts a re-run compares."""


def seed_content(rule: SeedRule) -> dict[str, object]:
    """What a seed rule stores in its draft version, in the stored (JSON-ready) form."""
    return {
        "title": rule.title,
        "summary": rule.summary,
        "specification": specification_to_mapping(rule.specification),
        "obligation_template": rule.obligation_template.to_mapping(),
        "recurrence": None if rule.recurrence is None else rule.recurrence.to_mapping(),
        "effective_from": rule.effective_from,
        "source": rule.source.to_mapping(),
        "seed_status": rule.seed_status.value,
        "todo": list(rule.todo),
    }


def reviewed_content(content: Mapping[str, object]) -> dict[str, object]:
    """The content a version past draft is compared on: everything but ``seed_status``, which
    review sets to reviewed while the file still says needs_review."""
    return {key: value for key, value in content.items() if key != "seed_status"}


@dataclass(frozen=True, slots=True)
class SeedOutcome:
    """What one run of the seed did, rule by rule (``rule_key@version`` for versions).
    ``kept_edited`` names the rules whose latest version an analyst edited through its review
    task: the analyst's text is the rule's now, and the seed leaves it alone."""

    created_rules: tuple[str, ...] = ()
    created_versions: tuple[str, ...] = ()
    updated_drafts: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    kept_edited: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        text = (
            f"{len(self.created_rules)} new rules, {len(self.created_versions)} new versions, "
            f"{len(self.updated_drafts)} drafts updated, {len(self.unchanged)} unchanged"
        )
        if self.kept_edited:
            text += f", {len(self.kept_edited)} kept as analysts edited them"
        return text
