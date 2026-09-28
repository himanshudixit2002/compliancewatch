"""The answerer: the post-check, one retry, and not covered."""

from typing import Any

import pytest

from qa.application.answerer import Answerer
from qa.domain.answer import AnswerCitation, Layer, Outcome, Reason
from qa.domain.errors import DependencyUnavailableError, GatewayError
from qa.domain.evidence import BundleBuilder, EvidenceBundle
from qa.domain.prompt import PromptText
from qa.testing import answer_text

World = Any
PROMPT = PromptText("qa.answer", "1", "ai-platform", "Answer from the evidence.")


def bundle(world: World) -> EvidenceBundle:
    builder = BundleBuilder()
    clause = world.extension_clause
    builder.add_clause(
        clause_id=clause.clause_id,
        document_id=clause.document_id,
        clause_ref=clause.clause_ref,
        text=clause.text,
        step_id="s2",
        source=clause.source,
    )
    builder.add_fact("s2", "the extension extends the monthly rule for 2026-03")
    return builder.build()


def answer(world: World, layer: Layer = Layer.KAG) -> Any:
    return Answerer(world.provider, PROMPT).answer(world.context(), bundle(world), layer)


def test_an_answer_that_passes_the_check(world: World) -> None:
    world.provider.add(
        "q1", world.ANSWER, answer_text(" 24 April 2026. ", ("C1", world.EXTENSION_QUOTE))
    )
    result = answer(world)
    assert result.outcome is Outcome.ANSWERED
    assert result.text == "24 April 2026."
    clause = world.extension_clause
    assert result.citations == (
        AnswerCitation(clause.clause_ref, clause.document_id, world.EXTENSION_QUOTE),
    )
    (request,) = world.provider.requests
    assert dict(request.metadata) == {
        "question_id": "q1",
        "stage": "answer",
        "attempt": "1",
        "layer": "kag",
    }
    assert request.json_schema is not None
    assert "[C1] en.p3 (TEST-02)" in request.user
    assert "F1: the extension extends the monthly rule for 2026-03" in request.user


def test_a_failed_check_gets_one_retry(world: World) -> None:
    wrong = answer_text("25 April", ("C1", "may be furnished till the 25th day of April, 2026"))
    right = answer_text("24 April", ("C1", world.EXTENSION_QUOTE))
    world.provider.add("q1", world.ANSWER, wrong, right)
    result = answer(world, Layer.HYBRID)
    assert result.outcome is Outcome.ANSWERED
    first, second = world.provider.requests
    assert (second.metadata["attempt"], second.metadata["layer"]) == ("2", "hybrid")
    assert second.user.startswith(first.user + "\n\nYour previous answer failed the check: ")
    assert "25th" in second.user


def test_two_failures_are_not_covered(world: World) -> None:
    world.provider.add("q1", world.ANSWER, "not json", answer_text("yes"))
    result = answer(world)
    assert (result.outcome, result.reason) == (Outcome.NOT_COVERED, Reason.CITATION_CHECK_FAILED)
    assert result.citations == ()


def test_a_declined_answer_is_not_covered(world: World) -> None:
    world.provider.add("q1", world.ANSWER, answer_text("", covered=False))
    result = answer(world)
    assert (result.outcome, result.reason) == (Outcome.NOT_COVERED, Reason.ANSWERER_DECLINED)


def test_a_gateway_failure_is_a_dependency_failure(world: World) -> None:
    world.provider.add("q1", world.ANSWER, GatewayError("429: budget"))
    with pytest.raises(DependencyUnavailableError, match="llm-gateway: 429: budget"):
        answer(world)
    assert Answerer(world.provider, PROMPT).prompt_ref == "qa.answer@1"
