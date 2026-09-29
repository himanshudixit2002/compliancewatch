"""Layer 2 behind the flag (ADR-017): plan, solve, then answer from what the solver found.

A plan that does not validate, a deferral, a solver that fails or runs over its budget, and a
bundle with no clause all fall back to hybrid search with the reason. Once the answerer has
run, its outcome is final: an answer that fails its checks is ``not_covered`` here, not a
second chance elsewhere.
"""

from dataclasses import dataclass

from qa.application.answerer import Answerer
from qa.application.context import AskContext
from qa.application.planner import Planner
from qa.application.solver import Solver, SolverBudgetExceededError, SolverStepError
from qa.domain.answer import Answer, Layer, Reason
from qa.domain.plan import Plan


@dataclass(frozen=True, slots=True)
class KagOutcome:
    """The answer when the layer decided, else the reason it fell back; the plan whenever one
    validated."""

    answer: Answer | None
    plan: Plan | None = None
    reason: Reason | None = None


class KagLayer:
    def __init__(self, planner: Planner, solver: Solver, answerer: Answerer) -> None:
        self._planner = planner
        self._solver = solver
        self._answerer = answerer

    def run(self, ctx: AskContext) -> KagOutcome:
        planned = self._planner.plan(ctx)
        plan = planned.plan
        if plan is None or planned.reason is not None:
            return KagOutcome(None, plan, planned.reason)
        try:
            bundle = self._solver.solve(plan, ctx)
        except SolverBudgetExceededError:
            return KagOutcome(None, plan, Reason.STEP_BUDGET_EXCEEDED)
        except SolverStepError:
            return KagOutcome(None, plan, Reason.STEP_FAILED)
        if bundle.empty:
            return KagOutcome(None, plan, Reason.NO_EVIDENCE)
        answer = self._answerer.answer(ctx, bundle, Layer.KAG)
        return KagOutcome(answer, plan, answer.reason)
