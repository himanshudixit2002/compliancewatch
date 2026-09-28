"""Layer 1: due dates from the business's obligations, with the rule's verified citations."""

from datetime import date
from typing import Any

from domain_kernel.status import ObligationStatus
from qa.application.structured import StructuredLayer
from qa.domain.answer import AnswerCitation, Outcome

World = Any


def layer(world: World) -> StructuredLayer:
    return StructuredLayer(world.rulebook, world.obligations)


def cited(world: World) -> AnswerCitation:
    clause = world.monthly_clause
    return AnswerCitation(clause.clause_ref, clause.document_id, world.MONTHLY_QUOTE)


def test_the_next_due_date_of_a_form(world: World) -> None:
    answer = layer(world).run(world.context("When is my GSTR-3B due?"))
    assert answer is not None
    assert answer.outcome is Outcome.ANSWERED
    assert answer.text == (
        "Your next GSTR-3B is due on 20 April 2026: File GSTR-3B for the month (2026-03)."
    )
    assert answer.citations == (cited(world),)
    assert world.obligations.requests == [(date(2026, 4, 10), date(2027, 4, 10))]


def test_what_is_due_next_month(world: World) -> None:
    answer = layer(world).run(world.context("What is due next month?"))
    assert answer is not None
    assert (
        answer.text == "Due next month: File GSTR-3B for the month (2026-04), due on 20 May 2026."
    )
    assert world.obligations.requests == [(date(2026, 5, 1), date(2026, 5, 31))]


def test_the_form_can_be_named_by_the_rule_alone(world: World) -> None:
    world.obligations.add(
        world.TENANT, world.BUSINESS, world.monthly, "Monthly return", date(2026, 4, 15)
    )
    answer = layer(world).run(world.context("when is my gstr 3b due"))
    assert answer is not None
    assert "15 April 2026: Monthly return" in answer.text


def test_other_questions_and_no_business_pass(world: World) -> None:
    assert layer(world).run(world.context("Which notice extended GSTR-3B?")) is None
    assert layer(world).run(world.context("When is my GSTR-3B due?", business=None)) is None
    assert world.obligations.requests == []


def test_another_form_passes(world: World) -> None:
    assert layer(world).run(world.context("When is my GSTR-1 due?")) is None


def test_closed_obligations_and_hidden_versions_do_not_count(world: World) -> None:
    world.obligations.rows[world.TENANT] = []
    world.obligations.add(
        world.TENANT,
        world.BUSINESS,
        world.monthly,
        "File GSTR-3B for the month (2026-03)",
        date(2026, 4, 20),
        status=ObligationStatus.DONE,
    )
    world.obligations.add(
        world.TENANT, world.BUSINESS, world.draft, "File GSTR-3B (draft)", date(2026, 4, 21)
    )
    assert layer(world).run(world.context("When is my GSTR-3B due?")) is None


def test_a_citation_that_does_not_hold_passes(world: World) -> None:
    world.rulebook.citations[world.monthly.rule_version_id] = []
    world.rulebook.cite(world.monthly, world.monthly_clause, world.MONTHLY_QUOTE, verified=False)
    world.rulebook.cite(world.monthly, world.monthly_clause, "by the 25th day of the next month")
    world.rulebook.cite(world.monthly, world.extension_clause, world.MONTHLY_QUOTE)
    assert layer(world).run(world.context("When is my GSTR-3B due?")) is None


def test_a_missing_clause_passes(world: World) -> None:
    del world.rulebook.clauses[world.monthly_clause.clause_id]
    assert layer(world).run(world.context("When is my GSTR-3B due?")) is None


def test_a_version_the_rulebook_no_longer_has_passes(world: World) -> None:
    rulebook = world.rulebook
    rulebook.rule_version = lambda rule_version_id: None
    assert layer(world).run(world.context("When is my GSTR-3B due?")) is None
