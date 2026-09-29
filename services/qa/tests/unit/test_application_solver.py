"""The solver: every operator, visibility, cycles, depth, the budget, spans and failures."""

from datetime import date
from decimal import Decimal
from itertools import pairwise
from typing import Any

import pytest

from domain_kernel.knowledge import EntityType, RelationKind
from qa.application.answerer import render_evidence
from qa.application.retrieval import OUT_OF_FORCE
from qa.application.solver import Budget, SolverBudgetExceededError, SolverStepError
from qa.domain.evidence import EvidenceBundle
from qa.domain.plan import (
    Aggregate,
    AggregateFn,
    AnswerFrom,
    Comparator,
    Compare,
    Direction,
    EvaluateApplicability,
    FindEntity,
    Follow,
    GetObligations,
    Op,
    Plan,
    RetrieveClauses,
    RulesInForce,
    Step,
    StepArgs,
)

World = Any
OPS = {
    FindEntity: Op.FIND_ENTITY,
    RulesInForce: Op.RULES_IN_FORCE,
    Follow: Op.FOLLOW,
    EvaluateApplicability: Op.EVALUATE_APPLICABILITY,
    GetObligations: Op.GET_OBLIGATIONS,
    Aggregate: Op.AGGREGATE,
    Compare: Op.COMPARE,
    RetrieveClauses: Op.RETRIEVE_CLAUSES,
    AnswerFrom: Op.ANSWER,
}
EXTENDS = (RelationKind.EXTENDS_DEADLINE,)


def plan(*args: StepArgs, as_of: date | None = None) -> Plan:
    steps = (Step(f"s{n}", OPS[type(a)], a) for n, a in enumerate(args, start=1))
    return Plan(as_of, tuple(steps))


def solve(
    world: World, *args: StepArgs, budget: Budget | None = None, **ctx: Any
) -> EvidenceBundle:
    bundle: EvidenceBundle = world.solver(budget).solve(plan(*args), world.context(**ctx))
    return bundle


def facts(bundle: EvidenceBundle) -> list[str]:
    return [fact.text for fact in bundle.facts]


def steps(world: World) -> list[dict[str, Any]]:
    return [span.attributes for span in world.tracer.named("qa.solve.step")]


def test_rules_in_force_are_facts_with_one_span_per_step(world: World) -> None:
    bundle = solve(world, RulesInForce(rule_key=world.MONTHLY_RULE), AnswerFrom(("s1",)))
    assert bundle.empty
    assert facts(bundle) == [
        f"rule {world.MONTHLY_RULE} version 1 (File FORM GSTR-3B every month) is in force on "
        "2026-04-10, effective from 2026-04-01"
    ]
    assert steps(world) == [
        {
            "qa.step.id": "s1",
            "qa.step.op": "rules_in_force",
            "qa.step.hidden": 0,
            "qa.step.items": 1,
            "qa.step.status": "ok",
        },
        {
            "qa.step.id": "s2",
            "qa.step.op": "answer",
            "qa.step.hidden": 0,
            "qa.step.items": 0,
            "qa.step.status": "ok",
        },
    ]


def test_a_regulator_with_no_rules_is_empty(world: World) -> None:
    solve(world, RulesInForce(regulator="rbi"))
    assert steps(world)[0]["qa.step.status"] == "empty"


def test_a_closed_period_is_named(world: World) -> None:
    world.rulebook.add_version(
        "ended", effective_from=date(2026, 1, 1), effective_to=date(2027, 1, 1)
    )
    bundle = solve(world, RulesInForce(rule_key="ended"))
    assert facts(bundle)[0].endswith("effective from 2026-01-01 to before 2027-01-01")


def test_following_in_finds_the_extension_with_its_evidence(world: World) -> None:
    bundle = solve(
        world,
        RulesInForce(rule_key=world.MONTHLY_RULE),
        Follow("s1", EXTENDS, Direction.IN, 1),
    )
    (clause,) = bundle.clauses
    assert (clause.label, clause.clause_ref, clause.step_id, clause.source) == (
        "C1",
        "en.p3",
        "s2",
        "TEST-02",
    )
    assert facts(bundle)[1] == (
        f"rule {world.EXTENSION_RULE} version 1 extends deadline rule {world.MONTHLY_RULE} "
        "version 1 for the period 2026-03, with the new due date 2026-04-24 (evidence C1)"
    )
    assert steps(world)[1]["qa.step.items"] == 1


def test_a_version_not_in_force_is_hidden_and_counted(world: World) -> None:
    future = world.rulebook.add_version("gstr3b_future", effective_from=date(2026, 7, 1))
    world.rulebook.relate(future, RelationKind.AMENDS, world.monthly, world.draft_clause)
    bundle = solve(
        world,
        RulesInForce(rule_key=world.MONTHLY_RULE),
        Follow("s1", (RelationKind.AMENDS, RelationKind.EXTENDS_DEADLINE), Direction.IN, 1),
    )
    assert [clause.clause_ref for clause in bundle.clauses] == ["en.p3"]
    assert steps(world)[1]["qa.step.hidden"] == 1
    assert "gstr3b_future" not in " ".join(facts(bundle))


def test_following_out_reaches_versions_and_entities(world: World) -> None:
    bundle = solve(
        world,
        RulesInForce(rule_key=world.EXTENSION_RULE),
        Follow("s1", (RelationKind.EXTENDS_DEADLINE, RelationKind.REFERS_TO), Direction.OUT, 1),
    )
    assert (
        f"rule {world.EXTENSION_RULE} version 1 refers to notification test-01 (evidence C1)"
        in (facts(bundle))
    )
    assert steps(world)[1]["qa.step.items"] == 1


def test_following_in_from_an_entity(world: World) -> None:
    bundle = solve(
        world,
        FindEntity(EntityType.NOTIFICATION, "test-01"),
        Follow("s1", (RelationKind.REFERS_TO,), Direction.IN, 2),
    )
    assert facts(bundle)[0] == "notification test-01 is the known entity test-01"
    assert steps(world)[1]["qa.step.items"] == 1


def test_a_cycle_ends(world: World) -> None:
    world.rulebook.relate(
        world.monthly, RelationKind.REFERS_TO, world.extension, world.monthly_clause
    )
    world.rulebook.relate(
        world.extension, RelationKind.REFERS_TO, world.monthly, world.extension_clause
    )
    world.rulebook.calls.clear()
    bundle = solve(
        world,
        RulesInForce(rule_key=world.MONTHLY_RULE),
        Follow("s1", (RelationKind.REFERS_TO,), Direction.OUT, 3),
    )
    assert steps(world)[1]["qa.step.items"] == 1
    assert world.rulebook.calls.count("relations") == 2
    assert len(bundle.clauses) == 2


def test_depth_bounds_the_search(world: World) -> None:
    rulebook = world.rulebook
    chain = [rulebook.add_version(f"chain_{n}", effective_from=date(2026, 1, 1)) for n in range(4)]
    for newer, older in pairwise(chain):
        rulebook.relate(newer, RelationKind.SUPERSEDES, older, world.monthly_clause)
    solve(
        world,
        RulesInForce(rule_key="chain_0"),
        Follow("s1", (RelationKind.SUPERSEDES,), Direction.OUT, 2),
    )
    assert steps(world)[1]["qa.step.items"] == 2


def test_the_call_budget_stops_the_solve(world: World) -> None:
    with pytest.raises(SolverBudgetExceededError, match="more than 1 upstream calls"):
        solve(
            world,
            RulesInForce(rule_key=world.MONTHLY_RULE),
            Follow("s1", EXTENDS, Direction.IN, 1),
            budget=Budget(calls=1),
        )
    span = world.tracer.named("qa.solve.step")[1]
    assert (span.attributes["qa.step.status"], span.failed) == ("over_budget", True)


def test_the_item_budget_stops_the_solve(world: World) -> None:
    with pytest.raises(SolverBudgetExceededError, match="s1: more than 1 items"):
        solve(world, RulesInForce(), budget=Budget(items=1))


def test_applicability_from_the_profile(world: World) -> None:
    bundle = solve(world, RulesInForce(rule_key=world.MONTHLY_RULE), EvaluateApplicability("s1"))
    assert facts(bundle)[1] == (
        f"rule {world.MONTHLY_RULE} version 1 (File FORM GSTR-3B every month) applies to this "
        "business: registration_type = regular holds; filing_scheme = regular_monthly holds"
    )


@pytest.mark.parametrize(
    "specification",
    [
        {"any_of": "not a list"},
        {"attribute": "legacy_flag", "operator": "eq", "value": "x"},
        {"attribute": "filing_scheme", "operator": "gt", "value": "regular_monthly"},
    ],
)
def test_a_specification_that_cannot_be_read_is_unsure(
    world: World, specification: dict[str, object]
) -> None:
    world.rulebook.add_version("odd", effective_from=date(2026, 1, 1), specification=specification)
    world.profiles.add(
        world.TENANT,
        world.BUSINESS,
        {"filing_scheme": "regular_monthly", "legacy_flag": "x"},
    )
    bundle = solve(world, RulesInForce(rule_key="odd"), EvaluateApplicability("s1"))
    assert facts(bundle)[1] == (
        "rule odd version 1 (odd) cannot be decided for this business: its condition could not "
        "be read against the profile"
    )


def test_an_unset_attribute_is_unsure_with_its_reason(world: World) -> None:
    spec = {"attribute": "makes_inter_state_supplies", "operator": "eq", "value": True}
    world.rulebook.add_version("inter", effective_from=date(2026, 1, 1), specification=spec)
    bundle = solve(world, RulesInForce(rule_key="inter"), EvaluateApplicability("s1"))
    assert facts(bundle)[1].endswith(
        "cannot be decided for this business: makes_inter_state_supplies is not set on the profile"
    )


def test_obligations_of_hidden_versions_are_dropped(world: World) -> None:
    world.obligations.add(
        world.TENANT, world.BUSINESS, world.draft, "Draft duty", date(2026, 4, 25)
    )
    world.obligations.add(world.TENANT, world.BUSINESS, world.extension, "Other", None)
    bundle = solve(
        world,
        RulesInForce(rule_key=world.MONTHLY_RULE),
        GetObligations("s1", date(2026, 4, 1), date(2026, 4, 30)),
        GetObligations(),
    )
    assert steps(world)[1]["qa.step.hidden"] == 1
    assert steps(world)[1]["qa.step.items"] == 1
    assert steps(world)[2]["qa.step.items"] == 3
    assert facts(bundle)[1] == (
        "the obligation 'File GSTR-3B for the month (2026-03)' "
        f"(rule {world.MONTHLY_RULE} version 1) is due on 2026-04-20, status open"
    )
    assert "'Other' (rule gstr3b_extension version 1) is not dated, status open" in (
        " ".join(facts(bundle))
    )
    assert world.obligations.requests[0] == (date(2026, 4, 1), date(2026, 4, 30))


def test_obligations_need_a_business(world: World) -> None:
    with pytest.raises(SolverStepError, match="no business"):
        solve(world, GetObligations(), business=None)


@pytest.mark.parametrize(
    ("fn", "fact", "value"),
    [
        (AggregateFn.COUNT, "s1 has 2 items", Decimal(2)),
        (AggregateFn.MIN_DUE, "the earliest due date in s1 is 2026-04-20", date(2026, 4, 20)),
        (AggregateFn.MAX_DUE, "the latest due date in s1 is 2026-05-20", date(2026, 5, 20)),
    ],
)
def test_aggregates_over_obligations(
    world: World, fn: AggregateFn, fact: str, value: object
) -> None:
    bundle = solve(world, GetObligations(), Aggregate("s1", fn))
    assert fact in facts(bundle)


def test_aggregates_over_rules_and_nothing(world: World) -> None:
    bundle = solve(
        world,
        RulesInForce(),
        Aggregate("s1", AggregateFn.MIN_EFFECTIVE),
        Aggregate("s1", AggregateFn.MAX_EFFECTIVE),
        RulesInForce(regulator="rbi"),
        Aggregate("s4", AggregateFn.MIN_EFFECTIVE),
    )
    assert "the earliest effective date in s1 is 2026-03-30" in facts(bundle)
    assert "the latest effective date in s1 is 2026-04-01" in facts(bundle)
    assert "s4 has no effective date" in facts(bundle)
    assert steps(world)[4]["qa.step.status"] == "empty"


def test_comparing_a_date_with_a_literal(world: World) -> None:
    bundle = solve(
        world,
        GetObligations(),
        Aggregate("s1", AggregateFn.MIN_DUE),
        Compare("s2", Comparator.LTE, value=date(2026, 4, 24)),
        Aggregate("s1", AggregateFn.MAX_DUE),
        Compare("s2", Comparator.GT, right="s4"),
    )
    assert "2026-04-20 <= 2026-04-24 is true" in facts(bundle)
    assert "2026-04-20 > 2026-05-20 is false" in facts(bundle)


def test_comparing_a_threshold_entity(world: World) -> None:
    world.rulebook.add_entity(EntityType.THRESHOLD, "Rs. 2 crore")
    world.rulebook.add_entity(EntityType.TAX_RATE, "18%")
    bundle = solve(
        world,
        FindEntity(EntityType.THRESHOLD, "20000000"),
        Compare("s1", Comparator.GTE, value=Decimal("15000000")),
        FindEntity(EntityType.TAX_RATE, "18%"),
        Compare("s3", Comparator.EQ, value=Decimal(18)),
    )
    assert "20000000 >= 15000000 is true" in facts(bundle)
    assert "18 = 18 is true" in facts(bundle)


@pytest.mark.parametrize(
    "args",
    [
        (
            GetObligations(),
            Aggregate("s1", AggregateFn.COUNT),
            Compare("s2", Comparator.LT, value=date(2026, 1, 1)),
        ),
        (
            RulesInForce(regulator="rbi"),
            Aggregate("s1", AggregateFn.MIN_EFFECTIVE),
            Compare("s2", Comparator.LT, value=date(2026, 1, 1)),
        ),
        (FindEntity(EntityType.THRESHOLD, "1"), Compare("s1", Comparator.LT, value=Decimal(1))),
        (FindEntity(EntityType.FORM, "GSTR-3B"), Compare("s1", Comparator.LT, value=Decimal(1))),
    ],
)
def test_a_comparison_without_values_fails_the_step(
    world: World, args: tuple[StepArgs, ...]
) -> None:
    with pytest.raises(SolverStepError):
        solve(world, *args)
    assert world.tracer.named("qa.solve.step")[-1].attributes["qa.step.status"] == "failed"


def test_finding_entities(world: World) -> None:
    rulebook = world.rulebook
    rulebook.add_entity(EntityType.CIRCULAR, "1/2026", aliases=["one"])
    rulebook.add_entity(EntityType.CIRCULAR, "2/2026", aliases=["one"])
    bundle = solve(
        world,
        FindEntity(EntityType.CIRCULAR, "one"),
        FindEntity(EntityType.CIRCULAR, "3/2026"),
        FindEntity(EntityType.SECTION, "16"),
    )
    assert facts(bundle) == [
        "circular one is ambiguous: it may be any of 1/2026, 2/2026",
        "no known circular 3/2026 (not_found)",
        "no known section 16 (unqualified)",
    ]
    assert [attributes["qa.step.items"] for attributes in steps(world)] == [2, 0, 0]


def test_rules_citing_clauses_that_mention_an_entity(world: World) -> None:
    other = world.rulebook.add_version("unrelated", effective_from=date(2026, 1, 1))
    world.rulebook.cite(other, world.draft_clause, "A draft test notice")
    solve(world, FindEntity(EntityType.FORM, "GSTR 3B"), RulesInForce(entity="s1"))
    assert steps(world)[1]["qa.step.items"] == 2


def test_retrieving_by_text_passes_the_served_model(world: World) -> None:
    bundle = solve(world, RetrieveClauses(text="GSTR-3B March extended", k=1))
    assert bundle.labels == ("C1",)
    assert bundle.clauses[0].clause_id == world.extension_clause.clause_id
    (text, metadata) = world.embedder.requests[0]
    assert (text, metadata) == ("GSTR-3B March extended", {"question_id": "q1", "layer": "kag"})
    assert "qa.retrieve.lexical_only" not in steps(world)[0]


def test_retrieving_by_text_without_embeddings_is_lexical(world: World) -> None:
    world.embedder.fail = True
    bundle = solve(world, RetrieveClauses(text="GSTR-3B furnished", k=8))
    assert len(bundle.clauses) == 2
    assert steps(world)[0]["qa.retrieve.lexical_only"] is True


def test_retrieving_the_clauses_rules_and_obligations_cite(world: World) -> None:
    world.rulebook.cite(world.monthly, world.extension_clause, "unverified", verified=False)
    bundle = solve(
        world,
        RulesInForce(),
        RetrieveClauses(source="s1", k=1),
        GetObligations(),
        RetrieveClauses(source="s3", k=8),
    )
    assert [(c.label, c.step_id) for c in bundle.clauses] == [("C1", "s2"), ("C2", "s4")]
    assert bundle.clause("C2").clause_id == world.monthly_clause.clause_id  # type: ignore[union-attr]


def test_retrieving_the_clauses_that_mention_an_entity(world: World) -> None:
    bundle = solve(world, FindEntity(EntityType.FORM, "GSTR-3B"), RetrieveClauses(source="s1", k=1))
    assert len(bundle.clauses) == 1


def test_a_missing_clause_or_version_is_skipped(world: World) -> None:
    del world.rulebook.clauses[world.extension_clause.clause_id]
    bundle = solve(
        world, RulesInForce(rule_key=world.MONTHLY_RULE), Follow("s1", EXTENDS, Direction.IN, 1)
    )
    assert bundle.empty
    assert facts(bundle)[1].endswith("new due date 2026-04-24")
    world.rulebook.rule_version = lambda rule_version_id: None
    bundle = solve(world, RulesInForce(), RetrieveClauses(source="s1"))
    assert bundle.empty


def test_an_upstream_failure_fails_the_step(world: World) -> None:
    world.obligations.fail = True
    with pytest.raises(SolverStepError, match="s1: obligation: 503"):
        solve(world, GetObligations())
    assert steps(world)[0]["qa.step.status"] == "failed"


def test_rules_in_force_unreadable_fails_the_solve(world: World) -> None:
    world.rulebook.fail = True
    with pytest.raises(SolverStepError, match="rules in force on 2026-04-10"):
        solve(world, RulesInForce())


def test_the_plan_date_moves_what_is_visible(world: World) -> None:
    bundle = world.solver().solve(plan(RulesInForce(), as_of=date(2026, 3, 31)), world.context())
    assert facts(bundle) == [
        f"rule {world.EXTENSION_RULE} version 1 (GSTR-3B March 2026 extension) is in force on "
        "2026-03-31, effective from 2026-03-30"
    ]


def test_the_evidence_does_not_depend_on_the_upstream_order(world: World) -> None:
    """Relations, the candidates of an ambiguous name and obligations due on one day come back
    in the upstream's order; the bundle and the prompt are the same whichever it is."""
    rulebook = world.rulebook
    february = rulebook.add_clause(
        "The return in FORM GSTR-3B for the month of February, 2026 may be furnished till the "
        "22nd day of March, 2026.",
        clause_ref="en.p2",
        external_ref="TEST-04",
        published_at=date(2026, 3, 1),
    )
    earlier = rulebook.add_version("gstr3b_extension_2026_02", effective_from=date(2026, 3, 1))
    rulebook.relate(
        earlier,
        RelationKind.EXTENDS_DEADLINE,
        world.monthly,
        february,
        period_label="2026-02",
        new_due_on=date(2026, 3, 22),
    )
    rulebook.add_entity(EntityType.CIRCULAR, "1/2026", aliases=["one"])
    rulebook.add_entity(EntityType.CIRCULAR, "2/2026", aliases=["one"])
    world.obligations.add(
        world.TENANT, world.BUSINESS, world.monthly, "Annual statement", date(2026, 4, 20)
    )
    question_plan = plan(
        RulesInForce(rule_key=world.MONTHLY_RULE),
        Follow("s1", EXTENDS, Direction.IN, 1),
        FindEntity(EntityType.CIRCULAR, "one"),
        GetObligations(None, date(2026, 4, 1), date(2026, 5, 31)),
        AnswerFrom(("s2", "s3", "s4")),
    )
    request = world.request("Which notices extended GSTR-3B, and what is due?")
    seen = []
    for _ in range(2):
        bundle = world.solver().solve(question_plan, world.context())
        seen.append((bundle, render_evidence(request, bundle)))
        rulebook.relation_rows.reverse()
        rulebook.entities = dict(reversed(rulebook.entities.items()))
        world.obligations.rows[world.TENANT].reverse()
    assert seen[0] == seen[1]
    bundle = seen[0][0]
    assert [(clause.label, clause.source) for clause in bundle.clauses] == [
        ("C1", "TEST-04"),
        ("C2", "TEST-02"),
    ]
    assert "may be any of 1/2026, 2/2026" in seen[0][1]


def test_clauses_whose_rule_is_out_of_force_are_not_retrieved(world: World) -> None:
    rulebook = world.rulebook
    withdrawn_clause = rulebook.add_clause(
        "The return in FORM GSTR-3B for the month of March, 2025 may be furnished till the "
        "22nd day of April, 2025.",
        external_ref="TEST-00",
        published_at=date(2025, 3, 1),
    )
    withdrawn = rulebook.add_version(
        "gstr3b_extension_2025_03", effective_from=date(2025, 3, 1), status="withdrawn"
    )
    rulebook.cite(withdrawn, withdrawn_clause, "may be furnished till the 22nd day of April, 2025")
    rulebook.mentions[world.form.entity_id].append(withdrawn_clause.clause_id)
    by_text = solve(world, RetrieveClauses(text="GSTR-3B March furnished till April", k=5))
    by_entity = solve(
        world, FindEntity(EntityType.FORM, "GSTR-3B"), RetrieveClauses(source="s1", k=5)
    )
    for bundle in (by_text, by_entity):
        assert sorted(clause.source for clause in bundle.clauses) == ["TEST-01", "TEST-02"]
    retrieved = [span for span in steps(world) if span["qa.step.op"] == "retrieve_clauses"]
    assert [span[OUT_OF_FORCE] for span in retrieved] == [1, 1]
