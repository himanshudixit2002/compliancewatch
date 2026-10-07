"""The planner: the call it makes, one retry with the problems, and each way it falls back."""

from typing import Any

import pytest

from qa.application.planner import Planner
from qa.domain.answer import Reason
from qa.domain.errors import GatewayError, ModelBudgetExceededError, ModelResidencyRefusedError
from qa.domain.plan import Op
from qa.domain.prompt import PromptText
from qa.testing import plan_step, plan_text

World = Any
PROMPT = PromptText("qa.plan", "1", "ai-platform", "Plan the question.")


def valid(world: World) -> str:
    return plan_text(
        plan_step(1, "rules_in_force", rule_key=world.MONTHLY_RULE),
        plan_step(2, "answer", sources=["s1"]),
    )


def test_one_call_with_the_closed_schema_and_the_tags(world: World) -> None:
    world.provider.add("q1", world.PLAN, valid(world))
    planned = Planner(world.provider, PROMPT).plan(world.context("Which notice extended it?"))
    assert planned.reason is None
    assert planned.attempts == 1
    assert planned.plan is not None
    assert [step.op for step in planned.plan.steps] == [Op.RULES_IN_FORCE, Op.ANSWER]
    (request,) = world.provider.requests
    assert (request.feature, request.prompt_version, request.system) == (
        "qa",
        "qa.plan@1",
        "Plan the question.",
    )
    assert request.tenant_id == world.TENANT
    assert dict(request.metadata) == {
        "question_id": "q1",
        "stage": "plan",
        "attempt": "1",
        "layer": "kag",
    }
    assert request.json_schema is not None
    properties = request.json_schema["properties"]["steps"]["items"]["properties"]
    assert list(properties["rule_key"]["enum"]) == [world.EXTENSION_RULE, world.MONTHLY_RULE, None]
    assert request.user.splitlines()[:3] == [
        "Question: Which notice extended it?",
        "Date of the question: 2026-04-10",
        "Business in context: yes",
    ]
    assert f"- {world.MONTHLY_RULE} [cbic]: File FORM GSTR-3B every month" in request.user
    assert "gstr3b_draft" not in request.user


def test_one_retry_names_the_problems(world: World) -> None:
    world.provider.add("q1", world.PLAN, '{"as_of": null}', valid(world))
    planned = Planner(world.provider, PROMPT).plan(world.context())
    assert (planned.reason, planned.attempts) == (None, 2)
    first, second = world.provider.requests
    assert second.metadata["attempt"] == "2"
    assert second.user == (
        first.user + "\n\nYour previous plan failed: "
        "the plan must be an object with exactly as_of and steps"
    )


def test_two_invalid_plans_fall_back(world: World) -> None:
    world.provider.add("q1", world.PLAN, "no plan")
    planned = Planner(world.provider, PROMPT).plan(world.context())
    assert (planned.plan, planned.reason, planned.attempts) == (None, Reason.PLAN_INVALID, 2)
    assert len(world.provider.requests) == 2


def test_a_gateway_failure_falls_back(world: World) -> None:
    world.provider.add("q1", world.PLAN, GatewayError("503: down"))
    planned = Planner(world.provider, PROMPT).plan(world.context())
    assert (planned.plan, planned.reason, planned.attempts) == (
        None,
        Reason.PLANNER_UNAVAILABLE,
        1,
    )


def test_a_used_up_budget_is_not_a_fallback(world: World) -> None:
    world.provider.add("q1", world.PLAN, ModelBudgetExceededError("llm-gateway answered 429"))
    with pytest.raises(ModelBudgetExceededError):
        Planner(world.provider, PROMPT).plan(world.context())


def test_a_residency_refusal_is_not_a_fallback(world: World) -> None:
    world.provider.add("q1", world.PLAN, ModelResidencyRefusedError("llm-gateway refuses"))
    with pytest.raises(ModelResidencyRefusedError):
        Planner(world.provider, PROMPT).plan(world.context())
    assert len(world.provider.requests) == 1


def test_an_empty_plan_defers(world: World) -> None:
    world.provider.add("q1", world.PLAN, plan_text())
    planned = Planner(world.provider, PROMPT).plan(world.context(business=None))
    assert planned.plan is not None
    assert planned.plan.defers
    assert planned.reason is Reason.PLANNER_DEFERRED
    assert "Business in context: no" in world.provider.requests[0].user


def test_no_rules_in_force_is_said(world: World) -> None:
    world.rulebook.versions.clear()
    world.provider.add("q1", world.PLAN, plan_text())
    planner = Planner(world.provider, PROMPT)
    assert planner.prompt_ref == "qa.plan@1"
    planner.plan(world.context())
    assert world.provider.requests[0].user.endswith("(none)")
