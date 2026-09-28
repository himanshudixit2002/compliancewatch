"""Asking: the layers in order, flag routing, fallbacks, the plan and the records."""

from datetime import date
from typing import Any

import pytest

from domain_kernel.financial_year import FinancialYear
from domain_kernel.ids import BusinessId
from qa.application.ask import LayerRecord
from qa.application.context import AskRequest
from qa.application.solver import Budget
from qa.application.tracing import NullTracer
from qa.domain.answer import NOT_COVERED_TEXT, Layer, LayerResult, Outcome, Reason
from qa.domain.errors import (
    BusinessNotFoundError,
    DependencyUnavailableError,
    GatewayError,
    QuestionInvalidError,
)
from qa.domain.flags import KagTargeting
from qa.testing import answer_text, plan_step, plan_text

World = Any
EXTENSION_QUESTION = "Which notice extended the GSTR-3B due date for March 2026?"


def extension_plan(world: World) -> str:
    return plan_text(
        plan_step(1, "rules_in_force", rule_key=world.MONTHLY_RULE),
        plan_step(
            2, "follow", source="s1", relations=["extends_deadline"], direction="in", depth=1
        ),
        plan_step(3, "answer", sources=["s2"]),
    )


def cited(world: World) -> str:
    return answer_text("TEST-02 extended it to 24 April 2026.", ("C1", world.EXTENSION_QUOTE))


def test_the_structured_layer_answers_first_without_a_model_call(world: World) -> None:
    result = world.ask().run(world.request("When is my GSTR-3B due?"))
    assert (result.outcome, result.layer, result.reason, result.plan) == (
        Outcome.ANSWERED,
        Layer.STRUCTURED,
        None,
        None,
    )
    assert result.layers == (LayerRecord(Layer.STRUCTURED, LayerResult.ANSWERED),)
    assert result.as_of == world.AS_OF
    assert world.provider.requests == []


def test_kag_answers_a_targeted_tenant_and_keeps_the_plan(world: World) -> None:
    world.provider.add("q1", world.PLAN, extension_plan(world))
    world.provider.add("q1", world.ANSWER, cited(world))
    result = world.ask().run(world.request(EXTENSION_QUESTION))
    assert (result.outcome, result.layer) == (Outcome.ANSWERED, Layer.KAG)
    assert result.layers == (
        LayerRecord(Layer.STRUCTURED, LayerResult.PASSED),
        LayerRecord(Layer.KAG, LayerResult.ANSWERED),
    )
    assert result.plan is not None
    assert len(result.plan.steps) == 3
    assert [c.clause_ref for c in result.citations] == ["en.p3"]
    assert [req.metadata["stage"] for req in world.provider.requests] == ["plan", "answer"]
    assert len(world.tracer.named("qa.solve.step")) == 3
    (ask,) = world.tracer.named("qa.ask")
    assert ask.attributes == {
        "qa.question_id": "q1",
        "qa.tenant_id": str(world.TENANT),
        "qa.layer": "kag",
        "qa.outcome": "answered",
    }
    layers = [span.attributes for span in world.tracer.named("qa.layer")]
    assert layers == [
        {"qa.layer": "structured", "qa.result": "passed"},
        {"qa.layer": "kag", "qa.result": "answered"},
    ]


def test_with_the_flag_off_hybrid_answers_without_a_planner_call(world: World) -> None:
    world.provider.add("q1", world.ANSWER, cited(world))
    result = world.ask(KagTargeting(enabled=False)).run(world.request(EXTENSION_QUESTION))
    assert (result.outcome, result.layer, result.plan) == (Outcome.ANSWERED, Layer.HYBRID, None)
    assert result.layers == (
        LayerRecord(Layer.STRUCTURED, LayerResult.PASSED),
        LayerRecord(Layer.HYBRID, LayerResult.ANSWERED),
    )
    assert world.provider.calls(world.PLAN) == []


def test_a_tenant_not_listed_goes_to_hybrid(world: World) -> None:
    world.provider.add("q1", world.ANSWER, cited(world))
    targeting = KagTargeting(enabled=True, tenants=frozenset({world.OTHER_TENANT}))
    result = world.ask(targeting).run(world.request(EXTENSION_QUESTION))
    assert [record.layer for record in result.layers] == [Layer.STRUCTURED, Layer.HYBRID]
    assert world.provider.calls(world.PLAN) == []


def test_an_invalid_plan_falls_back_to_hybrid(world: World) -> None:
    world.provider.add("q1", world.PLAN, "no plan")
    world.provider.add("q1", world.ANSWER, cited(world))
    result = world.ask().run(world.request(EXTENSION_QUESTION))
    assert (result.layer, result.plan) == (Layer.HYBRID, None)
    assert result.layers[1] == LayerRecord(Layer.KAG, LayerResult.FALLBACK, Reason.PLAN_INVALID)
    assert world.provider.calls(world.ANSWER)[0].metadata["layer"] == "hybrid"


def test_a_deferred_plan_is_kept_when_hybrid_answers(world: World) -> None:
    world.provider.add("q1", world.PLAN, plan_text())
    world.provider.add("q1", world.ANSWER, cited(world))
    result = world.ask().run(world.request(EXTENSION_QUESTION))
    assert result.plan is not None
    assert result.plan.defers
    assert result.layers[1].reason is Reason.PLANNER_DEFERRED


def test_a_planner_outage_falls_back(world: World) -> None:
    world.provider.add("q1", world.PLAN, GatewayError("502"))
    world.provider.add("q1", world.ANSWER, cited(world))
    result = world.ask().run(world.request(EXTENSION_QUESTION))
    assert result.layers[1].reason is Reason.PLANNER_UNAVAILABLE


def test_a_failed_step_falls_back_with_the_plan(world: World) -> None:
    world.provider.add(
        "q1",
        world.PLAN,
        plan_text(plan_step(1, "get_obligations"), plan_step(2, "answer", sources=["s1"])),
    )
    world.provider.add("q1", world.ANSWER, cited(world))
    world.obligations.fail = True
    result = world.ask().run(world.request(EXTENSION_QUESTION))
    assert result.plan is not None
    assert result.layers[1] == LayerRecord(Layer.KAG, LayerResult.FALLBACK, Reason.STEP_FAILED)
    assert result.layer is Layer.HYBRID


def test_no_clause_from_the_solver_falls_back(world: World) -> None:
    world.provider.add(
        "q1",
        world.PLAN,
        plan_text(plan_step(1, "rules_in_force"), plan_step(2, "answer", sources=["s1"])),
    )
    world.provider.add("q1", world.ANSWER, cited(world))
    result = world.ask().run(world.request(EXTENSION_QUESTION))
    assert result.layers[1].reason is Reason.NO_EVIDENCE


def test_the_budget_falls_back(world: World) -> None:
    many = [plan_step(n, "rules_in_force") for n in range(1, 8)]
    world.provider.add("q1", world.PLAN, plan_text(*many, plan_step(8, "answer", sources=["s1"])))
    world.provider.add("q1", world.ANSWER, cited(world))
    result = world.ask(budget=Budget(items=1)).run(world.request(EXTENSION_QUESTION))
    assert result.layers[1].reason is Reason.STEP_BUDGET_EXCEEDED


def test_once_kag_has_answered_its_refusal_is_final(world: World) -> None:
    world.provider.add("q1", world.PLAN, extension_plan(world))
    world.provider.add("q1", world.ANSWER, answer_text("", covered=False))
    result = world.ask().run(world.request(EXTENSION_QUESTION))
    assert (result.outcome, result.answer, result.layer, result.reason) == (
        Outcome.NOT_COVERED,
        NOT_COVERED_TEXT,
        Layer.KAG,
        Reason.ANSWERER_DECLINED,
    )
    assert len(result.layers) == 2
    assert world.tracer.named("qa.ask")[0].attributes["qa.reason"] == "answerer_declined"


def test_hybrid_with_nothing_found_is_not_covered(world: World) -> None:
    result = world.ask(KagTargeting()).run(world.request("What is the rate on cement?"))
    assert (result.outcome, result.layer, result.reason) == (
        Outcome.NOT_COVERED,
        Layer.HYBRID,
        Reason.NO_EVIDENCE,
    )
    assert result.layers[-1] == LayerRecord(
        Layer.HYBRID, LayerResult.NOT_COVERED, Reason.NO_EVIDENCE
    )


def test_a_draft_version_stays_hidden(world: World) -> None:
    world.rulebook.relation_rows.clear()
    world.rulebook.set_status(world.extension, "draft")
    world.provider.add("q1", world.PLAN, "no plan")
    world.provider.add("q1", world.ANSWER, cited(world))
    world.ask().run(world.request(EXTENSION_QUESTION))
    schema = world.provider.calls(world.PLAN)[0].json_schema
    keys = schema["properties"]["steps"]["items"]["properties"]["rule_key"]["enum"]
    assert list(keys) == [world.MONTHLY_RULE, None]


def test_an_unknown_business_is_refused_before_any_layer(world: World) -> None:
    with pytest.raises(BusinessNotFoundError):
        world.ask().run(world.request("When is my GSTR-3B due?", business=BusinessId.new()))
    assert world.obligations.requests == []
    assert world.tracer.named("qa.ask")[0].failed


def test_a_rulebook_outage_is_a_dependency_failure(world: World) -> None:
    world.rulebook.fail = True
    with pytest.raises(DependencyUnavailableError):
        world.ask().run(world.request("When is my GSTR-3B due?"))


def test_the_profile_is_read_for_the_financial_year_of_the_date(world: World) -> None:
    world.provider.add("q1", world.ANSWER, cited(world))
    world.ask(KagTargeting()).run(world.request(EXTENSION_QUESTION))
    assert world.profiles.requests == [(world.TENANT, world.BUSINESS, FinancialYear(2026))]


def test_a_request_is_checked(world: World) -> None:
    tenant = world.TENANT
    with pytest.raises(QuestionInvalidError, match="empty"):
        AskRequest(tenant, "  \n ", world.AS_OF, "q1")
    with pytest.raises(QuestionInvalidError, match="at most 1000"):
        AskRequest(tenant, "x" * 1001, world.AS_OF, "q1")
    with pytest.raises(QuestionInvalidError, match="an id"):
        AskRequest(tenant, "why", world.AS_OF, " ")
    request = AskRequest(tenant, "  why\n now ", date(2026, 3, 31), "q1", fy=FinancialYear(2024))
    assert (request.question, request.financial_year) == ("why now", FinancialYear(2024))
    assert AskRequest(tenant, "why", date(2026, 3, 31), "q1").financial_year == FinancialYear(2025)


def test_a_profile_needs_a_business(world: World) -> None:
    with pytest.raises(QuestionInvalidError, match="no business"):
        world.context(business=None).profile()


def test_the_null_tracer_records_nothing() -> None:
    with NullTracer().span("qa.ask", {"qa.question_id": "q1"}) as span:
        span.set_attribute("qa.layer", "kag")
