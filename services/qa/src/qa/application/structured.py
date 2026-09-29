"""Layer 1: two questions answered from the business's own obligations, with no model call.

"When is my <form> due" gives the earliest open obligation of that form due on or after the
question's date, within a year; "what is due this (or next) month" gives every open obligation
due in that month. Only obligations of rule versions in force on the date count, and the answer
cites the rule version's verified citations, each checked again against its clause. Anything
else, no obligation, or no citation that holds passes the question to the next layer: this
layer never answers ``not_covered``.

An obligation whose deadline a version in force extends (``extends_deadline``, for the
obligation's period when the relation names one) passes the question on too: the obligation's
due date may not have moved yet, and the next layer reads the extension itself.
"""

import re
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Final

from domain_kernel.citations import evidence_tokens_missing, quote_matches
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId
from domain_kernel.knowledge import RelationKind
from qa.application.context import AskContext
from qa.domain.answer import MAX_CITATIONS, Answer, AnswerCitation
from qa.domain.intents import DueForForm, DueInWindow, Intent, match_intent
from qa.domain.ports import ObligationReader, RulebookReader
from qa.domain.records import ObligationRecord, RuleVersion

LOOKAHEAD_DAYS: Final = 365
"""How far ahead "when is my form due" looks for the next due date."""


class StructuredLayer:
    def __init__(self, rulebook: RulebookReader, obligations: ObligationReader) -> None:
        self._rulebook = rulebook
        self._obligations = obligations

    def run(self, ctx: AskContext) -> Answer | None:
        request = ctx.request
        business = request.business
        if business is None:
            return None
        intent = match_intent(request.question, request.as_of)
        if intent is None:
            return None
        visible = ctx.visible()
        reader = _OpenObligations(self._obligations, request.tenant, business, visible)
        chosen: list[ObligationRecord]
        match intent:
            case DueForForm(form=form):
                end = request.as_of + timedelta(days=LOOKAHEAD_DAYS)
                due = reader.due(request.as_of, end)
                chosen = [
                    obligation
                    for obligation in due
                    if _names_form(obligation.title, form)
                    or _names_form(visible[obligation.rule_version_id].title, form)
                ][:1]
            case DueInWindow(start=start, end=end):  # pragma: no branch - the other intent
                chosen = reader.due(start, end)
        if not chosen or self._extended(chosen, visible):
            return None
        citations = self._citations(dict.fromkeys(item.rule_version_id for item in chosen))
        if not citations:
            return None
        return Answer.answered(_text(intent, chosen), citations)

    def _extended(
        self, chosen: Iterable[ObligationRecord], visible: Mapping[RuleVersionId, RuleVersion]
    ) -> bool:
        """Whether a version in force extends the deadline of a chosen obligation."""
        periods: dict[RuleVersionId, set[str | None]] = {}
        for obligation in chosen:
            periods.setdefault(obligation.rule_version_id, set()).add(obligation.period_label)
        return any(
            relation.relation is RelationKind.EXTENDS_DEADLINE
            and relation.from_rule_version_id in visible
            and (relation.period_label is None or relation.period_label in labels)
            for rule_version_id, labels in periods.items()
            for relation in self._rulebook.relations(to_rule_version_id=rule_version_id)
        )

    def _citations(self, rule_version_ids: Iterable[RuleVersionId]) -> list[AnswerCitation]:
        """The verified citations of the versions whose quotes still hold in their clauses."""
        found: list[AnswerCitation] = []
        for rule_version_id in rule_version_ids:
            detail = self._rulebook.rule_version(rule_version_id)
            if detail is None:
                continue
            for citation in detail.citations:
                if not citation.verified or len(found) == MAX_CITATIONS:
                    continue
                clause = self._rulebook.clause(citation.clause_id)
                if clause is None or not _holds(citation.quote, clause.text):
                    continue
                cited = AnswerCitation(clause.clause_ref, clause.document_id, citation.quote)
                if cited not in found:
                    found.append(cited)
        return found


class _OpenObligations:
    """Open obligations with a due day, of versions in force, due first."""

    def __init__(
        self,
        obligations: ObligationReader,
        tenant: TenantId,
        business: BusinessId,
        visible: Mapping[RuleVersionId, RuleVersion],
    ) -> None:
        self._obligations = obligations
        self._tenant = tenant
        self._business = business
        self._visible = visible

    def due(self, start: date, end: date) -> list[ObligationRecord]:
        found = self._obligations.obligations(
            self._tenant, self._business, due_from=start, due_to=end
        )
        dated = [
            (obligation.due_on, obligation)
            for obligation in found
            if obligation.is_open and obligation.rule_version_id in self._visible
        ]
        ordered = sorted(
            ((day, item) for day, item in dated if day is not None),
            key=lambda pair: (pair[0], pair[1].title),
        )
        return [item for _, item in ordered]


def _holds(quote: str, text: str) -> bool:
    return quote_matches(quote, text) and not evidence_tokens_missing(quote, text)


def _names_form(title: str, form: str) -> bool:
    """Whether ``title`` names the form as a whole code: GSTR-3B, not GSTR-3."""
    folded = title.casefold().replace(" - ", "-")
    return (
        re.search(rf"(?<![a-z0-9-]){re.escape(form.casefold())}(?![a-z0-9-])", folded) is not None
    )


def _day(day: date | None) -> str:
    return "no date" if day is None else f"{day.day} {day:%B %Y}"


def _text(intent: Intent, chosen: list[ObligationRecord]) -> str:
    if isinstance(intent, DueForForm):
        first = chosen[0]
        return f"Your next {intent.form} is due on {_day(first.due_on)}: {first.title}."
    items = "; ".join(f"{item.title}, due on {_day(item.due_on)}" for item in chosen)
    return f"Due {intent.label}: {items}."
