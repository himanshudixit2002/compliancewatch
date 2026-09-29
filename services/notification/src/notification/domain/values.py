"""The values a message template is filled with, from what a notification knows.

A queued notification keeps what its event said (``routing.ObligationNotice``). When it goes
out, ``message_values`` turns that into the values its template names, adding what the rulebook
publishes about the rule version and a link into the web app:

- dates in IST, as '25 Oct 2026' ('25 अक्टूबर 2026' in Hindi): ``due_date``,
  ``previous_due_date``, ``new_due_date``, ``closed_on`` and ``applies_from``;
- ``steps`` joined with '; ', from the event or else from the rule version;
- ``summary`` and ``applies_from`` from the rule version, and ``source_ref`` from the version
  that changed the deadline (or the rule version itself);
- ``reason`` in words for a closure;
- a phrase where a value is missing: no due date, no steps, no label for the business, no
  source.

A value the notification already has is kept. A change card states the rule version's facts,
so without them (the rulebook has no such version) the notification goes out as
``obligation_created``, which states only what the obligation itself says.
"""

from collections.abc import Mapping
from datetime import date, datetime

from domain_kernel.errors import InvariantViolationError
from notification.domain.ports import RuleVersionFacts
from notification.domain.preferences import IST
from notification.domain.templates import CHANGE_CARD, CREATED, month_name, phrase

CLOSE_REASONS = frozenset({"profile_changed", "rule_superseded"})
"""Closure reasons ``obligation_closed`` puts in words."""
STEP_SEPARATOR = "; "


def format_date(value: object, language: str) -> str:
    """A date, a datetime or an ISO 8601 text as the day in IST, such as '25 Oct 2026'."""
    day = _day(value)
    return f"{day.day} {month_name(day.month, language)} {day.year}"


def _day(value: object) -> date:
    if isinstance(value, datetime):
        return value.astimezone(IST).date() if value.tzinfo is not None else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            if len(value) == len("2026-10-25"):
                return date.fromisoformat(value)
            return _day(datetime.fromisoformat(value))
        except ValueError:
            pass
    raise InvariantViolationError(f"not a date: {value!r}")


def message_values(
    template_key: str,
    language: str,
    params: Mapping[str, object],
    *,
    business_name: str,
    link: str,
    rule: RuleVersionFacts | None = None,
    source: RuleVersionFacts | None = None,
) -> tuple[str, dict[str, object]]:
    """The template to send and its values. ``business_name`` is the recipient's label for the
    business ('' for none), ``rule`` the facts of the notification's rule version and ``source``
    those of the version whose source a change cites."""
    values: dict[str, object] = dict(params)
    values.setdefault("business_name", business_name or phrase("business", language))
    values.setdefault("link", link)
    title = params.get("title") or (rule.title if rule is not None else "")
    if title:
        values["title"] = str(title)
    values["steps"] = _steps(params.get("steps"), rule, language)
    due_at = params.get("due_at")
    values.setdefault(
        "due_date", phrase("no_due_date", language) if not due_at else format_date(due_at, language)
    )
    for fact, name in (
        ("previous_due_at", "previous_due_date"),
        ("new_due_at", "new_due_date"),
        ("closed_at", "closed_on"),
    ):
        if params.get(fact):
            values.setdefault(name, format_date(params[fact], language))
    reason = params.get("close_reason")
    if reason:
        values.setdefault(
            "reason", phrase(f"closed.{reason}", language) if reason in CLOSE_REASONS else reason
        )
    cited = source or rule
    values.setdefault(
        "source_ref",
        cited.source_ref if cited and cited.source_ref else phrase("rulebook", language),
    )
    if rule is not None:
        values.setdefault("summary", rule.summary.strip().rstrip(".") or values.get("title", ""))
        values.setdefault("applies_from", format_date(rule.effective_from, language))
    elif template_key == CHANGE_CARD:
        return CREATED, values
    return template_key, values


def _steps(given: object, rule: RuleVersionFacts | None, language: str) -> str:
    """The steps as one text: the event's, else the rule version's, else a pointer to the
    details."""
    if isinstance(given, str) and given.strip():
        return given
    steps = [str(step) for step in given] if isinstance(given, list | tuple) else []
    if not steps and rule is not None:
        steps = list(rule.steps)
    return STEP_SEPARATOR.join(steps) if steps else phrase("no_steps", language)
