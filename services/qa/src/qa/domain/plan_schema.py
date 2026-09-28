"""What the planner may answer, and reading the answer without trusting it.

The JSON schema is built per call so that every choice is closed: the operator, the entity type,
the relation kinds, the direction, the function, the comparator, the step references, and the
rule keys and regulators in force on the question's date. Each step is one flat object in which
every field is present and the ones its operator does not use are null, the same shape for
every operator, so a model with strict structured output can follow it.

``parse_plan`` checks everything the schema cannot: ids in order, references to earlier steps
only, the kind of each input, one ``answer`` last, arguments set only where the operator reads
them, business steps only with a business, and a date no later than the question's. It never
raises anything but ``PlanInvalidError``, and it lists every problem it finds so that one retry
can fix them all.
"""

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from domain_kernel.knowledge import EntityType, RelationKind, normalise_name
from qa.domain.plan import (
    COLLECTIONS,
    MAX_DEPTH,
    MAX_K,
    MAX_NAME_CHARS,
    MAX_STEPS,
    MAX_TEXT_CHARS,
    MAX_WINDOW_DAYS,
    NUMERIC_ENTITY_TYPES,
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
    StepArgs,
    ValueKind,
)

FIELDS: Final = (
    "id",
    "op",
    "entity_type",
    "name",
    "rule_key",
    "regulator",
    "source",
    "sources",
    "relations",
    "direction",
    "depth",
    "due_from",
    "due_to",
    "fn",
    "left",
    "comparator",
    "right",
    "value",
    "text",
    "k",
)
_ARGUMENTS: Final[Mapping[Op, frozenset[str]]] = {
    Op.FIND_ENTITY: frozenset({"entity_type", "name"}),
    Op.RULES_IN_FORCE: frozenset({"rule_key", "regulator", "source"}),
    Op.FOLLOW: frozenset({"source", "relations", "direction", "depth"}),
    Op.EVALUATE_APPLICABILITY: frozenset({"source"}),
    Op.GET_OBLIGATIONS: frozenset({"source", "due_from", "due_to"}),
    Op.AGGREGATE: frozenset({"source", "fn"}),
    Op.COMPARE: frozenset({"left", "comparator", "right", "value"}),
    Op.RETRIEVE_CLAUSES: frozenset({"source", "text", "k"}),
    Op.ANSWER: frozenset({"sources"}),
}
"""The fields each operator reads; every other field of its step must be null."""
_REQUIRED: Final[Mapping[Op, frozenset[str]]] = {
    Op.FIND_ENTITY: frozenset({"entity_type", "name"}),
    Op.RULES_IN_FORCE: frozenset(),
    Op.FOLLOW: frozenset({"source", "relations", "direction", "depth"}),
    Op.EVALUATE_APPLICABILITY: frozenset({"source"}),
    Op.GET_OBLIGATIONS: frozenset(),
    Op.AGGREGATE: frozenset({"source", "fn"}),
    Op.COMPARE: frozenset({"left", "comparator"}),
    Op.RETRIEVE_CLAUSES: frozenset(),
    Op.ANSWER: frozenset({"sources"}),
}
_AGGREGATE_INPUT: Final[Mapping[AggregateFn, frozenset[ValueKind]]] = {
    AggregateFn.COUNT: COLLECTIONS,
    AggregateFn.MIN_DUE: frozenset({ValueKind.OBLIGATIONS}),
    AggregateFn.MAX_DUE: frozenset({ValueKind.OBLIGATIONS}),
    AggregateFn.MIN_EFFECTIVE: frozenset({ValueKind.RULES}),
    AggregateFn.MAX_EFFECTIVE: frozenset({ValueKind.RULES}),
}
_BUSINESS_OPS: Final = frozenset({Op.EVALUATE_APPLICABILITY, Op.GET_OBLIGATIONS})
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NUMBER = "number"
_DATE = "date"


class PlanInvalidError(ValueError):
    """The planner's answer is not a valid plan; ``problems`` says why, one line each."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True, slots=True)
class PlanContext:
    """What a plan is checked against: the question's date, whether a business is in context,
    and the rule keys and regulators in force on that date."""

    as_of: date
    has_business: bool
    rule_keys: frozenset[str] = frozenset()
    regulators: frozenset[str] = frozenset()


def plan_schema(rule_keys: Sequence[str], regulators: Sequence[str]) -> dict[str, Any]:
    """The JSON schema of one planner call."""
    ref = {"type": ["string", "null"], "enum": [*STEP_IDS, None]}
    day = {"type": ["string", "null"], "format": "date"}
    step = {
        "type": "object",
        "additionalProperties": False,
        "required": list(FIELDS),
        "properties": {
            "id": {"type": "string", "enum": list(STEP_IDS)},
            "op": {"type": "string", "enum": [op.value for op in Op]},
            "entity_type": _nullable_enum([kind.value for kind in EntityType]),
            "name": {"type": ["string", "null"], "maxLength": MAX_NAME_CHARS},
            "rule_key": _nullable_enum(sorted(set(rule_keys))),
            "regulator": _nullable_enum(sorted(set(regulators))),
            "source": ref,
            "sources": {
                "type": ["array", "null"],
                "maxItems": MAX_STEPS,
                "items": {"type": "string", "enum": list(STEP_IDS)},
            },
            "relations": {
                "type": ["array", "null"],
                "maxItems": len(RelationKind),
                "items": {"type": "string", "enum": [kind.value for kind in RelationKind]},
            },
            "direction": _nullable_enum([direction.value for direction in Direction]),
            "depth": {"type": ["integer", "null"], "minimum": 1, "maximum": MAX_DEPTH},
            "due_from": day,
            "due_to": day,
            "fn": _nullable_enum([fn.value for fn in AggregateFn]),
            "left": ref,
            "comparator": _nullable_enum([comparator.value for comparator in Comparator]),
            "right": ref,
            "value": {"type": ["string", "number", "null"]},
            "text": {"type": ["string", "null"], "maxLength": MAX_TEXT_CHARS},
            "k": {"type": ["integer", "null"], "minimum": 1, "maximum": MAX_K},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "QaPlan",
        "type": "object",
        "additionalProperties": False,
        "required": ["as_of", "steps"],
        "properties": {
            "as_of": day,
            "steps": {"type": "array", "maxItems": MAX_STEPS, "items": step},
        },
    }


def parse_plan(text: str, context: PlanContext) -> Plan:
    """The plan in the planner's answer. Raises ``PlanInvalidError`` with every problem."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise PlanInvalidError([f"not JSON: {exc}"]) from exc
    return plan_from_mapping(data, context)


def plan_from_mapping(data: object, context: PlanContext) -> Plan:
    """``parse_plan`` for an already decoded answer."""
    if not isinstance(data, dict) or set(data) != {"as_of", "steps"}:
        raise PlanInvalidError(["the plan must be an object with exactly as_of and steps"])
    problems: list[str] = []
    as_of = _date(data["as_of"], "as_of", problems)
    if as_of is not None and as_of > context.as_of:
        problems.append(f"as_of {as_of} is after the question's date {context.as_of}")
    raw_steps = data["steps"]
    if not isinstance(raw_steps, list):
        raise PlanInvalidError([*problems, "steps must be a list"])
    if len(raw_steps) > MAX_STEPS:
        raise PlanInvalidError([*problems, f"a plan has at most {MAX_STEPS} steps"])
    steps: dict[str, Step] = {}
    ops: list[Op | None] = []
    for index, raw in enumerate(raw_steps):
        reader = _StepReader(index, steps, context)
        step = reader.read(raw)
        ops.append(reader.op)
        problems.extend(f"{STEP_IDS[index]}: {problem}" for problem in reader.problems)
        if step is not None:
            steps[step.id] = step
    if raw_steps:
        answers = ops.count(Op.ANSWER)
        if answers != 1:
            problems.append(f"a plan needs exactly one answer step, got {answers}")
        elif ops[-1] is not Op.ANSWER:
            problems.append("the answer step must come last")
    if problems:
        raise PlanInvalidError(problems)
    return Plan(as_of, tuple(steps.values()))


def plan_to_mapping(plan: Plan) -> dict[str, Any]:
    """The plan in the planner's own JSON shape; ``plan_from_mapping`` reads it back."""
    return {
        "as_of": None if plan.as_of is None else plan.as_of.isoformat(),
        "steps": [_step_mapping(step) for step in plan.steps],
    }


def _step_mapping(step: Step) -> dict[str, Any]:
    fields: dict[str, Any] = dict.fromkeys(FIELDS)
    fields.update(id=step.id, op=step.op.value)
    args = step.args
    match args:
        case FindEntity(entity_type=entity_type, name=name):
            fields.update(entity_type=entity_type.value, name=name)
        case RulesInForce(rule_key=rule_key, regulator=regulator, entity=entity):
            fields.update(rule_key=rule_key, regulator=regulator, source=entity)
        case Follow(source=source, relations=relations, direction=direction, depth=depth):
            fields.update(
                source=source,
                relations=[kind.value for kind in relations],
                direction=direction.value,
                depth=depth,
            )
        case EvaluateApplicability(rules=rules):
            fields.update(source=rules)
        case GetObligations(rules=rules, due_from=due_from, due_to=due_to):
            fields.update(
                source=rules,
                due_from=None if due_from is None else due_from.isoformat(),
                due_to=None if due_to is None else due_to.isoformat(),
            )
        case Aggregate(of=of, fn=fn):
            fields.update(source=of, fn=fn.value)
        case Compare(left=left, comparator=comparator, right=right, value=value):
            literal: object = value
            if isinstance(value, date):
                literal = value.isoformat()
            elif isinstance(value, Decimal):
                literal = int(value) if value == value.to_integral_value() else float(value)
            fields.update(left=left, comparator=comparator.value, right=right, value=literal)
        case RetrieveClauses(source=source, text=text, k=k):
            fields.update(source=source, text=text, k=k)
        case AnswerFrom(sources=sources):
            fields.update(sources=list(sources))
    return fields


class _StepReader:
    """Reads one step, collecting its problems; ``op`` is set once the operator is known."""

    def __init__(self, index: int, earlier: Mapping[str, Step], context: PlanContext) -> None:
        self.index = index
        self.id = STEP_IDS[index]
        self.earlier = earlier
        self.context = context
        self.problems: list[str] = []
        self.op: Op | None = None

    def read(self, raw: object) -> Step | None:
        if not isinstance(raw, dict):
            self.problems.append("a step must be an object")
            return None
        if set(raw) != set(FIELDS):
            self.problems.append(f"a step must have exactly the fields {', '.join(FIELDS)}")
            return None
        if raw["id"] != self.id:
            self.problems.append(f"id must be {self.id}, got {raw['id']!r}")
        op = self._enum(raw["op"], Op, "op")
        if op is None:
            return None
        self.op = op
        for name in FIELDS[2:]:
            if name not in _ARGUMENTS[op] and raw[name] is not None:
                self.problems.append(f"{name} must be null for {op.value}")
        for name in sorted(_REQUIRED[op]):
            if raw[name] is None:
                self.problems.append(f"{op.value} needs {name}")
        if op in _BUSINESS_OPS and not self.context.has_business:
            self.problems.append(f"{op.value} needs a business in context")
        args = self._args(op, raw)
        if self.problems or args is None:
            return None
        return Step(self.id, op, args)

    def _args(self, op: Op, raw: Mapping[str, object]) -> StepArgs | None:
        match op:
            case Op.FIND_ENTITY:
                return self._find_entity(raw)
            case Op.RULES_IN_FORCE:
                return self._rules_in_force(raw)
            case Op.FOLLOW:
                return self._follow(raw)
            case Op.EVALUATE_APPLICABILITY:
                rules = self._ref(raw["source"], "source", frozenset({ValueKind.RULES}))
                return None if rules is None else EvaluateApplicability(rules)
            case Op.GET_OBLIGATIONS:
                return self._get_obligations(raw)
            case Op.AGGREGATE:
                return self._aggregate(raw)
            case Op.COMPARE:
                return self._compare(raw)
            case Op.RETRIEVE_CLAUSES:
                return self._retrieve_clauses(raw)
            case Op.ANSWER:  # pragma: no branch - the last operator
                return self._answer(raw)

    def _find_entity(self, raw: Mapping[str, object]) -> FindEntity | None:
        entity_type = self._enum(raw["entity_type"], EntityType, "entity_type")
        name = self._text(raw["name"], "name", MAX_NAME_CHARS)
        if entity_type is None or name is None:
            return None
        canonical = _normalise(entity_type, name)
        if not canonical:
            self.problems.append(f"name {name!r} is empty once read as a {entity_type.value}")
            return None
        return FindEntity(entity_type, canonical)

    def _rules_in_force(self, raw: Mapping[str, object]) -> RulesInForce | None:
        rule_key = self._closed(raw["rule_key"], self.context.rule_keys, "rule_key")
        regulator = self._closed(raw["regulator"], self.context.regulators, "regulator")
        entity = self._ref(raw["source"], "source", frozenset({ValueKind.ENTITIES}))
        return RulesInForce(rule_key, regulator, entity)

    def _follow(self, raw: Mapping[str, object]) -> Follow | None:
        kinds = frozenset({ValueKind.RULES, ValueKind.ENTITIES})
        source = self._ref(raw["source"], "source", kinds)
        relations = self._relations(raw["relations"])
        direction = self._enum(raw["direction"], Direction, "direction")
        depth = self._int(raw["depth"], "depth", 1, MAX_DEPTH)
        if source is None or relations is None or direction is None or depth is None:
            return None
        if self.earlier[source].output is ValueKind.ENTITIES and direction is Direction.OUT:
            self.problems.append("follow from entities only goes in")
            return None
        return Follow(source, relations, direction, depth)

    def _get_obligations(self, raw: Mapping[str, object]) -> GetObligations | None:
        rules = self._ref(raw["source"], "source", frozenset({ValueKind.RULES}))
        due_from = _date(raw["due_from"], "due_from", self.problems)
        due_to = _date(raw["due_to"], "due_to", self.problems)
        if due_from is not None and due_to is not None:
            if due_from > due_to:
                self.problems.append(f"due_from {due_from} is after due_to {due_to}")
            elif (due_to - due_from).days + 1 > MAX_WINDOW_DAYS:
                self.problems.append(f"the due window is longer than {MAX_WINDOW_DAYS} days")
        return GetObligations(rules, due_from, due_to)

    def _aggregate(self, raw: Mapping[str, object]) -> Aggregate | None:
        fn = self._enum(raw["fn"], AggregateFn, "fn")
        kinds = COLLECTIONS if fn is None else _AGGREGATE_INPUT[fn]
        of = self._ref(raw["source"], "source", kinds)
        return None if fn is None or of is None else Aggregate(of, fn)

    def _compare(self, raw: Mapping[str, object]) -> Compare | None:
        comparator = self._enum(raw["comparator"], Comparator, "comparator")
        left, left_class = self._scalar(raw["left"], "left")
        if (raw["right"] is None) == (raw["value"] is None):
            self.problems.append("compare takes exactly one of right and value")
            return None
        right: str | None = None
        value: Decimal | date | None = None
        if raw["right"] is not None:
            right, right_class = self._scalar(raw["right"], "right")
            if left_class is not None and right_class is not None and left_class != right_class:
                self.problems.append(f"cannot compare a {left_class} with a {right_class}")
        elif left_class is not None:
            value = self._literal(raw["value"], left_class)
        if comparator is None or left is None or (right is None and value is None):
            return None
        return Compare(left, comparator, right, value)

    def _retrieve_clauses(self, raw: Mapping[str, object]) -> RetrieveClauses | None:
        if (raw["source"] is None) == (raw["text"] is None):
            self.problems.append("retrieve_clauses takes exactly one of source and text")
            return None
        kinds = frozenset({ValueKind.RULES, ValueKind.ENTITIES, ValueKind.OBLIGATIONS})
        source = self._ref(raw["source"], "source", kinds)
        text = self._text(raw["text"], "text", MAX_TEXT_CHARS)
        k = MAX_K if raw["k"] is None else self._int(raw["k"], "k", 1, MAX_K)
        if k is None or (source is None and text is None):
            return None
        return RetrieveClauses(source, text, k)

    def _answer(self, raw: Mapping[str, object]) -> AnswerFrom | None:
        sources = raw["sources"]
        if not isinstance(sources, list) or not sources:
            self.problems.append("sources must be a non-empty list of step ids")
            return None
        if len(set(map(repr, sources))) != len(sources):
            self.problems.append("sources must not repeat a step")
            return None
        refs = [self._ref(item, "sources", None) for item in sources]
        clean = tuple(ref for ref in refs if ref is not None)
        return AnswerFrom(clean) if len(clean) == len(refs) else None

    def _ref(self, value: object, name: str, kinds: frozenset[ValueKind] | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or value not in STEP_IDS:
            self.problems.append(f"{name} must be a step id, got {value!r}")
            return None
        if STEP_IDS.index(value) >= self.index:
            self.problems.append(f"{name} {value} is not an earlier step")
            return None
        step = self.earlier.get(value)
        if step is None:
            self.problems.append(f"{name} {value} is an invalid step")
            return None
        if kinds is not None and step.output not in kinds:
            wanted = ", ".join(sorted(kind.value for kind in kinds))
            given = "nothing" if step.output is None else step.output.value
            self.problems.append(f"{name} {value} gives {given}; this needs {wanted}")
            return None
        return value

    def _scalar(self, value: object, name: str) -> tuple[str | None, str | None]:
        """A reference to a number, a date, or a single threshold or tax rate entity, with
        what it reads as."""
        kinds = frozenset({ValueKind.NUMBER, ValueKind.DATE, ValueKind.ENTITIES})
        ref = self._ref(value, name, kinds)
        if ref is None:
            return None, None
        step = self.earlier[ref]
        if step.output is ValueKind.DATE:
            return ref, _DATE
        if step.output is ValueKind.NUMBER:
            return ref, _NUMBER
        if isinstance(step.args, FindEntity) and step.args.entity_type in NUMERIC_ENTITY_TYPES:
            return ref, _NUMBER
        self.problems.append(f"{name} {ref} must find a threshold or a tax rate to compare")
        return None, None

    def _literal(self, value: object, kind: str) -> Decimal | date | None:
        if kind == _DATE:
            return _date(value, "value", self.problems)
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.problems.append(f"value must be a number, got {value!r}")
            return None
        if not math.isfinite(value):
            self.problems.append("value must be a finite number")
            return None
        return Decimal(str(value))

    def _closed(self, value: object, allowed: frozenset[str], name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or value not in allowed:
            self.problems.append(f"{name} {value!r} is not one of the values in force")
            return None
        return value

    def _relations(self, value: object) -> tuple[RelationKind, ...] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            self.problems.append("relations must be a non-empty list")
            return None
        kinds = [self._enum(item, RelationKind, "relations") for item in value]
        clean = tuple(kind for kind in kinds if kind is not None)
        if len(clean) != len(kinds):
            return None
        if len(set(clean)) != len(clean):
            self.problems.append("relations must not repeat a kind")
            return None
        return clean

    def _enum[E: StrEnum](self, value: object, kind: type[E], name: str) -> E | None:
        if value is None:
            return None
        if not isinstance(value, str) or value not in {member.value for member in kind}:
            self.problems.append(f"{name} {value!r} is not one of the listed values")
            return None
        return kind(value)

    def _int(self, value: object, name: str, low: int, high: int) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            self.problems.append(f"{name} must be a whole number from {low} to {high}")
            return None
        return value

    def _text(self, value: object, name: str, limit: int) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            self.problems.append(f"{name} must be text of 1 to {limit} characters")
            return None
        return value.strip()


def _nullable_enum(values: Sequence[str]) -> dict[str, Any]:
    return {"type": ["string", "null"], "enum": [*values, None]}


def _date(value: object, name: str, problems: list[str]) -> date | None:
    if value is None:
        return None
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    problems.append(f"{name} must be a date as YYYY-MM-DD, got {value!r}")
    return None


def _normalise(entity_type: EntityType, name: str) -> str:
    try:
        return normalise_name(entity_type, name)
    except (ValueError, ArithmeticError):
        return ""
