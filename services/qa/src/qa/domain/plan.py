"""The logical form of a question: a short plan of typed steps that the solver runs against the
rulebook, the profile and the obligations without a model call (ADR-017).

A plan is at most ``MAX_STEPS`` steps named ``s1``, ``s2`` and so on in order. A step reads
only the output of earlier steps, and every output has a kind (entities, rules, decisions,
obligations, clauses, a number, a date or a boolean) that the next step's operator checks.
There is exactly one ``answer`` step and it comes last. A plan with no steps defers the
question to hybrid search. ``plan_schema.parse_plan`` builds plans from the planner's answer
and is the only place that checks these rules.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final

from domain_kernel.knowledge import EntityType, RelationKind

MAX_STEPS: Final = 8
MAX_DEPTH: Final = 3
MAX_NAME_CHARS: Final = 120
MAX_TEXT_CHARS: Final = 300
MAX_K: Final = 8
MAX_WINDOW_DAYS: Final = 366
"""The longest due window ``get_obligations`` may ask for, as the obligation service allows."""
STEP_IDS: Final = tuple(f"s{number}" for number in range(1, MAX_STEPS + 1))


class Op(StrEnum):
    FIND_ENTITY = "find_entity"
    RULES_IN_FORCE = "rules_in_force"
    FOLLOW = "follow"
    EVALUATE_APPLICABILITY = "evaluate_applicability"
    GET_OBLIGATIONS = "get_obligations"
    AGGREGATE = "aggregate"
    COMPARE = "compare"
    RETRIEVE_CLAUSES = "retrieve_clauses"
    ANSWER = "answer"


class ValueKind(StrEnum):
    """What a step's output holds."""

    ENTITIES = "entities"
    RULES = "rules"
    DECISIONS = "decisions"
    OBLIGATIONS = "obligations"
    CLAUSES = "clauses"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"


class Direction(StrEnum):
    """``out`` follows relations from a rule version, ``in`` the relations pointing at it."""

    OUT = "out"
    IN = "in"


class AggregateFn(StrEnum):
    COUNT = "count"
    MIN_DUE = "min_due"
    MAX_DUE = "max_due"
    MIN_EFFECTIVE = "min_effective"
    MAX_EFFECTIVE = "max_effective"


class Comparator(StrEnum):
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    EQ = "eq"


COLLECTIONS: Final = frozenset(
    {
        ValueKind.ENTITIES,
        ValueKind.RULES,
        ValueKind.DECISIONS,
        ValueKind.OBLIGATIONS,
        ValueKind.CLAUSES,
    }
)
NUMERIC_ENTITY_TYPES: Final = frozenset({EntityType.THRESHOLD, EntityType.TAX_RATE})
"""A single entity of these types reads as a number in ``compare``: rupees or a percentage."""

OUTPUT_KIND: Final[Mapping[Op, ValueKind]] = {
    Op.FIND_ENTITY: ValueKind.ENTITIES,
    Op.RULES_IN_FORCE: ValueKind.RULES,
    Op.FOLLOW: ValueKind.RULES,
    Op.EVALUATE_APPLICABILITY: ValueKind.DECISIONS,
    Op.GET_OBLIGATIONS: ValueKind.OBLIGATIONS,
    Op.COMPARE: ValueKind.BOOLEAN,
    Op.RETRIEVE_CLAUSES: ValueKind.CLAUSES,
}
"""The output of every operator but ``aggregate``, whose output depends on its function, and
``answer``, which nothing reads."""

AGGREGATE_KIND: Final[Mapping[AggregateFn, ValueKind]] = {
    AggregateFn.COUNT: ValueKind.NUMBER,
    AggregateFn.MIN_DUE: ValueKind.DATE,
    AggregateFn.MAX_DUE: ValueKind.DATE,
    AggregateFn.MIN_EFFECTIVE: ValueKind.DATE,
    AggregateFn.MAX_EFFECTIVE: ValueKind.DATE,
}


@dataclass(frozen=True, slots=True)
class FindEntity:
    """Resolve a name to canonical entities; ``name`` is already normalised for its type."""

    entity_type: EntityType
    name: str


@dataclass(frozen=True, slots=True)
class RulesInForce:
    """The rule versions in force on the plan's date, optionally one rule, one regulator, or
    the ones citing a clause that mentions an entity of step ``entity``."""

    rule_key: str | None = None
    regulator: str | None = None
    entity: str | None = None


@dataclass(frozen=True, slots=True)
class Follow:
    """Rule versions reached over the given relations, breadth first, up to ``depth`` hops."""

    source: str
    relations: tuple[RelationKind, ...]
    direction: Direction
    depth: int


@dataclass(frozen=True, slots=True)
class EvaluateApplicability:
    rules: str


@dataclass(frozen=True, slots=True)
class GetObligations:
    """The business's obligations due in the window (days in India, both ends included),
    optionally only those of the rule versions of step ``rules``."""

    rules: str | None = None
    due_from: date | None = None
    due_to: date | None = None


@dataclass(frozen=True, slots=True)
class Aggregate:
    of: str
    fn: AggregateFn


@dataclass(frozen=True, slots=True)
class Compare:
    """``left comparator right``, where ``right`` is a step or the literal ``value``."""

    left: str
    comparator: Comparator
    right: str | None = None
    value: Decimal | date | None = None


@dataclass(frozen=True, slots=True)
class RetrieveClauses:
    """Clauses cited by the rules (or the obligations' rules) of step ``source``, mentioning
    its entities, or found by searching ``text``."""

    source: str | None = None
    text: str | None = None
    k: int = MAX_K


@dataclass(frozen=True, slots=True)
class AnswerFrom:
    """The last step: phrase the answer from the evidence of these steps."""

    sources: tuple[str, ...]


type StepArgs = (
    FindEntity
    | RulesInForce
    | Follow
    | EvaluateApplicability
    | GetObligations
    | Aggregate
    | Compare
    | RetrieveClauses
    | AnswerFrom
)


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    op: Op
    args: StepArgs

    def refs(self) -> tuple[str, ...]:
        """The ids of the earlier steps this step reads, in argument order."""
        args = self.args
        match args:
            case RulesInForce(entity=entity):
                return () if entity is None else (entity,)
            case Follow(source=source):
                return (source,)
            case EvaluateApplicability(rules=rules):
                return (rules,)
            case GetObligations(rules=rules):
                return () if rules is None else (rules,)
            case Aggregate(of=of):
                return (of,)
            case Compare(left=left, right=right):
                return (left,) if right is None else (left, right)
            case RetrieveClauses(source=source):
                return () if source is None else (source,)
            case AnswerFrom(sources=sources):
                return sources
        return ()

    @property
    def output(self) -> ValueKind | None:
        """What the step's output holds; ``None`` for the answer step."""
        if isinstance(self.args, Aggregate):
            return AGGREGATE_KIND[self.args.fn]
        return OUTPUT_KIND.get(self.op)


@dataclass(frozen=True, slots=True)
class Plan:
    """``as_of`` moves the date the rules are read for, never past the question's own date."""

    as_of: date | None
    steps: tuple[Step, ...]

    @property
    def defers(self) -> bool:
        """No steps: the planner hands the question to hybrid search."""
        return not self.steps
