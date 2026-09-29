"""Plans: the schema per call, the validator's rules, and a property that it never crashes."""

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from domain_kernel.knowledge import EntityType, RelationKind
from qa.domain.plan import (
    MAX_STEPS,
    STEP_IDS,
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
    ValueKind,
)
from qa.domain.plan_schema import (
    FIELDS,
    PlanContext,
    PlanInvalidError,
    parse_plan,
    plan_from_mapping,
    plan_schema,
    plan_to_mapping,
)

MONTHLY = "gstr3b_monthly"
CBIC = "cbic"
AS_OF = date(2026, 4, 10)
CONTEXT = PlanContext(AS_OF, True, frozenset({MONTHLY}), frozenset({CBIC}))


def step(number: int, op: Op, **fields: Any) -> dict[str, Any]:
    raw: dict[str, Any] = dict.fromkeys(FIELDS)
    raw.update(id=f"s{number}", op=op.value, **fields)
    return raw


def plan(*steps: dict[str, Any], as_of: str | None = None) -> dict[str, Any]:
    return {"as_of": as_of, "steps": list(steps)}


def problems_of(data: object, context: PlanContext = CONTEXT) -> tuple[str, ...]:
    with pytest.raises(PlanInvalidError) as caught:
        plan_from_mapping(data, context)
    return caught.value.problems


EVERY_OP = plan(
    step(1, Op.FIND_ENTITY, entity_type="form", name="gstr 3b"),
    step(2, Op.RULES_IN_FORCE, rule_key=MONTHLY, regulator=CBIC, source="s1"),
    step(3, Op.FOLLOW, source="s2", relations=["extends_deadline"], direction="in", depth=2),
    step(4, Op.EVALUATE_APPLICABILITY, source="s2"),
    step(5, Op.GET_OBLIGATIONS, source="s3", due_from="2026-04-01", due_to="2026-04-30"),
    step(6, Op.AGGREGATE, source="s5", fn="min_due"),
    step(7, Op.COMPARE, left="s6", comparator="lte", value="2026-04-24"),
    step(8, Op.ANSWER, sources=["s3", "s7"]),
)


def test_a_plan_with_every_kind_of_step_is_read() -> None:
    parsed = parse_plan(json.dumps(EVERY_OP), CONTEXT)
    assert parsed.as_of is None
    assert not parsed.defers
    assert [s.args for s in parsed.steps] == [
        FindEntity(EntityType.FORM, "GSTR-3B"),
        RulesInForce(MONTHLY, CBIC, "s1"),
        Follow("s2", (RelationKind.EXTENDS_DEADLINE,), Direction.IN, 2),
        EvaluateApplicability("s2"),
        GetObligations("s3", date(2026, 4, 1), date(2026, 4, 30)),
        Aggregate("s5", AggregateFn.MIN_DUE),
        Compare("s6", Comparator.LTE, None, date(2026, 4, 24)),
        AnswerFrom(("s3", "s7")),
    ]
    assert [s.output for s in parsed.steps] == [
        ValueKind.ENTITIES,
        ValueKind.RULES,
        ValueKind.RULES,
        ValueKind.DECISIONS,
        ValueKind.OBLIGATIONS,
        ValueKind.DATE,
        ValueKind.BOOLEAN,
        None,
    ]
    assert parsed.steps[6].refs() == ("s6",)
    assert parse_plan(json.dumps(plan_to_mapping(parsed)), CONTEXT) == parsed


def test_numbers_retrieval_and_plan_dates() -> None:
    parsed = plan_from_mapping(
        plan(
            step(1, Op.FIND_ENTITY, entity_type="threshold", name="Rs. 2 crore"),
            step(2, Op.COMPARE, left="s1", comparator="gt", value=15000000),
            step(3, Op.RULES_IN_FORCE),
            step(4, Op.AGGREGATE, source="s3", fn="count"),
            step(5, Op.COMPARE, left="s4", comparator="gte", right="s1"),
            step(6, Op.RETRIEVE_CLAUSES, text=" late fee for GSTR-3B ", k=4),
            step(7, Op.RETRIEVE_CLAUSES, source="s3"),
            step(8, Op.ANSWER, sources=["s2", "s6", "s7"]),
            as_of="2026-01-31",
        ),
        CONTEXT,
    )
    assert parsed.as_of == date(2026, 1, 31)
    assert parsed.steps[0].args == FindEntity(EntityType.THRESHOLD, "20000000")
    assert parsed.steps[1].args == Compare("s1", Comparator.GT, None, Decimal("15000000"))
    assert parsed.steps[4].refs() == ("s4", "s1")
    assert parsed.steps[5].args == RetrieveClauses(None, "late fee for GSTR-3B", 4)
    assert parsed.steps[6].args == RetrieveClauses("s3", None, 8)
    mapped = plan_to_mapping(parsed)
    assert mapped["steps"][1]["value"] == 15000000
    assert plan_from_mapping(mapped, CONTEXT) == parsed


def test_a_fractional_literal_round_trips() -> None:
    parsed = plan_from_mapping(
        plan(
            step(1, Op.FIND_ENTITY, entity_type="tax_rate", name="18%"),
            step(2, Op.COMPARE, left="s1", comparator="eq", value=18.5),
            step(3, Op.ANSWER, sources=["s2"]),
        ),
        CONTEXT,
    )
    assert plan_to_mapping(parsed)["steps"][1]["value"] == 18.5


def test_no_steps_defers_the_question() -> None:
    assert parse_plan('{"as_of": null, "steps": []}', CONTEXT) == Plan(None, ())
    assert Plan(None, ()).defers


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        ("[]", "exactly as_of and steps"),
        ({"steps": []}, "exactly as_of and steps"),
        (plan(as_of="2026-04-11"), "after the question's date"),
        (plan(as_of="10/04/2026"), "as_of must be a date"),
        ({"as_of": None, "steps": {}}, "steps must be a list"),
        (plan(*[step(1, Op.RULES_IN_FORCE)] * (MAX_STEPS + 1)), "at most 8 steps"),
    ],
)
def test_the_plan_as_a_whole(data: object, problem: str) -> None:
    assert any(problem in found for found in problems_of(data))


def test_not_json_is_refused() -> None:
    with pytest.raises(PlanInvalidError, match="not JSON"):
        parse_plan("plan: find it", CONTEXT)


ANSWER_2 = step(2, Op.ANSWER, sources=["s1"])


@pytest.mark.parametrize(
    ("steps", "problem"),
    [
        ([["not a step"]], "s1: a step must be an object"),
        ([{"id": "s1", "op": "answer"}], "exactly the fields"),
        ([step(2, Op.RULES_IN_FORCE), ANSWER_2], "s1: id must be s1, got 's2'"),
        ([step(1, Op.RULES_IN_FORCE, fn="count"), ANSWER_2], "fn must be null for rules_in_force"),
        ([{**step(1, Op.RULES_IN_FORCE), "op": "search"}, ANSWER_2], "op 'search' is not one"),
        ([step(1, Op.FOLLOW, source="s1"), ANSWER_2], "follow needs direction"),
        ([step(1, Op.RULES_IN_FORCE, rule_key="gstr1"), ANSWER_2], "not one of the values"),
        ([step(1, Op.RULES_IN_FORCE, regulator="rbi"), ANSWER_2], "regulator 'rbi'"),
        ([step(1, Op.RULES_IN_FORCE, source="s1"), ANSWER_2], "source s1 is not an earlier"),
        ([step(1, Op.RULES_IN_FORCE, source="s9"), ANSWER_2], "source must be a step id"),
        ([step(1, Op.FIND_ENTITY, entity_type="form", name="  "), ANSWER_2], "name must be text"),
        ([step(1, Op.FIND_ENTITY, entity_type="tax_rate", name="nil"), ANSWER_2], "empty once"),
        ([step(1, Op.FIND_ENTITY, entity_type="person", name="x"), ANSWER_2], "entity_type"),
        ([step(1, Op.RULES_IN_FORCE)], "exactly one answer step, got 0"),
        ([step(1, Op.RULES_IN_FORCE), ANSWER_2, step(3, Op.RULES_IN_FORCE)], "must come last"),
        ([step(1, Op.ANSWER, sources=["s1"])], "sources s1 is not an earlier step"),
    ],
)
def test_step_problems_are_listed(steps: list[Any], problem: str) -> None:
    assert any(problem in found for found in problems_of(plan(*steps)))


RULES_1 = step(1, Op.RULES_IN_FORCE)
ENTITY_1 = step(1, Op.FIND_ENTITY, entity_type="notification", name="17/2025-Central Tax")


@pytest.mark.parametrize(
    ("second", "problem"),
    [
        (step(2, Op.FOLLOW, source="s1", relations=[], direction="in", depth=1), "non-empty"),
        (
            step(2, Op.FOLLOW, source="s1", relations=["amends"] * 2, direction="in", depth=1),
            "must not repeat a kind",
        ),
        (step(2, Op.FOLLOW, source="s1", relations=["cites"], direction="in", depth=1), "cites"),
        (step(2, Op.FOLLOW, source="s1", relations=["amends"], direction="in", depth=4), "depth"),
        (step(2, Op.FOLLOW, source="s1", relations=["amends"], direction="up", depth=1), "'up'"),
        (step(2, Op.EVALUATE_APPLICABILITY, source="s1"), "needs rules"),
        (step(2, Op.GET_OBLIGATIONS, due_from="2026-05-01", due_to="2026-04-01"), "is after"),
        (step(2, Op.GET_OBLIGATIONS, due_from="2026-01-01", due_to="2027-01-05"), "longer than"),
        (step(2, Op.GET_OBLIGATIONS, due_to="2026-02-30"), "due_to must be a date"),
        (step(2, Op.AGGREGATE, source="s1", fn="min_due"), "needs obligations"),
        (step(2, Op.AGGREGATE, source="s1", fn="avg"), "fn 'avg'"),
        (step(2, Op.COMPARE, left="s1", comparator="lt", value=3), "threshold or a tax rate"),
        (step(2, Op.RETRIEVE_CLAUSES), "exactly one of source and text"),
        (step(2, Op.RETRIEVE_CLAUSES, text="late fee", k=9), "k must be"),
        (step(2, Op.ANSWER, sources=[]), "non-empty list"),
        (step(2, Op.ANSWER, sources=["s1", "s1"]), "must not repeat"),
    ],
)
def test_arguments_are_checked_against_an_entity_step(second: dict[str, Any], problem: str) -> None:
    found = problems_of(plan(ENTITY_1, second, step(3, Op.ANSWER, sources=["s1"])))
    assert any(problem in line for line in found), found


def test_following_out_from_entities_is_refused() -> None:
    bad = step(2, Op.FOLLOW, source="s1", relations=["amends"], direction="out", depth=1)
    assert "s2: follow from entities only goes in" in problems_of(plan(ENTITY_1, bad, ANSWER_2))


@pytest.mark.parametrize(
    ("second", "problem"),
    [
        (step(2, Op.COMPARE, left="s1", comparator="lt"), "exactly one of right and value"),
        (step(2, Op.COMPARE, left="s1", comparator="lt", right="s1", value=1), "exactly one"),
        (step(2, Op.AGGREGATE, source="s1", fn="max_effective"), None),
    ],
)
def test_compare_needs_one_right_side(second: dict[str, Any], problem: str | None) -> None:
    data = plan(RULES_1, second, step(3, Op.ANSWER, sources=["s2"]))
    if problem is None:
        assert plan_from_mapping(data, CONTEXT).steps[1].output is ValueKind.DATE
        return
    assert any(problem in line for line in problems_of(data))


def test_compare_checks_what_the_sides_read_as() -> None:
    steps = [
        RULES_1,
        step(2, Op.AGGREGATE, source="s1", fn="count"),
        step(3, Op.AGGREGATE, source="s1", fn="min_effective"),
        step(4, Op.COMPARE, left="s2", comparator="lt", right="s3"),
        step(5, Op.COMPARE, left="s3", comparator="lt", value=4),
        step(6, Op.COMPARE, left="s2", comparator="lt", value=True),
        step(7, Op.COMPARE, left="s2", comparator="lt", value=float("inf")),
        step(8, Op.ANSWER, sources=["s1"]),
    ]
    found = problems_of(plan(*steps))
    assert "s4: cannot compare a number with a date" in found
    assert "s5: value must be a date as YYYY-MM-DD, got 4" in found
    assert "s6: value must be a number, got True" in found
    assert "s7: value must be a finite number" in found


def test_business_steps_need_a_business() -> None:
    context = PlanContext(AS_OF, False, frozenset({MONTHLY}), frozenset({CBIC}))
    evaluate = step(2, Op.EVALUATE_APPLICABILITY, source="s1")
    data = plan(RULES_1, evaluate, step(3, Op.ANSWER, sources=["s2"]))
    assert "s2: evaluate_applicability needs a business in context" in problems_of(data, context)


def test_a_step_that_reads_an_invalid_step_says_so() -> None:
    data = plan(
        step(1, Op.RULES_IN_FORCE, rule_key="unknown"),
        step(2, Op.EVALUATE_APPLICABILITY, source="s1"),
        step(3, Op.ANSWER, sources=["s2"]),
    )
    assert "s2: source s1 is an invalid step" in problems_of(data)


def test_two_answers_are_refused() -> None:
    data = plan(RULES_1, ANSWER_2, step(3, Op.ANSWER, sources=["s1"]))
    assert "a plan needs exactly one answer step, got 2" in problems_of(data)


def test_the_schema_closes_every_choice() -> None:
    schema = plan_schema([MONTHLY, MONTHLY], [CBIC])
    item = schema["properties"]["steps"]["items"]
    properties = item["properties"]
    assert schema["properties"]["steps"]["maxItems"] == MAX_STEPS
    assert item["required"] == list(FIELDS)
    assert item["additionalProperties"] is False
    assert properties["rule_key"]["enum"] == [MONTHLY, None]
    assert properties["regulator"]["enum"] == [CBIC, None]
    assert properties["id"]["enum"] == list(STEP_IDS)
    assert properties["op"]["enum"] == [op.value for op in Op]
    assert properties["relations"]["items"]["enum"] == [kind.value for kind in RelationKind]
    assert None in properties["source"]["enum"]
    assert plan_schema([], [])["properties"]["steps"]["items"]["properties"]["rule_key"][
        "enum"
    ] == [None]


# ---- property: the validator never crashes, and what it accepts is well formed ---------------

USES = {
    Op.FIND_ENTITY: ("entity_type", "name"),
    Op.RULES_IN_FORCE: ("rule_key", "regulator", "source"),
    Op.FOLLOW: ("source", "relations", "direction", "depth"),
    Op.EVALUATE_APPLICABILITY: ("source",),
    Op.GET_OBLIGATIONS: ("source", "due_from", "due_to"),
    Op.AGGREGATE: ("source", "fn"),
    Op.COMPARE: ("left", "comparator", "right", "value"),
    Op.RETRIEVE_CLAUSES: ("source", "text", "k"),
    Op.ANSWER: ("sources",),
}
REFS = st.sampled_from([*STEP_IDS, "s0", "x"])
DATES = st.sampled_from(["2026-04-01", "2026-04-30", "2026-13-01", "2027-06-01", "1 May"])
POOLS: dict[str, st.SearchStrategy[Any]] = {
    "entity_type": st.sampled_from([*[t.value for t in EntityType], "person"]),
    "name": st.one_of(st.text(max_size=12), st.sampled_from(["GSTR-3B", "Rs. 2 crore", "18%"])),
    "rule_key": st.sampled_from([MONTHLY, "other"]),
    "regulator": st.sampled_from([CBIC, "rbi"]),
    "source": REFS,
    "sources": st.lists(REFS, max_size=3),
    "relations": st.lists(st.sampled_from([*[k.value for k in RelationKind], "x"]), max_size=3),
    "direction": st.sampled_from(["out", "in", "up"]),
    "depth": st.integers(-1, 4),
    "due_from": DATES,
    "due_to": DATES,
    "fn": st.sampled_from([*[f.value for f in AggregateFn], "avg"]),
    "left": REFS,
    "comparator": st.sampled_from([*[c.value for c in Comparator], "ne"]),
    "right": REFS,
    "value": st.one_of(st.integers(), st.floats(), DATES, st.booleans(), st.text(max_size=5)),
    "text": st.text(max_size=20),
    "k": st.integers(-1, 10),
}
ANYTHING = st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=5), REFS)


def odds(against: int) -> st.SearchStrategy[bool]:
    """True once in ``against + 1`` draws, drawn uniformly."""
    return st.sampled_from([*[False] * against, True])


@st.composite
def raw_steps(draw: st.DrawFn) -> list[object]:
    """Mostly plausible steps: the right id, earlier references, the operator's own fields;
    now and then something wrong."""
    count = draw(st.integers(0, MAX_STEPS + 1))
    steps: list[object] = []
    for index in range(count):
        if draw(odds(30)):
            steps.append(draw(ANYTHING))
            continue
        earlier = st.sampled_from(STEP_IDS[: min(index, MAX_STEPS)]) if index else REFS
        refs = st.one_of(earlier, earlier, earlier, REFS)
        last = index == count - 1
        ops = st.sampled_from([op for op in Op if op is not Op.ANSWER])
        op = Op.ANSWER if last and not draw(odds(4)) else draw(ops)
        raw: dict[str, object] = dict.fromkeys(FIELDS)
        own = STEP_IDS[index] if index < MAX_STEPS else "s9"
        raw["id"] = draw(REFS) if draw(odds(20)) else own
        raw["op"] = op.value
        for name in USES[op]:
            if not draw(odds(6)):
                pool = POOLS[name]
                if name in {"source", "left", "right"}:
                    pool = refs
                elif name == "sources":
                    pool = st.lists(refs, min_size=1, max_size=3)
                raw[name] = draw(pool)
        if draw(odds(20)):
            name = draw(st.sampled_from(FIELDS[2:]))
            raw[name] = draw(POOLS[name])
        if draw(odds(40)):
            raw.pop(draw(st.sampled_from(FIELDS)))
        steps.append(raw)
    return steps


BASES = [
    EVERY_OP["steps"],
    [
        step(1, Op.FIND_ENTITY, entity_type="threshold", name="Rs. 2 crore"),
        step(2, Op.RULES_IN_FORCE, source="s1"),
        step(3, Op.AGGREGATE, source="s2", fn="count"),
        step(4, Op.COMPARE, left="s3", comparator="gt", right="s1"),
        step(5, Op.RETRIEVE_CLAUSES, source="s2", k=3),
        step(6, Op.ANSWER, sources=["s4", "s5"]),
    ],
]


@st.composite
def mutated_steps(draw: st.DrawFn) -> list[object]:
    """A valid plan with a few fields changed, a step dropped, or two steps swapped."""
    steps: list[dict[str, object]] = [dict(item) for item in draw(st.sampled_from(BASES))]
    for _ in range(draw(st.integers(0, 3))):
        index = draw(st.integers(0, len(steps) - 1))
        match draw(st.sampled_from(["field", "field", "drop", "swap"])):
            case "field":
                name = draw(st.sampled_from(FIELDS[2:]))
                steps[index][name] = draw(st.one_of(st.none(), POOLS[name]))
            case "drop" if len(steps) > 1:
                steps.pop(index)
            case "swap":
                other = draw(st.integers(0, len(steps) - 1))
                steps[index], steps[other] = steps[other], steps[index]
    return list(steps)


@given(
    steps=st.one_of(raw_steps(), mutated_steps()),
    as_of=st.one_of(st.none(), DATES),
    business=st.booleans(),
)
@settings(max_examples=500, deadline=None)
def test_the_validator_never_crashes(
    steps: list[object], as_of: str | None, business: bool
) -> None:
    context = PlanContext(AS_OF, business, frozenset({MONTHLY}), frozenset({CBIC}))
    try:
        parsed = parse_plan(json.dumps({"as_of": as_of, "steps": steps}), context)
    except PlanInvalidError as exc:
        problems = exc.problems
        assert problems
        return
    seen: set[str] = set()
    for index, accepted in enumerate(parsed.steps):
        assert isinstance(accepted, Step)
        assert accepted.id == STEP_IDS[index]
        assert set(accepted.refs()) <= seen
        seen.add(accepted.id)
    if parsed.steps:
        assert [s.op for s in parsed.steps].count(Op.ANSWER) == 1
        assert parsed.steps[-1].op is Op.ANSWER
    assert plan_from_mapping(plan_to_mapping(parsed), context) == parsed
