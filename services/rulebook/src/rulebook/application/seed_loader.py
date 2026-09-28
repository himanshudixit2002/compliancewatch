"""Parse the seed calendar YAML into ``SeedRule``s and check it against the ontology.

Structured predicates must name an ontology attribute with an allowed operator and a valid
value; a free-text predicate may name an attribute the ontology does not have yet, which is
exactly the kind of gap the rule's ``todo`` records. Every problem is collected and reported
at once so an analyst fixes the file in one pass.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import yaml

from domain_kernel.errors import DomainError, InvariantViolationError, UnknownAttributeError
from domain_kernel.ontology import AttributeLevel, Ontology
from domain_kernel.predicates import PredicateKind, specification_from_mapping
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate
from rulebook.domain.seed import SeedCalendar, SeedRule, SeedSource, SeedStatus

RULE_KEYS = frozenset(
    {
        "rule_key",
        "title",
        "summary",
        "regulator",
        "level",
        "specification",
        "obligation_template",
        "recurrence",
        "effective_from",
        "source",
        "seed_status",
        "todo",
    }
)
REQUIRED_RULE_KEYS = RULE_KEYS - {"recurrence"}


class SeedError(ValueError):
    """The seed file is malformed; ``problems`` lists every finding."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


def default_seed_path() -> Path:
    """``services/rulebook/seed/gst_calendar.yaml`` in a checkout."""
    return Path(__file__).resolve().parents[3] / "seed" / "gst_calendar.yaml"


def parse_calendar(text: str, ontology: Ontology) -> SeedCalendar:
    data = yaml.safe_load(text)
    if not isinstance(data, Mapping):
        raise SeedError(["the seed file must be a mapping with version, ontology_version, rules"])
    problems: list[str] = []
    rules_raw = data.get("rules")
    if not isinstance(rules_raw, list):
        raise SeedError(["rules must be a list"])
    rules: list[SeedRule] = []
    for index, raw in enumerate(rules_raw):
        where = f"rules[{index}]"
        if isinstance(raw, Mapping) and isinstance(raw.get("rule_key"), str):
            where = raw["rule_key"]
        try:
            rules.append(_rule(raw, where))
        except (DomainError, SeedError, ValueError, TypeError) as exc:
            problems.append(f"{where}: {exc}")
    if problems:
        raise SeedError(problems)
    try:
        calendar = SeedCalendar(
            version=str(data.get("version", "")),
            ontology_version=str(data.get("ontology_version", "")),
            rules=tuple(rules),
        )
    except DomainError as exc:
        raise SeedError([str(exc)]) from exc
    problems.extend(check_against_ontology(calendar, ontology))
    if problems:
        raise SeedError(problems)
    return calendar


def load_calendar(ontology: Ontology, path: Path | None = None) -> SeedCalendar:
    return parse_calendar((path or default_seed_path()).read_text(encoding="utf-8"), ontology)


def check_against_ontology(calendar: SeedCalendar, ontology: Ontology) -> list[str]:
    """Every structured predicate is valid for the ontology; the version matches."""
    problems: list[str] = []
    if calendar.ontology_version != ontology.version:
        problems.append(
            f"seed is written for ontology {calendar.ontology_version}, "
            f"loaded ontology is {ontology.version}"
        )
    for rule in calendar.rules:
        for predicate in rule.specification.predicates():
            if predicate.kind is PredicateKind.FREE_TEXT:
                if predicate.attribute not in ontology and not rule.todo:
                    problems.append(
                        f"{rule.rule_key}: free-text predicate on unknown attribute "
                        f"{predicate.attribute!r} needs a todo"
                    )
                continue
            try:
                ontology.check_predicate(predicate)
            except (UnknownAttributeError, DomainError) as exc:
                problems.append(f"{rule.rule_key}: {predicate.describe()}: {exc}")
    return problems


def _rule(raw: object, where: str) -> SeedRule:
    if not isinstance(raw, Mapping):
        raise SeedError([f"{where} must be a mapping"])
    unknown = set(raw) - RULE_KEYS
    missing = REQUIRED_RULE_KEYS - set(raw)
    if unknown or missing:
        raise SeedError(
            [
                *(f"unknown key {key!r}" for key in sorted(unknown)),
                *(f"missing key {key!r}" for key in sorted(missing)),
            ]
        )
    source_raw = raw["source"]
    if not isinstance(source_raw, Mapping):
        raise SeedError(["source must be a mapping"])
    todo_raw = raw["todo"]
    if not isinstance(todo_raw, list):
        raise SeedError(["todo must be a list"])
    effective = raw["effective_from"]
    if isinstance(effective, str):
        effective = date.fromisoformat(effective)
    recurrence_raw = raw.get("recurrence")
    try:
        level = AttributeLevel(str(raw["level"]))
    except ValueError as exc:
        raise SeedError(
            [f"level must be one of {[item.value for item in AttributeLevel]}"]
        ) from exc
    try:
        status = SeedStatus(str(raw["seed_status"]))
    except ValueError as exc:
        raise SeedError([f"seed_status must be one of {[s.value for s in SeedStatus]}"]) from exc
    return SeedRule(
        rule_key=str(raw["rule_key"]),
        title=str(raw["title"]),
        summary=str(raw["summary"]).strip(),
        regulator=str(raw["regulator"]),
        level=level,
        specification=specification_from_mapping(raw["specification"]),
        obligation_template=ObligationTemplate.from_mapping(raw["obligation_template"]),
        recurrence=None if recurrence_raw is None else Recurrence.from_mapping(recurrence_raw),
        effective_from=effective if isinstance(effective, date) else _bad_date(effective),
        source=SeedSource(
            instrument=str(source_raw.get("instrument", "")),
            reference=str(source_raw.get("reference", "")),
            note=str(source_raw.get("note", "")),
            url=str(source_raw.get("url", "")),
        ),
        seed_status=status,
        todo=tuple(str(item) for item in todo_raw),
    )


def _bad_date(value: object) -> date:
    raise InvariantViolationError(f"effective_from must be an ISO date, got {value!r}")
