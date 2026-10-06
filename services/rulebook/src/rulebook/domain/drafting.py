"""The content of a draft rule version an analyst edits, and the checks it passes.

A draft is edited through its review task (``PATCH .../review/tasks/{id}/draft``) or drafted from
a rule candidate (``POST .../review/tasks/{id}/draft``). Either way its content is checked as the
seed loader checks the calendar: each value is read into the kernel's canonical form, structured
predicates must fit the ontology, a free-text predicate may name an attribute the ontology lacks
only while the version carries an open question (``todo``), and a duty that does not recur needs
the template's ``due_in_days``. Every problem found is reported at once.

``changed_paths`` names what an edit changed, as dotted paths into the content
(``obligation_template.due_in_days``, ``specification.all_of[1].value``), for the decision
audit.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Final, Protocol

from domain_kernel._validation import require_date, require_instance, require_text
from domain_kernel.errors import DomainError, InvariantViolationError
from domain_kernel.ontology import Ontology
from domain_kernel.predicates import (
    PredicateKind,
    specification_from_mapping,
    specification_to_mapping,
)
from domain_kernel.recurrence import Recurrence
from domain_kernel.rules import ObligationTemplate
from rulebook.domain.rule_versions import RuleVersionRecord

MAX_TITLE: Final = 300
MAX_SUMMARY: Final = 4_000
MAX_TODO: Final = 20
MAX_QUESTION: Final = 500
MAX_PATHS: Final = 20
"""At most this many changed paths are named; the rest are counted."""

EDITABLE_FIELDS: Final = (
    "title",
    "summary",
    "specification",
    "obligation_template",
    "recurrence",
    "effective_from",
    "effective_to",
    "todo",
)
"""The content of a draft an analyst edits. The rule's key, regulator and level, the seed source
and the lifecycle columns are not edited here."""
NULLABLE_FIELDS: Final = frozenset({"recurrence", "effective_to"})


class DraftContentLike(Protocol):
    """What the content checks read: a draft version, or content not stored yet."""

    @property
    def specification(self) -> Mapping[str, object]: ...

    @property
    def obligation_template(self) -> Mapping[str, object]: ...

    @property
    def recurrence(self) -> Mapping[str, object] | None: ...

    @property
    def effective_from(self) -> date: ...

    @property
    def effective_to(self) -> date | None: ...

    @property
    def todo(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class DraftEdit:
    """What an analyst changes in a draft: the fields named in ``changes``, each with its new
    value as sent (the mapping forms for the specification, the template and the recurrence;
    None clears the recurrence or the end date)."""

    changes: Mapping[str, object]

    def __post_init__(self) -> None:
        unknown = sorted(set(self.changes) - set(EDITABLE_FIELDS))
        if unknown:
            raise InvariantViolationError(f"a draft edit cannot change {', '.join(unknown)}")
        refused = sorted(
            name
            for name, value in self.changes.items()
            if value is None and name not in NULLABLE_FIELDS
        )
        if refused:
            raise InvariantViolationError(f"{', '.join(refused)} cannot be null")


def checked_values(edit: DraftEdit) -> tuple[dict[str, Any], list[str]]:
    """The edit's values in the kernel's canonical form, and a problem (``field: why``) for each
    value that does not read."""
    problems: list[str] = []
    values: dict[str, Any] = {}
    for name, raw in edit.changes.items():
        try:
            values[name] = _CHECKS[name](raw)
        except (DomainError, TypeError, ValueError) as exc:
            problems.append(f"{name}: {exc}")
    return values, problems


def edited_record(
    record: RuleVersionRecord, edit: DraftEdit, ontology: Ontology
) -> tuple[RuleVersionRecord, tuple[str, ...]]:
    """The draft after ``edit`` and the fields whose value changed. Each value is checked and
    stored in the kernel's canonical form; every problem found is reported at once."""
    values, problems = checked_values(edit)
    if problems:
        raise InvariantViolationError("; ".join(problems))
    after = replace(record, **values)
    problems = content_problems(after, ontology)
    if problems:
        raise InvariantViolationError("; ".join(problems))
    changed = tuple(
        name for name in EDITABLE_FIELDS if getattr(after, name) != getattr(record, name)
    )
    return after, changed


def content_problems(content: DraftContentLike, ontology: Ontology) -> list[str]:
    """What the seed loader would refuse in the content."""
    problems: list[str] = []
    if content.effective_to is not None and content.effective_to <= content.effective_from:
        problems.append("effective_to must be after effective_from")
    try:
        template = ObligationTemplate.from_mapping(content.obligation_template)
        specification = specification_from_mapping(content.specification)
    except DomainError as exc:
        return [*problems, f"the stored content does not parse: {exc}"]
    if content.recurrence is None and template.due_in_days is None:
        problems.append("a duty that does not recur needs obligation_template.due_in_days")
    for predicate in specification.predicates():
        if predicate.kind is PredicateKind.FREE_TEXT:
            if predicate.attribute not in ontology and not content.todo:
                problems.append(
                    f"free-text predicate on unknown attribute {predicate.attribute!r} needs an "
                    "open question in todo"
                )
            continue
        try:
            ontology.check_predicate(predicate)
        except DomainError as exc:
            problems.append(f"{predicate.describe()}: {exc}")
    return problems


def changed_paths(before: Mapping[str, object], after: Mapping[str, object]) -> tuple[str, ...]:
    """Where ``after`` differs from ``before``, as dotted paths in field order: a key one side
    lacks is a change of its own, mappings that share a key and lists of one length are compared
    item by item, and anything else by value (a list and a tuple of equal items are equal)."""
    order = {name: index for index, name in enumerate(EDITABLE_FIELDS)}
    keys = sorted(set(before) | set(after), key=lambda key: (order.get(key, len(order)), key))
    paths: list[str] = []
    for key in keys:
        if key not in before or key not in after:
            paths.append(key)
        else:
            paths.extend(_diff(before[key], after[key], key))
    return tuple(paths)


def described_paths(paths: Sequence[str]) -> str:
    """``title, obligation_template.due_in_days`` with at most ``MAX_PATHS`` named."""
    named = ", ".join(paths[:MAX_PATHS])
    more = len(paths) - MAX_PATHS
    return f"{named} and {more} more" if more > 0 else named


def _diff(old: object, new: object, path: str) -> list[str]:
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        if old and new and not set(old) & set(new):
            return [path]
        found: list[str] = []
        for key in sorted(set(old) | set(new), key=str):
            where = f"{path}.{key}"
            if key not in old or key not in new:
                found.append(where)
            else:
                found.extend(_diff(old[key], new[key], where))
        return found
    if _is_list(old) and _is_list(new):
        old_items, new_items = list(old), list(new)  # type: ignore[call-overload]
        if len(old_items) == len(new_items):
            return [
                found
                for index, (a, b) in enumerate(zip(old_items, new_items, strict=True))
                for found in _diff(a, b, f"{path}[{index}]")
            ]
    return [] if old == new else [path]


def _is_list(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _title(raw: object) -> str:
    title = require_text(raw, "title")
    if len(title) > MAX_TITLE:
        raise InvariantViolationError(f"at most {MAX_TITLE} characters")
    return title


def _summary(raw: object) -> str:
    summary = require_instance(raw, str, "summary").strip()
    if len(summary) > MAX_SUMMARY:
        raise InvariantViolationError(f"at most {MAX_SUMMARY} characters")
    return summary


def _specification(raw: object) -> Mapping[str, object]:
    return specification_to_mapping(specification_from_mapping(raw))


def _template(raw: object) -> Mapping[str, object]:
    return ObligationTemplate.from_mapping(raw).to_mapping()


def _recurrence(raw: object) -> Mapping[str, object] | None:
    return None if raw is None else Recurrence.from_mapping(raw).to_mapping()


def _effective_to(raw: object) -> date | None:
    return None if raw is None else require_date(raw, "effective_to")


def _todo(raw: object) -> tuple[str, ...]:
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        raise InvariantViolationError("todo must be a list of questions")
    if len(raw) > MAX_TODO:
        raise InvariantViolationError(f"at most {MAX_TODO} questions")
    questions = tuple(require_text(item, "todo[]") for item in raw)
    if any(len(question) > MAX_QUESTION for question in questions):
        raise InvariantViolationError(f"a question has at most {MAX_QUESTION} characters")
    return questions


_CHECKS: Mapping[str, Callable[[object], object]] = {
    "title": _title,
    "summary": _summary,
    "specification": _specification,
    "obligation_template": _template,
    "recurrence": _recurrence,
    "effective_from": lambda raw: require_date(raw, "effective_from"),
    "effective_to": _effective_to,
    "todo": _todo,
}
