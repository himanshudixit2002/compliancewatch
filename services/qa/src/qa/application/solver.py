"""The solver: runs a validated plan against the rulebook, the profile and the obligations,
deterministically and without a model call (ADR-017).

Each step is one ``qa.solve.step`` span with its id, operator, item count, hidden count and
status. A question may make ``Budget.calls`` upstream calls in all and a step may produce
``Budget.items`` items; going over either stops the solve (``SolverBudgetExceededError``). A
step that cannot run (nothing to compare, an upstream failure) stops it too
(``SolverStepError``); the question then falls back to hybrid search.

Only the rule versions in force on the plan's date are visible. A version reached any other way
(the far end of a relation, an obligation's version) is dropped when it is not in that set, and
the drop is counted on the step's span; so is a retrieved clause the rulebook marks out of
force on that date (``qa.retrieve.out_of_force``). ``follow`` is breadth first with a visited
set, so a cycle of relations ends. Applicability is the kernel's ``Specification.evaluate`` with
the injected ontology, standing in until the applicability engine has an API; a specification that
does not parse or names an unknown attribute gives an ``unsure`` fact, never a crash.

The bundle holds every clause the solver touched as evidence (relation evidence and retrieved
clauses), in step order, and one fact per finding. Collections the upstream services return in
an order of their own (relations, the candidates of an ambiguous name, obligations due on the
same day) are sorted first, so the labels and the prompt do not depend on it; search hits and
entity clauses keep the order they were ranked in.
"""

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from domain_kernel.errors import DomainError
from domain_kernel.ids import CanonicalEntityId, ClauseId, RuleVersionId
from domain_kernel.knowledge import EntityType
from domain_kernel.ontology import Ontology
from domain_kernel.predicates import Applicability, evaluate_predicate, specification_from_mapping
from qa.application.context import AskContext
from qa.application.retrieval import OUT_OF_FORCE, search_clauses
from qa.domain.answer import Layer
from qa.domain.errors import DependencyUnavailableError
from qa.domain.evidence import BundleBuilder, EvidenceBundle
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
    Plan,
    RetrieveClauses,
    RulesInForce,
    Step,
    ValueKind,
)
from qa.domain.ports import (
    ClauseSearch,
    Embedder,
    ObligationReader,
    RulebookReader,
    Span,
    Tracer,
)
from qa.domain.records import (
    ClauseRecord,
    Entity,
    ObligationRecord,
    Relation,
    ResolutionStatus,
    RuleVersion,
    RuleVersionDetail,
)

STEP_SPAN: Final = "qa.solve.step"
ENTITY_CLAUSES: Final = 50
"""How many clauses mentioning an entity ``rules_in_force`` looks at."""
_COMPARE: Final[Mapping[Comparator, tuple[str, Callable[[Any, Any], bool]]]] = {
    Comparator.LT: ("<", operator.lt),
    Comparator.LTE: ("<=", operator.le),
    Comparator.GT: (">", operator.gt),
    Comparator.GTE: (">=", operator.ge),
    Comparator.EQ: ("=", operator.eq),
}
_VERDICT: Final = {
    Applicability.APPLIES: "applies to",
    Applicability.NOT_APPLICABLE: "does not apply to",
    Applicability.UNSURE: "cannot be decided for",
}


class SolverStepError(RuntimeError):
    """A step could not run; the question falls back."""


class SolverBudgetExceededError(RuntimeError):
    """The plan needs more upstream calls, or a step more items, than the budget allows."""


@dataclass(frozen=True, slots=True)
class Budget:
    calls: int = 40
    items: int = 50


@dataclass(frozen=True, slots=True)
class Decision:
    rule: RuleVersion
    outcome: Applicability


@dataclass(frozen=True, slots=True)
class StepValue:
    """A step's output: the collection its kind names, or one scalar."""

    kind: ValueKind | None
    entities: tuple[Entity, ...] = ()
    rules: tuple[RuleVersion, ...] = ()
    decisions: tuple[Decision, ...] = ()
    obligations: tuple[ObligationRecord, ...] = ()
    clauses: tuple[ClauseRecord, ...] = ()
    scalar: Decimal | date | bool | None = None

    @property
    def size(self) -> int:
        collected = (self.entities, self.rules, self.decisions, self.obligations, self.clauses)
        return sum(map(len, collected)) + (self.scalar is not None)


class Solver:
    def __init__(
        self,
        *,
        rulebook: RulebookReader,
        search: ClauseSearch,
        embedder: Embedder,
        obligations: ObligationReader,
        ontology: Ontology,
        tracer: Tracer,
        budget: Budget = Budget(),  # noqa: B008 - frozen default
    ) -> None:
        self.rulebook = rulebook
        self.search = search
        self.embedder = embedder
        self.obligations = obligations
        self.ontology = ontology
        self.tracer = tracer
        self.budget = budget

    def solve(self, plan: Plan, ctx: AskContext) -> EvidenceBundle:
        as_of = plan.as_of or ctx.request.as_of
        try:
            visible = ctx.visible(as_of)
        except DependencyUnavailableError as exc:
            raise SolverStepError(f"rules in force on {as_of}: {exc}") from exc
        run = _Run(self, ctx, as_of, visible)
        for step in plan.steps:
            with self.tracer.span(
                STEP_SPAN, {"qa.step.id": step.id, "qa.step.op": step.op.value}
            ) as span:
                run.start(step)
                try:
                    value = run.execute(step, span)
                except SolverBudgetExceededError:
                    span.set_attribute("qa.step.status", "over_budget")
                    raise
                except SolverStepError:
                    span.set_attribute("qa.step.status", "failed")
                    raise
                except DependencyUnavailableError as exc:
                    span.set_attribute("qa.step.status", "failed")
                    raise SolverStepError(f"{step.id}: {exc}") from exc
                finally:
                    span.set_attribute("qa.step.hidden", run.hidden)
                empty = value.size == 0 and value.kind is not None
                span.set_attribute("qa.step.items", value.size)
                span.set_attribute("qa.step.status", "empty" if empty else "ok")
                run.values[step.id] = value
        return run.builder.build()


class _Run:
    """The state of one solve: step outputs, the bundle, the call count and read caches."""

    def __init__(
        self,
        solver: Solver,
        ctx: AskContext,
        as_of: date,
        visible: Mapping[RuleVersionId, RuleVersion],
    ) -> None:
        self.solver = solver
        self.ctx = ctx
        self.as_of = as_of
        self.visible = visible
        self.values: dict[str, StepValue] = {}
        self.builder = BundleBuilder()
        self.calls = 0
        self.hidden = 0
        self.step_id = ""
        self._details: dict[RuleVersionId, RuleVersionDetail | None] = {}
        self._clauses: dict[ClauseId, ClauseRecord | None] = {}

    def start(self, step: Step) -> None:
        self.step_id = step.id
        self.hidden = 0

    def execute(self, step: Step, span: Span) -> StepValue:
        args = step.args
        match args:
            case FindEntity():
                return self.find_entity(args)
            case RulesInForce():
                return self.rules_in_force(args)
            case Follow():
                return self.follow(args)
            case EvaluateApplicability():
                return self.evaluate(args)
            case GetObligations():
                return self.get_obligations(args)
            case Aggregate():
                return self.aggregate(args)
            case Compare():
                return self.compare(args)
            case RetrieveClauses():
                return self.retrieve(args, span)
            case AnswerFrom():  # pragma: no branch - the last kind of step
                return StepValue(None)

    # ---- budget, facts and cached reads ----------------------------------------------------

    def call(self) -> None:
        self.calls += 1
        if self.calls > self.solver.budget.calls:
            raise SolverBudgetExceededError(
                f"{self.step_id}: more than {self.solver.budget.calls} upstream calls"
            )

    def items(self, count: int) -> None:
        if count > self.solver.budget.items:
            raise SolverBudgetExceededError(
                f"{self.step_id}: more than {self.solver.budget.items} items"
            )

    def fact(self, text: str) -> None:
        self.builder.add_fact(self.step_id, text)

    def detail(self, rule_version_id: RuleVersionId) -> RuleVersionDetail | None:
        if rule_version_id not in self._details:
            self.call()
            self._details[rule_version_id] = self.solver.rulebook.rule_version(rule_version_id)
        return self._details[rule_version_id]

    def clause(self, clause_id: ClauseId) -> ClauseRecord | None:
        if clause_id not in self._clauses:
            self.call()
            self._clauses[clause_id] = self.solver.rulebook.clause(clause_id)
        return self._clauses[clause_id]

    def evidence(self, clause: ClauseRecord) -> str | None:
        return self.builder.add_clause(
            clause_id=clause.clause_id,
            document_id=clause.document_id,
            clause_ref=clause.clause_ref,
            text=clause.text,
            step_id=self.step_id,
            source=clause.source,
        )

    # ---- operators --------------------------------------------------------------------------

    def find_entity(self, args: FindEntity) -> StepValue:
        self.call()
        found = self.solver.rulebook.resolve_entity(args.entity_type, args.name)
        named = f"{args.entity_type.value} {args.name}"
        entities: tuple[Entity, ...] = ()
        if found.status is ResolutionStatus.RESOLVED and found.entity is not None:
            entities = (found.entity,)
            self.fact(f"{named} is the known entity {found.entity.canonical_name}")
        elif found.status is ResolutionStatus.AMBIGUOUS:
            entities = tuple(sorted(found.candidates, key=_entity_order))
            names = ", ".join(entity.canonical_name for entity in entities)
            self.fact(f"{named} is ambiguous: it may be any of {names}")
        else:
            self.fact(f"no known {named} ({found.status.value})")
        self.items(len(entities))
        return StepValue(ValueKind.ENTITIES, entities=entities)

    def rules_in_force(self, args: RulesInForce) -> StepValue:
        rules = sorted(
            (
                version
                for version in self.visible.values()
                if args.rule_key in (None, version.rule_key)
                and args.regulator in (None, version.regulator)
            ),
            key=lambda version: version.rule_key,
        )
        if args.entity is not None:
            mentioned: set[ClauseId] = set()
            for entity in self.values[args.entity].entities:
                self.call()
                clauses = self.solver.rulebook.entity_clauses(
                    entity.entity_id, as_of=self.as_of, limit=ENTITY_CLAUSES
                )
                mentioned.update(clause.clause_id for clause in clauses)
            rules = [rule for rule in rules if self._cites_any(rule, mentioned)]
        self.items(len(rules))
        for rule in rules:
            period = f"effective from {rule.effective_from.isoformat()}"
            if rule.effective_to is not None:
                period += f" to before {rule.effective_to.isoformat()}"
            self.fact(f"{rule.label} ({rule.title}) is in force on {self.as_of}, {period}")
        return StepValue(ValueKind.RULES, rules=tuple(rules))

    def _cites_any(self, rule: RuleVersion, clause_ids: set[ClauseId]) -> bool:
        detail = self.detail(rule.rule_version_id)
        return detail is not None and any(
            citation.verified and citation.clause_id in clause_ids for citation in detail.citations
        )

    def follow(self, args: Follow) -> StepValue:
        source = self.values[args.source]
        frontier: list[RuleVersionId | CanonicalEntityId] = [
            entity.entity_id for entity in source.entities
        ] + [rule.rule_version_id for rule in source.rules]
        visited: set[RuleVersionId | CanonicalEntityId] = set(frontier)
        found: list[RuleVersion] = []
        wanted = set(args.relations)
        for _ in range(args.depth):
            reached: list[RuleVersionId | CanonicalEntityId] = []
            for node in frontier:
                for relation in self._relations(node, args.direction):
                    if relation.relation not in wanted:
                        continue
                    target = self._far_end(relation, args.direction)
                    if target is None:
                        self._record(relation)
                        continue
                    version = self.visible.get(target)
                    if version is None:
                        self.hidden += 1
                        continue
                    self._record(relation)
                    if target in visited:
                        continue
                    visited.add(target)
                    found.append(version)
                    reached.append(target)
                    self.items(len(found))
            frontier = reached
            if not frontier:
                break
        return StepValue(ValueKind.RULES, rules=tuple(sorted(found, key=_rule_order)))

    def _relations(
        self, node: RuleVersionId | CanonicalEntityId, direction: Direction
    ) -> list[Relation]:
        """The node's relations, ordered by the version at their far end (effective date, rule
        key), then by kind, target, period and evidence."""
        self.call()
        rulebook = self.solver.rulebook
        if isinstance(node, CanonicalEntityId):
            found = rulebook.relations(to_entity_id=node)
        elif direction is Direction.OUT:
            found = rulebook.relations(from_rule_version_id=node)
        else:
            found = rulebook.relations(to_rule_version_id=node)

        def order(relation: Relation) -> tuple[date, str, str, str, str, str, str, str]:
            target = self._far_end(relation, direction)
            version = None if target is None else self.visible.get(target)
            return (
                date.min if version is None else version.effective_from,
                "" if version is None else version.rule_key,
                relation.relation.value,
                relation.to_kind,
                relation.to_ref,
                relation.period_label or "",
                relation.evidence_clause_ref,
                str(relation.evidence_clause_id),
            )

        return sorted(found, key=order)

    @staticmethod
    def _far_end(relation: Relation, direction: Direction) -> RuleVersionId | None:
        """The rule version the relation leads to; ``None`` for an entity reached going out."""
        if direction is Direction.IN:
            return relation.from_rule_version_id
        return relation.to_rule_version_id

    def _record(self, relation: Relation) -> None:
        """The relation as a fact, and its evidence clause in the bundle."""
        clause = self.clause(relation.evidence_clause_id)
        label = None if clause is None else self.evidence(clause)
        source = self.visible.get(relation.from_rule_version_id)
        subject = "a rule version" if source is None else source.label
        if relation.to_rule_version_id is not None:
            target = self.visible.get(relation.to_rule_version_id)
            obj = "a rule version" if target is None else target.label
        else:
            obj = f"{relation.to_kind} {relation.to_ref}"
        text = f"{subject} {relation.relation.value.replace('_', ' ')} {obj}"
        if relation.period_label:
            text += f" for the period {relation.period_label}"
        if relation.new_due_on is not None:
            text += f", with the new due date {relation.new_due_on.isoformat()}"
        if label is not None:
            text += f" (evidence {label})"
        self.fact(text)

    def evaluate(self, args: EvaluateApplicability) -> StepValue:
        attributes = self.ctx.profile().attributes
        decisions: list[Decision] = []
        for rule in self.values[args.rules].rules:
            outcome, reasons = self._applicability(rule, attributes)
            decisions.append(Decision(rule, outcome))
            self.fact(
                f"{rule.label} ({rule.title}) {_VERDICT[outcome]} this business: "
                + "; ".join(reasons)
            )
        return StepValue(ValueKind.DECISIONS, decisions=tuple(decisions))

    def _applicability(
        self, rule: RuleVersion, attributes: Mapping[str, object]
    ) -> tuple[Applicability, list[str]]:
        ontology = self.solver.ontology
        try:
            specification = specification_from_mapping(dict(rule.specification))
            outcome = specification.evaluate(attributes, ontology)
            reasons = [
                evaluate_predicate(predicate, attributes, ontology).reason
                for predicate in specification.predicates()
            ]
        except (DomainError, ValueError, TypeError, LookupError):
            return Applicability.UNSURE, ["its condition could not be read against the profile"]
        return outcome, reasons

    def get_obligations(self, args: GetObligations) -> StepValue:
        request = self.ctx.request
        if request.business is None:
            raise SolverStepError(f"{self.step_id}: no business in context")
        self.call()
        found = self.solver.obligations.obligations(
            request.tenant, request.business, due_from=args.due_from, due_to=args.due_to
        )
        allowed = None
        if args.rules is not None:
            allowed = {rule.rule_version_id for rule in self.values[args.rules].rules}
        kept: list[ObligationRecord] = []
        for obligation in sorted(found, key=_obligation_order):
            if obligation.rule_version_id not in self.visible:
                self.hidden += 1
            elif allowed is None or obligation.rule_version_id in allowed:
                kept.append(obligation)
        self.items(len(kept))
        for obligation in kept:
            due = obligation.due_on
            rule = self.visible[obligation.rule_version_id]
            self.fact(
                f"the obligation {obligation.title!r} ({rule.label}) is "
                + ("not dated" if due is None else f"due on {due.isoformat()}")
                + f", status {obligation.status.value}"
            )
        return StepValue(ValueKind.OBLIGATIONS, obligations=tuple(kept))

    def aggregate(self, args: Aggregate) -> StepValue:
        source = self.values[args.of]
        if args.fn is AggregateFn.COUNT:
            self.fact(f"{args.of} has {source.size} items")
            return StepValue(ValueKind.NUMBER, scalar=Decimal(source.size))
        if args.fn in (AggregateFn.MIN_DUE, AggregateFn.MAX_DUE):
            days = [item.due_on for item in source.obligations if item.due_on is not None]
            what = "due date"
        else:
            days = [rule.effective_from for rule in source.rules]
            what = "effective date"
        if not days:
            self.fact(f"{args.of} has no {what}")
            return StepValue(ValueKind.DATE)
        first = args.fn in (AggregateFn.MIN_DUE, AggregateFn.MIN_EFFECTIVE)
        day = min(days) if first else max(days)
        self.fact(f"the {'earliest' if first else 'latest'} {what} in {args.of} is {day}")
        return StepValue(ValueKind.DATE, scalar=day)

    def compare(self, args: Compare) -> StepValue:
        left = self._scalar(args.left)
        right = self._scalar(args.right) if args.right is not None else args.value
        if left is None or right is None:
            raise SolverStepError(f"{self.step_id}: nothing to compare")
        if isinstance(left, date) != isinstance(right, date):
            raise SolverStepError(f"{self.step_id}: cannot compare a date with a number")
        symbol, check = _COMPARE[args.comparator]
        result = bool(check(left, right))
        self.fact(f"{left} {symbol} {right} is {'true' if result else 'false'}")
        return StepValue(ValueKind.BOOLEAN, scalar=result)

    def _scalar(self, ref: str) -> Decimal | date | None:
        value = self.values[ref]
        if value.kind is ValueKind.ENTITIES:
            if len(value.entities) != 1:
                raise SolverStepError(f"{self.step_id}: {ref} is not one entity")
            return _amount(value.entities[0])
        if isinstance(value.scalar, bool):
            return None
        return value.scalar

    def retrieve(self, args: RetrieveClauses, span: Span) -> StepValue:
        found: list[ClauseRecord] = []
        if args.text is not None:
            self.call()
            self.call()
            hits = search_clauses(
                self.solver.search,
                self.solver.embedder,
                self.ctx,
                args.text,
                as_of=self.as_of,
                k=args.k,
                layer=Layer.KAG,
                span=span,
            )
            found = [hit.clause for hit in hits]
        elif args.source is not None:  # pragma: no branch - the plan names one of the two
            found = self._clauses_of(self.values[args.source], args.k, span)
        clauses = list({clause.clause_id: clause for clause in found}.values())[: args.k]
        self.items(len(clauses))
        for clause in clauses:
            self.evidence(clause)
        return StepValue(ValueKind.CLAUSES, clauses=tuple(clauses))

    def _clauses_of(self, source: StepValue, k: int, span: Span) -> list[ClauseRecord]:
        """An entity's clauses in force, then the verified citations of the rules."""
        found: list[ClauseRecord] = []
        dropped = 0
        for entity in source.entities:
            if len(found) >= k:
                break
            self.call()
            mentioning = self.solver.rulebook.entity_clauses(
                entity.entity_id, as_of=self.as_of, limit=k
            )
            kept = [clause for clause in mentioning if not clause.out_of_force]
            dropped += len(mentioning) - len(kept)
            found.extend(kept)
        if dropped:
            span.set_attribute(OUT_OF_FORCE, dropped)
        rule_ids = [rule.rule_version_id for rule in source.rules] + [
            item.rule_version_id for item in source.obligations
        ]
        for rule_version_id in dict.fromkeys(rule_ids):
            detail = self.detail(rule_version_id)
            for citation in () if detail is None else detail.citations:
                if len(found) >= k:
                    return found
                clause = self.clause(citation.clause_id) if citation.verified else None
                if clause is not None:
                    found.append(clause)
        return found


def _entity_order(entity: Entity) -> tuple[str, str, str]:
    return (entity.entity_type.value, entity.canonical_name, str(entity.entity_id))


def _rule_order(rule: RuleVersion) -> tuple[date, str, int, str]:
    return (rule.effective_from, rule.rule_key, rule.version, str(rule.rule_version_id))


def _obligation_order(obligation: ObligationRecord) -> tuple[bool, date, str, str, str]:
    """Due first, undated last, then by title and period."""
    due = obligation.due_on
    return (
        due is None,
        due or date.min,
        obligation.title,
        obligation.period_label or "",
        str(obligation.obligation_id),
    )


def _amount(entity: Entity) -> Decimal | None:
    """A threshold's rupees or a tax rate's percentage, from its canonical name."""
    if entity.entity_type not in (EntityType.THRESHOLD, EntityType.TAX_RATE):
        return None
    try:
        return Decimal(entity.canonical_name.rstrip("%"))
    except InvalidOperation:
        return None
