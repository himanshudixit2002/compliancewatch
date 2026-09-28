"""The checks every proposed relation passes before it becomes a candidate.

The model's answer is structurally valid by the time it gets here (``parse_relations``); these
checks judge the content against the document. Each issue lowers the confidence by a fixed
factor and sends the candidate to review. Nothing is dropped: a proposal with every issue in
the book still becomes a candidate, and an analyst sees why it is doubtful.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import prod
from typing import Final

from domain_kernel.citations import (
    QUOTE_MATCH_THRESHOLD,
    evidence_tokens_missing,
    quote_match_ratio,
)
from domain_kernel.confidence import REVIEW_THRESHOLD
from domain_kernel.documents import ParsedDocument
from domain_kernel.knowledge import RULE_VERSION_ONLY, EntityType, RelationKind
from pipeline.application.detector import ChangeKind
from pipeline.domain.grammar import ExtractedMention
from pipeline.domain.issues import Issue
from pipeline.domain.knowledge import StagedRelation
from pipeline.domain.numbers import date_forms, normalise, text_has
from pipeline.domain.relations import PROPOSAL_TARGET_TYPES, RawRelation

PENALTIES: Final[Mapping[str, float]] = {
    "relation_target_type_not_allowed": 0.5,
    "evidence_quote_mismatch": 0.5,
    "evidence_token_mismatch": 0.5,
    "date_not_in_clause": 0.6,
    "detail_not_allowed": 0.8,
    "target_not_in_evidence": 0.8,
    "relation_disagrees_with_detector": 0.8,
    "target_unqualified": 0.9,
}
"""How much each issue multiplies the model's confidence by."""

EXPECTED_BY_CHANGE: Final[Mapping[ChangeKind, RelationKind]] = {
    ChangeKind.EXTENSION: RelationKind.EXTENDS_DEADLINE,
    ChangeKind.CORRIGENDUM: RelationKind.CORRECTS,
    ChangeKind.WITHDRAWAL: RelationKind.WITHDRAWS,
    ChangeKind.AMENDMENT: RelationKind.AMENDS,
}
"""The relation the detector's reading of a document leads one to expect from it."""

_PROVISIONS = frozenset({EntityType.SECTION, EntityType.RULE})


@dataclass(frozen=True, slots=True)
class RelationContext:
    """What the checks read: the document, the targets offered by id, every mention the grammar
    found (a target is listed once but may be named in several clauses), and the detector's
    reading of the document."""

    document: ParsedDocument
    targets: Mapping[str, ExtractedMention]
    change_kind: ChangeKind = ChangeKind.NONE
    mentions: tuple[ExtractedMention, ...] = ()

    def clause_text(self, clause_ref: str) -> str:
        clause = self.document.find_clause(clause_ref)
        return "" if clause is None else clause.text

    def target(self, proposal: RawRelation) -> ExtractedMention:
        """The proposal's target as named in its evidence clause when it is named there, else
        where it was first named."""
        listed = self.targets[proposal.target_mention]
        key = (listed.entity_type, listed.proposed_name)
        return next(
            (
                m
                for m in self.mentions
                if m.clause_ref == proposal.evidence_clause_ref
                and (m.entity_type, m.proposed_name) == key
            ),
            listed,
        )


RelationCheck = Callable[[RawRelation, RelationContext], Iterable[Issue]]


def check_pairing(proposal: RawRelation, ctx: RelationContext) -> Iterable[Issue]:
    target = ctx.targets[proposal.target_mention]
    if target.entity_type not in PROPOSAL_TARGET_TYPES[proposal.relation]:
        yield Issue(
            "relation_target_type_not_allowed",
            f"{proposal.relation.value} does not point at a {target.entity_type.value}",
            proposal.evidence_clause_ref,
        )


def check_evidence(proposal: RawRelation, ctx: RelationContext) -> Iterable[Issue]:
    text = ctx.clause_text(proposal.evidence_clause_ref)
    if quote_match_ratio(proposal.evidence_quote, text) < QUOTE_MATCH_THRESHOLD:
        yield Issue(
            "evidence_quote_mismatch",
            "the quote is not in the evidence clause",
            proposal.evidence_clause_ref,
        )
    missing = evidence_tokens_missing(proposal.evidence_quote, text)
    if missing:
        yield Issue(
            "evidence_token_mismatch",
            f"the clause does not have {', '.join(missing)}",
            proposal.evidence_clause_ref,
        )


def check_target_in_evidence(proposal: RawRelation, ctx: RelationContext) -> Iterable[Issue]:
    target = ctx.target(proposal)
    if target.clause_ref != proposal.evidence_clause_ref:
        yield Issue(
            "target_not_in_evidence",
            f"the target is named in {target.clause_ref}, the evidence is another clause",
            proposal.evidence_clause_ref,
        )


def check_target_qualified(proposal: RawRelation, ctx: RelationContext) -> Iterable[Issue]:
    target = ctx.targets[proposal.target_mention]
    if target.entity_type in _PROVISIONS and "@" not in target.proposed_name:
        yield Issue(
            "target_unqualified",
            f"{target.entity_type.value} {target.proposed_name!r} names no statute",
            target.clause_ref,
        )


def check_details(proposal: RawRelation, ctx: RelationContext) -> Iterable[Issue]:
    if proposal.relation is not RelationKind.EXTENDS_DEADLINE:
        if proposal.period is not None or proposal.new_due_date is not None:
            yield Issue(
                "detail_not_allowed",
                f"a period or a new due date does not belong to {proposal.relation.value}",
                proposal.evidence_clause_ref,
            )
        return
    text = ctx.clause_text(proposal.evidence_clause_ref)
    if proposal.new_due_date is not None and not text_has(
        normalise(text), date_forms(proposal.new_due_date)
    ):
        yield Issue(
            "date_not_in_clause",
            f"{proposal.new_due_date.isoformat()} is not written in the evidence clause",
            proposal.evidence_clause_ref,
        )


def check_detector(proposal: RawRelation, ctx: RelationContext) -> Iterable[Issue]:
    expected = EXPECTED_BY_CHANGE.get(ctx.change_kind)
    if (
        expected is not None
        and proposal.relation in RULE_VERSION_ONLY
        and proposal.relation is not expected
    ):
        yield Issue(
            "relation_disagrees_with_detector",
            f"the detector reads the document as {ctx.change_kind.value}",
            proposal.evidence_clause_ref,
        )


CHAIN: Final[tuple[RelationCheck, ...]] = (
    check_pairing,
    check_evidence,
    check_target_in_evidence,
    check_target_qualified,
    check_details,
    check_detector,
)


def validate_relations(
    proposals: Sequence[RawRelation],
    ctx: RelationContext,
    checks: Sequence[RelationCheck] = CHAIN,
) -> tuple[tuple[StagedRelation, ...], tuple[Issue, ...]]:
    """Every proposal as a staged relation with its issues, and the run's own issues."""
    staged: list[StagedRelation] = []
    for proposal in proposals:
        issues = [issue for check in checks for issue in check(proposal, ctx)]
        confidence = proposal.confidence * prod(PENALTIES.get(i.code, 1.0) for i in issues)
        if confidence < REVIEW_THRESHOLD:
            issues.append(Issue("low_confidence", f"{confidence:.2f} < {REVIEW_THRESHOLD}", None))
        extends = proposal.relation is RelationKind.EXTENDS_DEADLINE
        clause_text = ctx.clause_text(proposal.evidence_clause_ref)
        staged.append(
            StagedRelation(
                relation=proposal.relation,
                target=ctx.target(proposal),
                evidence_clause_ref=proposal.evidence_clause_ref,
                evidence_quote=proposal.evidence_quote,
                quote_score=round(quote_match_ratio(proposal.evidence_quote, clause_text), 3),
                confidence=round(confidence, 3),
                needs_review=bool(issues),
                rule_key=proposal.rule_key,
                period_label=proposal.period if extends else None,
                new_due_on=proposal.new_due_date if extends else None,
                issues=tuple(issues),
            )
        )
    return tuple(staged), tuple(_run_issues(proposals, ctx))


def _run_issues(proposals: Sequence[RawRelation], ctx: RelationContext) -> Iterable[Issue]:
    expected = EXPECTED_BY_CHANGE.get(ctx.change_kind)
    if expected is not None and all(p.relation is not expected for p in proposals):
        yield Issue(
            "detector_relation_missing",
            f"the detector reads the document as {ctx.change_kind.value}; no "
            f"{expected.value} was proposed",
        )
