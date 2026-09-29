"""The planner: one ``qa.plan@1`` call that turns the question into a plan, never an answer.

The schema of the call closes every choice, including the rule keys and regulators in force on
the question's date. A plan that fails ``parse_plan`` gets one retry that lists the problems;
after that the question falls back (``plan_invalid``). A gateway failure falls back too
(``planner_unavailable``), and an empty plan hands the question to hybrid search
(``planner_deferred``). A used-up budget (``ModelBudgetExceededError``) is not caught: the
answer's call would be refused as well.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from domain_kernel.ids import RuleVersionId
from domain_kernel.llm import CompletionRequest
from domain_kernel.protocols import LLMProvider
from qa.application.context import AskContext, AskRequest
from qa.domain.answer import Layer, Reason
from qa.domain.errors import GatewayError
from qa.domain.plan import Plan
from qa.domain.plan_schema import PlanContext, PlanInvalidError, parse_plan, plan_schema
from qa.domain.prompt import PromptText
from qa.domain.records import RuleVersion

FEATURE: Final = "qa"
PLAN_MAX_TOKENS: Final = 1_500
STAGE: Final = "plan"


@dataclass(frozen=True, slots=True)
class Planned:
    """The plan when one validated (an empty one included), or why there is none."""

    plan: Plan | None
    reason: Reason | None = None
    attempts: int = 0


class Planner:
    def __init__(self, provider: LLMProvider, prompt: PromptText) -> None:
        self._provider = provider
        self._prompt = prompt

    @property
    def prompt_ref(self) -> str:
        return self._prompt.ref

    def plan(self, ctx: AskContext) -> Planned:
        request = ctx.request
        visible = ctx.visible()
        rule_keys = sorted({version.rule_key for version in visible.values()})
        regulators = sorted({version.regulator for version in visible.values()})
        context = PlanContext(
            as_of=request.as_of,
            has_business=request.business is not None,
            rule_keys=frozenset(rule_keys),
            regulators=frozenset(regulators),
        )
        schema = plan_schema(rule_keys, regulators)
        user = render_question(request, visible)
        problems: tuple[str, ...] = ()
        for attempt in (1, 2):
            text = user
            if problems:
                text += "\n\nYour previous plan failed: " + "; ".join(problems)
            try:
                response = self._provider.complete(
                    CompletionRequest(
                        feature=FEATURE,
                        prompt_version=self._prompt.ref,
                        system=self._prompt.system,
                        user=text,
                        max_tokens=PLAN_MAX_TOKENS,
                        json_schema=schema,
                        tenant_id=request.tenant,
                        metadata=ctx.metadata(STAGE, attempt, Layer.KAG),
                    )
                )
            except GatewayError:
                return Planned(None, Reason.PLANNER_UNAVAILABLE, attempt)
            try:
                plan = parse_plan(response.text, context)
            except PlanInvalidError as exc:
                problems = exc.problems
                continue
            return Planned(plan, Reason.PLANNER_DEFERRED if plan.defers else None, attempt)
        return Planned(None, Reason.PLAN_INVALID, 2)


def render_question(request: AskRequest, visible: Mapping[RuleVersionId, RuleVersion]) -> str:
    """What the planner reads: the question, its date, whether a business is in context, and
    the rules in force on that date."""
    rules = sorted(visible.values(), key=lambda version: version.rule_key)
    lines = [
        f"Question: {request.question}",
        f"Date of the question: {request.as_of.isoformat()}",
        f"Business in context: {'yes' if request.business is not None else 'no'}",
        "",
        f"Rules in force on {request.as_of.isoformat()} (rule_key [regulator]: title):",
    ]
    lines.extend(f"- {rule.rule_key} [{rule.regulator}]: {rule.title}" for rule in rules)
    if not rules:
        lines.append("(none)")
    return "\n".join(lines)
