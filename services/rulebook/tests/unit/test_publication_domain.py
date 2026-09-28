"""The publication planner: every check in its order, every relation effect, a replacement dated
before and after today, the due transitions, and the rule events it builds."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from domain_kernel.errors import InvalidTransitionError, InvariantViolationError
from domain_kernel.ids import (
    ClauseId,
    CorrelationId,
    DocumentId,
    EventId,
    RuleId,
    RuleVersionId,
    TenantId,
    UserId,
)
from domain_kernel.knowledge import RelationKind
from domain_kernel.ontology import AttributeLevel
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.errors import (
    ApprovalsMissingError,
    CitationsMissingError,
    DeadlineDetailMissingError,
    OverlappingVersionError,
    RelationTargetStateError,
    ReplacementDatesError,
    TargetAlreadyReplacedError,
    UnknownRuleVersionError,
)
from rulebook.domain.events import (
    DeadlineChangeReason,
    RuleDeadlineChanged,
    RulePublished,
    RuleSuperseded,
    RuleWithdrawn,
)
from rulebook.domain.graph import RelationRecord
from rulebook.domain.publication import (
    DecisionAction,
    PendingReplacement,
    PublicationPlan,
    RuleVersionDecision,
    attribute_keys,
    plan_due_transitions,
    plan_publication,
    required_approvals,
    transition_event,
)
from rulebook.domain.rule_versions import CitationRecord, RuleVersionRecord, check_quote
from rulebook.domain.seed import SeedStatus

RULE = RuleId(UUID(int=1))
OTHER_RULE = RuleId(UUID(int=2))
CLAUSE = ClauseId(UUID(int=3))
DOCUMENT = DocumentId(UUID(int=4))
ANALYST = UserId(UUID(int=5))
SECOND = UserId(UUID(int=6))
APRIL = date(2026, 4, 1)
JULY = date(2026, 7, 1)
TODAY = date(2026, 10, 1)
NOVEMBER = date(2026, 11, 1)
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
SPECIFICATION = {
    "all_of": [
        {"attribute": "registration_type", "operator": "eq", "value": "regular"},
        {"attribute": "turnover_band", "operator": "in", "value": ["b", "c"]},
        {"attribute": "registration_type", "operator": "neq", "value": "composition"},
    ]
}
MONTHLY = {"frequency": "monthly", "due_day": 20, "due_month_offset": 0}


def version(
    number: int = 2,
    status: RuleVersionStatus = RuleVersionStatus.APPROVED,
    effective_from: date = JULY,
    effective_to: date | None = None,
    *,
    rule_id: RuleId = RULE,
    high_impact: bool = False,
    recurrence: dict[str, object] | None = None,
) -> RuleVersionRecord:
    return RuleVersionRecord(
        rule_version_id=RuleVersionId.new(),
        rule_id=rule_id,
        rule_key="test_rule",
        regulator="CBIC",
        level=AttributeLevel.REGISTRATION,
        version=number,
        status=status,
        title=f"version {number}",
        summary="",
        specification=SPECIFICATION,
        obligation_template={},
        recurrence=recurrence,
        effective_from=effective_from,
        effective_to=effective_to,
        source={},
        seed_status=SeedStatus.REVIEWED,
        todo=(),
        high_impact=high_impact,
        submitted_at=NOW,
    )


def relation(
    x: RuleVersionRecord,
    kind: RelationKind,
    y: RuleVersionRecord,
    *,
    period_label: str | None = None,
    new_due_on: date | None = None,
) -> RelationRecord:
    return RelationRecord(
        relation_id=uuid4(),
        from_rule_version_id=x.rule_version_id,
        relation=kind,
        to_kind="rule_version",
        to_ref=str(y.rule_version_id),
        to_rule_version_id=y.rule_version_id,
        to_entity_id=None,
        evidence_clause_id=CLAUSE,
        evidence_clause_ref="en.p1",
        evidence_document_id=DOCUMENT,
        period_label=period_label,
        new_due_on=new_due_on,
    )


def citation(x: RuleVersionRecord, *, verified: bool = True) -> CitationRecord:
    return CitationRecord(
        citation_id=uuid4(),
        rule_version_id=x.rule_version_id,
        clause_id=CLAUSE,
        document_id=DOCUMENT,
        clause_ref="en.p1",
        quote="the quote",
        verified=verified,
        match_score=1.0 if verified else None,
        verified_at=NOW if verified else None,
    )


def plan(
    x: RuleVersionRecord,
    relations: tuple[RelationRecord, ...] = (),
    targets: tuple[RuleVersionRecord, ...] = (),
    *,
    siblings: tuple[RuleVersionRecord, ...] | None = None,
    approvers: frozenset[UserId] = frozenset({ANALYST}),
    citations: tuple[CitationRecord, ...] | None = None,
    replaced_elsewhere: frozenset[RuleVersionId] = frozenset(),
    today: date = TODAY,
) -> PublicationPlan:
    return plan_publication(
        x,
        relations=relations,
        targets={target.rule_version_id: target for target in targets},
        replaced_elsewhere=replaced_elsewhere,
        siblings=(x, *targets) if siblings is None else siblings,
        approvers=approvers,
        citations=(citation(x),) if citations is None else citations,
        today=today,
        published_at=NOW,
    )


# ---------------------------------------------------------------- checks, in order


def test_required_approvals_follow_adr_006() -> None:
    assert required_approvals(False) == 1
    assert required_approvals(True) == 2


@pytest.mark.parametrize(
    "status",
    [
        RuleVersionStatus.DRAFT,
        RuleVersionStatus.IN_REVIEW,
        RuleVersionStatus.PUBLISHED,
        RuleVersionStatus.SUPERSEDED,
        RuleVersionStatus.WITHDRAWN,
    ],
)
def test_only_an_approved_version_is_published(status: RuleVersionStatus) -> None:
    with pytest.raises(InvalidTransitionError):
        plan(version(status=status), citations=(), approvers=frozenset())


def test_citations_come_before_approvals() -> None:
    x = version()
    with pytest.raises(CitationsMissingError, match="cites no clause"):
        plan(x, citations=(), approvers=frozenset())
    with pytest.raises(CitationsMissingError, match="1 of the 2 citations"):
        plan(x, citations=(citation(x), citation(x, verified=False)))


def test_approvals_come_before_relations() -> None:
    x = version(high_impact=True)
    y = version(1, RuleVersionStatus.DRAFT, APRIL)
    broken = (relation(x, RelationKind.SUPERSEDES, y),)
    with pytest.raises(ApprovalsMissingError, match="1 of the 2 approvals"):
        plan(x, broken, (y,))
    with pytest.raises(ApprovalsMissingError, match="0 of the 1"):
        plan(version(), approvers=frozenset())
    with pytest.raises(RelationTargetStateError):
        plan(x, broken, (y,), approvers=frozenset({ANALYST, SECOND}))


def test_relations_come_before_the_overlap_check() -> None:
    x = version()
    open_sibling = version(1, RuleVersionStatus.PUBLISHED, APRIL)
    draft_target = version(1, RuleVersionStatus.DRAFT, APRIL, rule_id=OTHER_RULE)
    with pytest.raises(RelationTargetStateError):
        plan(
            x,
            (relation(x, RelationKind.SUPERSEDES, draft_target),),
            (draft_target,),
            siblings=(x, open_sibling),
        )
    with pytest.raises(OverlappingVersionError, match="overlaps version 1"):
        plan(x, siblings=(x, open_sibling))


def test_a_version_with_no_relations_is_published_as_it_is() -> None:
    x = version()
    published = plan(x, approvers=frozenset({SECOND, ANALYST}))
    assert published.published == replace(x, status=RuleVersionStatus.PUBLISHED, published_at=NOW)
    assert published.replacements == ()
    assert published.deadline_changes == ()
    assert published.approved_by == tuple(sorted((ANALYST, SECOND), key=str))
    assert published.attribute_keys == ("registration_type", "turnover_band")


# ---------------------------------------------------------------- replacements


@pytest.mark.parametrize(
    ("kind", "moves_to", "event_type"),
    [
        (RelationKind.SUPERSEDES, RuleVersionStatus.SUPERSEDED, RuleSuperseded),
        (RelationKind.CORRECTS, RuleVersionStatus.SUPERSEDED, RuleSuperseded),
        (RelationKind.WITHDRAWS, RuleVersionStatus.WITHDRAWN, RuleWithdrawn),
    ],
)
def test_a_replacement_in_effect_moves_its_target_at_publication(
    kind: RelationKind, moves_to: RuleVersionStatus, event_type: type[object]
) -> None:
    x = version(effective_from=JULY)
    y = version(1, RuleVersionStatus.PUBLISHED, APRIL)
    published = plan(x, (relation(x, kind, y),), (y,))
    (replacement,) = published.replacements
    assert (replacement.due, replacement.moves_to, replacement.effective_to) == (
        True,
        moves_to,
        JULY,
    )
    assert replacement.updated.status is moves_to
    assert replacement.updated.effective_to == JULY
    assert published.supersedes == ((y.rule_version_id,) if kind is RelationKind.SUPERSEDES else ())

    correlation = CorrelationId.new()
    announced, moved = published.events(correlation_id=correlation, occurred_at=NOW)
    assert isinstance(announced, RulePublished)
    assert isinstance(moved, event_type)
    assert announced.causation_id is None
    assert moved.causation_id == announced.event_id
    assert {announced.correlation_id, moved.correlation_id} == {correlation}
    assert (announced.tenant_id, moved.tenant_id) == (None, None)
    assert announced.partition_key == moved.partition_key == str(RULE)
    assert moved.effective_from == JULY  # type: ignore[attr-defined]


def test_a_future_replacement_cuts_now_and_moves_later() -> None:
    x = version(effective_from=NOVEMBER)
    y = version(1, RuleVersionStatus.PUBLISHED, APRIL)
    published = plan(x, (relation(x, RelationKind.SUPERSEDES, y),), (y,))
    (replacement,) = published.replacements
    assert not replacement.due
    assert replacement.updated.status is RuleVersionStatus.PUBLISHED
    assert replacement.updated.effective_to == NOVEMBER
    (announced,) = published.events(correlation_id=CorrelationId.new(), occurred_at=NOW)
    assert isinstance(announced, RulePublished)
    assert announced.supersedes == (y.rule_version_id,)


def test_the_day_x_takes_effect_counts_as_in_effect() -> None:
    x = version(effective_from=TODAY)
    y = version(1, RuleVersionStatus.PUBLISHED, APRIL)
    (replacement,) = plan(x, (relation(x, RelationKind.SUPERSEDES, y),), (y,)).replacements
    assert replacement.due


def test_an_earlier_end_of_the_target_is_kept() -> None:
    x = version(effective_from=NOVEMBER)
    y = version(1, RuleVersionStatus.PUBLISHED, APRIL, JULY)
    (replacement,) = plan(x, (relation(x, RelationKind.SUPERSEDES, y),), (y,)).replacements
    assert replacement.effective_to == JULY


@pytest.mark.parametrize(
    "status",
    [RuleVersionStatus.DRAFT, RuleVersionStatus.SUPERSEDED, RuleVersionStatus.WITHDRAWN],
)
def test_a_replacement_needs_a_published_target(status: RuleVersionStatus) -> None:
    x = version()
    y = version(1, status, APRIL, rule_id=OTHER_RULE)
    with pytest.raises(RelationTargetStateError, match=status.value):
        plan(x, (relation(x, RelationKind.SUPERSEDES, y),), (y,))


@pytest.mark.parametrize("starts", [JULY, NOVEMBER])
def test_a_replacement_starts_after_its_target(starts: date) -> None:
    x = version(effective_from=JULY)
    y = version(1, RuleVersionStatus.PUBLISHED, starts)
    with pytest.raises(ReplacementDatesError):
        plan(x, (relation(x, RelationKind.SUPERSEDES, y),), (y,))


def test_a_target_replaced_by_another_published_version_is_refused() -> None:
    x = version()
    y = version(1, RuleVersionStatus.PUBLISHED, APRIL)
    with pytest.raises(TargetAlreadyReplacedError):
        plan(
            x,
            (relation(x, RelationKind.CORRECTS, y),),
            (y,),
            replaced_elsewhere=frozenset({y.rule_version_id}),
        )


def test_two_relations_to_one_target_must_agree() -> None:
    x = version()
    y = version(1, RuleVersionStatus.PUBLISHED, APRIL)
    same = (relation(x, RelationKind.CORRECTS, y), relation(x, RelationKind.SUPERSEDES, y))
    agreed = plan(x, same, (y,))
    assert len(agreed.replacements) == 1
    assert agreed.supersedes == (y.rule_version_id,)
    clash = (relation(x, RelationKind.SUPERSEDES, y), relation(x, RelationKind.WITHDRAWS, y))
    with pytest.raises(RelationTargetStateError, match="both superseded and withdrawn"):
        plan(x, clash, (y,))


def test_a_target_that_was_not_loaded_is_unknown() -> None:
    x = version()
    y = version(1, RuleVersionStatus.PUBLISHED, APRIL)
    with pytest.raises(UnknownRuleVersionError):
        plan(x, (relation(x, RelationKind.SUPERSEDES, y),), siblings=(x,))


def test_relations_without_an_effect_change_nothing() -> None:
    x = version()
    y = version(1, RuleVersionStatus.DRAFT, APRIL, rule_id=OTHER_RULE)
    entity = replace(
        relation(x, RelationKind.REFERS_TO, y), to_kind="form", to_rule_version_id=None
    )
    published = plan(x, (relation(x, RelationKind.AMENDS, y), entity), (y,))
    assert (published.replacements, published.deadline_changes) == ((), ())


# ---------------------------------------------------------------- deadline changes


def test_extends_deadline_announces_the_new_date_at_publication() -> None:
    x = version(effective_from=NOVEMBER, rule_id=OTHER_RULE)
    y = version(1, RuleVersionStatus.PUBLISHED, APRIL, recurrence=MONTHLY)
    extension = relation(
        x, RelationKind.EXTENDS_DEADLINE, y, period_label="2026-09", new_due_on=date(2026, 10, 27)
    )
    published = plan(x, (extension,), (y,), siblings=(x,))
    (change,) = published.deadline_changes
    assert (change.period_label, change.new_due_on) == ("2026-09", date(2026, 10, 27))
    announced, changed = published.events(correlation_id=CorrelationId.new(), occurred_at=NOW)
    assert isinstance(changed, RuleDeadlineChanged)
    assert changed.causation_id == announced.event_id
    assert (changed.rule_id, changed.rule_version_id, changed.caused_by_rule_version_id) == (
        RULE,
        y.rule_version_id,
        x.rule_version_id,
    )
    assert changed.reason is DeadlineChangeReason.DEADLINE_EXTENDED
    assert changed.evidence_clause_id == CLAUSE
    assert changed.partition_key == str(RULE)


def test_a_superseded_target_can_still_have_its_deadline_moved() -> None:
    x = version(rule_id=OTHER_RULE)
    y = version(1, RuleVersionStatus.SUPERSEDED, APRIL, JULY)
    extension = relation(x, RelationKind.EXTENDS_DEADLINE, y, new_due_on=date(2026, 7, 31))
    (change,) = plan(x, (extension,), (y,), siblings=(x,)).deadline_changes
    assert change.period_label is None


def test_extends_deadline_needs_its_details_and_a_published_target() -> None:
    x = version(rule_id=OTHER_RULE)
    recurring = version(1, RuleVersionStatus.PUBLISHED, APRIL, recurrence=MONTHLY)
    no_date = relation(x, RelationKind.EXTENDS_DEADLINE, recurring, period_label="2026-09")
    with pytest.raises(DeadlineDetailMissingError, match="no new due date"):
        plan(x, (no_date,), (recurring,), siblings=(x,))
    no_period = relation(x, RelationKind.EXTENDS_DEADLINE, recurring, new_due_on=date(2026, 10, 27))
    with pytest.raises(DeadlineDetailMissingError, match="recurs"):
        plan(x, (no_period,), (recurring,), siblings=(x,))
    draft = version(1, RuleVersionStatus.DRAFT, APRIL)
    to_draft = relation(x, RelationKind.EXTENDS_DEADLINE, draft, new_due_on=date(2026, 10, 27))
    with pytest.raises(RelationTargetStateError, match="published or superseded"):
        plan(x, (to_draft,), (draft,), siblings=(x,))


# ---------------------------------------------------------------- overlap


def test_versions_of_the_rule_must_not_overlap_once_cut() -> None:
    x = version(effective_from=JULY)
    replaced = version(1, RuleVersionStatus.PUBLISHED, APRIL)
    plan(x, (relation(x, RelationKind.SUPERSEDES, replaced),), (replaced,))

    ended = version(1, RuleVersionStatus.SUPERSEDED, APRIL, JULY)
    draft = version(3, RuleVersionStatus.DRAFT, APRIL)
    withdrawn = version(4, RuleVersionStatus.WITHDRAWN, APRIL)
    plan(x, siblings=(x, ended, draft, withdrawn))

    later = version(5, RuleVersionStatus.PUBLISHED, NOVEMBER)
    with pytest.raises(OverlappingVersionError, match="overlaps version 5"):
        plan(x, siblings=(x, later))
    bounded = replace(x, effective_to=NOVEMBER)
    plan(bounded, siblings=(bounded, later))


# ---------------------------------------------------------------- attributes, events, sweep


def test_attribute_keys_come_from_the_predicates() -> None:
    assert attribute_keys({}) == ()
    assert attribute_keys(SPECIFICATION) == ("registration_type", "turnover_band")
    with pytest.raises(InvariantViolationError):
        attribute_keys({"colour": "blue"})


def test_plan_due_transitions_picks_the_earliest_replacement_per_target() -> None:
    target, other = RuleVersionId.new(), RuleVersionId.new()
    early, late, future = RuleVersionId.new(), RuleVersionId.new(), RuleVersionId.new()

    def pending(target_id: RuleVersionId, by: RuleVersionId, day: date) -> PendingReplacement:
        return PendingReplacement(RelationKind.SUPERSEDES, target_id, RULE, by, day)

    due = plan_due_transitions(
        [
            pending(target, late, TODAY),
            pending(target, early, JULY),
            pending(other, future, NOVEMBER),
        ],
        TODAY,
    )
    assert [(d.target_id, d.replacing_id) for d in due] == [(target, early)]
    assert due[0].moves_to is RuleVersionStatus.SUPERSEDED
    assert plan_due_transitions([pending(other, future, NOVEMBER)], NOVEMBER)[0].target_id == other
    withdrawing = PendingReplacement(RelationKind.WITHDRAWS, target, RULE, early, JULY)
    assert withdrawing.moves_to is RuleVersionStatus.WITHDRAWN


def test_transition_events_name_their_cause() -> None:
    target = RuleVersionId.new()
    withdrawn = transition_event(
        RULE,
        target,
        RuleVersionStatus.WITHDRAWN,
        by=None,
        effective_from=TODAY,
        correlation_id=CorrelationId.new(),
        causation_id=None,
        occurred_at=NOW,
    )
    assert isinstance(withdrawn, RuleWithdrawn)
    assert withdrawn.withdrawn_by_rule_version_id is None
    with pytest.raises(InvariantViolationError, match="names the version replacing it"):
        transition_event(
            RULE,
            target,
            RuleVersionStatus.SUPERSEDED,
            by=None,
            effective_from=TODAY,
            correlation_id=CorrelationId.new(),
            causation_id=EventId.new(),
            occurred_at=NOW,
        )
    with pytest.raises(InvariantViolationError, match="no event"):
        transition_event(
            RULE,
            target,
            RuleVersionStatus.PUBLISHED,
            by=RuleVersionId.new(),
            effective_from=TODAY,
            correlation_id=CorrelationId.new(),
            causation_id=None,
            occurred_at=NOW,
        )


def test_rule_events_check_their_payload() -> None:
    fields: dict[str, object] = {
        "rule_id": RULE,
        "rule_version_id": RuleVersionId.new(),
        "version": 1,
        "regulator": "CBIC",
        "title": "Title",
        "summary": "",
        "effective_from": APRIL,
        "effective_to": None,
        "supersedes": (),
        "approved_by": (ANALYST,),
        "high_impact": False,
        "attribute_keys": ("turnover_band",),
    }
    RulePublished(**fields)  # type: ignore[arg-type]
    for broken, pattern in (
        ({"approved_by": ()}, "at least one approver"),
        ({"approved_by": (ANALYST, ANALYST)}, "at least one approver"),
        ({"attribute_keys": ("Turnover",)}, "snake_case"),
        ({"attribute_keys": ("a", "a")}, "each key once"),
        ({"supersedes": (RULE,)}, "supersedes"),
        ({"title": " "}, "title"),
        ({"tenant_id": TenantId.new()}, "regulatory"),
    ):
        with pytest.raises(InvariantViolationError, match=pattern):
            RulePublished(**{**fields, **broken})  # type: ignore[arg-type]
    same = RuleVersionId.new()
    with pytest.raises(InvariantViolationError, match="each version once"):
        RulePublished(**{**fields, "supersedes": (same, same)})  # type: ignore[arg-type]


def test_a_decision_names_an_actor_or_a_cause() -> None:
    fields: dict[str, object] = {
        "decision_id": uuid4(),
        "rule_version_id": RuleVersionId.new(),
        "action": DecisionAction.SUPERSEDED,
        "from_status": RuleVersionStatus.PUBLISHED,
        "to_status": RuleVersionStatus.SUPERSEDED,
        "decided_at": NOW,
    }
    RuleVersionDecision(**fields, caused_by=RuleVersionId.new())  # type: ignore[arg-type]
    RuleVersionDecision(**fields, actor_id=ANALYST)  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="actor"):
        RuleVersionDecision(**fields)  # type: ignore[arg-type]


def test_a_quote_is_verified_by_score_and_facts() -> None:
    text = "The return in FORM GSTR-3B for September, 2026 shall be furnished by 20th October."
    assert check_quote("return in FORM GSTR-3B for September, 2026", text).verified
    wrong_year = check_quote("return in FORM GSTR-3B for September, 2027", text)
    assert wrong_year.missing == ("2027",)
    assert not wrong_year.verified
    assert not check_quote("something else entirely, not in the clause", text).verified
