"""Scoring one qa answer: dates in their written forms, facts, citations, and the aggregates."""

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from cw_evals.qa.cases import load_qa_case
from cw_evals.qa.score import (
    Asked,
    ModelCall,
    QaScore,
    WorldClause,
    aggregate,
    dates_in,
    entities_in,
    folded,
    has_amount,
    p95,
    score_case,
)
from domain_kernel.knowledge import EntityType

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "golden" / "qa" / "kag" / "cases"
DOC = UUID(int=1)
EN_P3 = (
    "the Commissioner hereby extends the due  date for furnishing the return in FORM GSTR-3B for "
    "the month of March, 2026 till the twenty -first day of April, 2026"
)
CLAUSES = {
    (str(DOC), "en.p3"): WorldClause("n01_2026", "en.p3", EN_P3, date(2026, 4, 21)),
    (str(DOC), "en.p9"): WorldClause("n01_2026", "en.p9", "Other text.", date(2026, 4, 21)),
}
QUOTE = (
    "extends the due date for furnishing the return in FORM GSTR-3B for the month of March, 2026"
)


@pytest.mark.parametrize(
    ("text", "day"),
    [
        ("due on 2026-04-21.", date(2026, 4, 21)),
        ("till 21 April 2026", date(2026, 4, 21)),
        ("dated the 21st April, 2026", date(2026, 4, 21)),
        ("dated the 26 th December, 2022", date(2022, 12, 26)),
        ("the 17th day of September 2025", date(2025, 9, 17)),
        ("on April 21, 2026", date(2026, 4, 21)),
        ("on september 3 2025", date(2025, 9, 3)),
        ("till the twenty -first day of April, 2026", date(2026, 4, 21)),
        ("till twenty-fifth day of October, 2025", date(2025, 10, 25)),
        ("on the thirty-first day of December, 2027", date(2027, 12, 31)),
        ("from the first day of July 2025", date(2025, 7, 1)),
        ("on April twenty first, 2026", date(2026, 4, 21)),
    ],
)
def test_dates_are_read_in_every_written_form(text: str, day: date) -> None:
    assert dates_in(text) == {day}


def test_impossible_dates_and_bare_months_are_not_dates() -> None:
    assert dates_in("31 February 2026, March 2026, 2026-13-01 and 12/2025") == set()
    assert (
        dates_in("the thirtieth day of February, 2026 and the twenty-first of the month") == set()
    )


def test_amounts_and_folding() -> None:
    assert has_amount("up to two crore rupees")
    assert has_amount("Rs. 5,000")
    assert has_amount("\u20b9 50")
    assert not has_amount("notification 12/2025-Central Tax")
    assert folded("Sub\u2013section  (6)\nof") == "sub-section (6) of"
    assert folded("sub -rule (4B) and 2024 - 25") == "sub-rule (4b) and 2024-25"


def test_the_grammar_reads_entities_out_of_an_answer() -> None:
    found = entities_in("It amends notification No. 02/2017-Central Tax and FORM GSTR-3B.")
    assert (EntityType.NOTIFICATION, "02/2017-central tax") in found
    assert (EntityType.FORM, "GSTR-3B") in found


def body(answer: str, *citations: tuple[str, str], **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "outcome": "answered",
        "answer": answer,
        "citations": [
            {"clause_ref": ref, "document_id": str(DOC), "quote": quote} for ref, quote in citations
        ],
        "layer": "kag",
        "layers": [
            {"layer": "structured", "result": "passed", "reason": None},
            {"layer": "kag", "result": "answered", "reason": None},
        ],
        "plan": {"as_of": None, "steps": []},
        "reason": None,
        "as_of": "2026-04-22",
    }
    data.update(overrides)
    return data


def case_2026_03() -> Any:
    return load_qa_case(CASES / "mh-acme-gstr3b-2026-03.yaml")


def test_a_grounded_answer_scores_every_part() -> None:
    plan_call = ModelCall("mh-acme-gstr3b-2026-03", "qa.plan@1", "plan", 1, 200, 10, 5)
    asked = Asked(
        case_2026_03(),
        200,
        body("Due on 21 April 2026.", ("en.p3", QUOTE)),
        calls=(plan_call,),
        latency_ms=12.0,
    )
    score = score_case(asked, CLAUSES)
    assert score.grounded
    assert score.safe
    assert score.passed
    assert (score.planned, score.plan_valid, score.plan_first_try) == (True, True, True)
    assert (score.citations, score.valid_citations, score.correct_citations) == (1, 1, 1)
    assert (score.input_tokens, score.output_tokens) == (10, 5)
    assert score.problems == ()


@pytest.mark.parametrize(
    ("answer", "citation", "problem"),
    [
        ("Due on 20 April 2026.", ("en.p3", QUOTE), "date 2026-04-21 is not in the answer"),
        (
            "Due on 21 April 2026, not 25 October.",
            ("en.p3", QUOTE),
            "the answer mentions '25 October'",
        ),
        ("Due on 21 April 2026.", ("en.p3", "extends the due date till May"), "is invalid"),
        ("Due on 21 April 2026.", ("en.p9", "Other text."), "is not expected"),
        ("Due on 21 April 2026.", ("en.p7", QUOTE), "is invalid"),
    ],
)
def test_an_answer_is_not_grounded_when_a_part_fails(
    answer: str, citation: tuple[str, str], problem: str
) -> None:
    score = score_case(Asked(case_2026_03(), 200, body(answer, citation)), CLAUSES)
    assert not score.grounded
    assert any(problem in item for item in score.problems), score.problems


def test_a_citation_of_a_clause_published_later_is_invalid() -> None:
    case = replace(case_2026_03(), as_of=date(2026, 4, 20))
    score = score_case(Asked(case, 200, body("21 April 2026", ("en.p3", QUOTE))), CLAUSES)
    assert (score.valid_citations, score.safe) == (0, False)


def test_entities_and_text_facts_are_read_from_the_answer() -> None:
    case = load_qa_case(CASES / "mh-02-2017-amendments.yaml")
    only_one = body("Notification No. 10/2025-Central Tax amends it.")
    score = score_case(Asked(case, 200, only_one), CLAUSES)
    assert score.problems == ("notification 27/2024-Central Tax is not in the answer",)
    text_case = load_qa_case(CASES / "sh-17-2025-power.yaml")
    score = score_case(Asked(text_case, 200, body("Under section 39 only.")), CLAUSES)
    assert "'section 168' is not in the answer" in score.problems


def test_a_refusal_passes_a_must_refuse_case_and_fails_an_answerable_one() -> None:
    refused = body(
        "I cannot answer this.",
        outcome="not_covered",
        layer="hybrid",
        reason="citation_check_failed",
        layers=[
            {"layer": "structured", "result": "passed", "reason": None},
            {"layer": "kag", "result": "fallback", "reason": "step_failed"},
            {"layer": "hybrid", "result": "not_covered", "reason": "citation_check_failed"},
        ],
    )
    must_refuse = load_qa_case(CASES / "mr-listing-12-2025.yaml")
    score = score_case(Asked(must_refuse, 200, refused), CLAUSES)
    assert score.passed
    assert score.refused
    assert score.safe
    assert score.solver_failed
    answerable = score_case(Asked(case_2026_03(), 200, refused), CLAUSES)
    assert not answerable.passed
    assert answerable.problems == ("not covered (citation_check_failed)",)
    answered = score_case(Asked(must_refuse, 200, body("Yes.")), CLAUSES)
    assert "answered a question it must refuse" in answered.problems


def test_with_kag_on_a_planned_case_counts_only_when_kag_decides() -> None:
    fell_back = body(
        "Due on 21 April 2026.",
        ("en.p3", QUOTE),
        layer="hybrid",
        layers=[
            {"layer": "structured", "result": "passed", "reason": None},
            {"layer": "kag", "result": "fallback", "reason": "no_evidence"},
            {"layer": "hybrid", "result": "answered", "reason": None},
        ],
        plan={"as_of": None, "steps": [{"id": "s1", "op": "rules_in_force"}]},
    )
    asked = Asked(case_2026_03(), 200, fell_back)
    kag_run = score_case(asked, CLAUSES, kag_on=True)
    assert (kag_run.kag_expected, kag_run.solver_failed, kag_run.grounded) == (True, True, False)
    assert "decided by the hybrid layer after no_evidence, not kag" in kag_run.problems
    assert score_case(asked, CLAUSES).grounded
    refused = {**fell_back, "outcome": "not_covered", "reason": "citation_check_failed"}
    refused["layers"] = [
        *fell_back["layers"][:2],
        {"layer": "hybrid", "result": "not_covered", "reason": "citation_check_failed"},
    ]
    must_refuse = load_qa_case(CASES / "mr-listing-12-2025.yaml")
    listing = score_case(Asked(must_refuse, 200, refused), CLAUSES, kag_on=True)
    assert (listing.kag_expected, listing.solver_failed, listing.passed) == (False, False, True)


def test_no_response_is_neither_safe_nor_a_refusal() -> None:
    for asked in (
        Asked(case_2026_03(), 503, {"detail": "down"}),
        Asked(case_2026_03(), None, error="RuntimeError: boom"),
        Asked(case_2026_03(), 200, {"outcome": "maybe"}),
    ):
        score = score_case(asked, CLAUSES)
        assert not score.responded
        assert not score.safe
        assert not score.refused
    assert score_case(Asked(case_2026_03(), None, error="E"), CLAUSES).problems == ("E",)


def score(**fields: Any) -> QaScore:
    base: dict[str, Any] = {
        "case_id": "c",
        "category": "single_hop",
        "fact_source": "recorded_clause",
        "label_status": "draft",
        "answerable": True,
        "responded": True,
        "outcome": "answered",
        "layer": "kag",
        "citations": 1,
        "valid_citations": 1,
        "correct_citations": 1,
        "expected_cited": True,
        "facts_ok": True,
    }
    base.update(fields)
    return QaScore(**base)


def test_the_aggregate_counts_each_metric_over_its_own_cases() -> None:
    scores = [
        score(planned=True, plan_valid=True, plan_first_try=True, latency_ms=10.0),
        score(planned=True, plan_valid=True, plan_first_try=False, solver_failed=True),
        score(planned=True, plan_valid=False, plan_first_try=False, outcome="not_covered"),
        score(
            answerable=False,
            outcome="not_covered",
            layer="hybrid",
            citations=0,
            valid_citations=0,
            correct_citations=0,
        ),
        score(category="multi_hop", valid_citations=0, correct_citations=0, latency_ms=30.0),
    ]
    result = aggregate(scores)
    assert result.cases == 5
    assert result.plan_validity == pytest.approx(2 / 3)
    assert result.plan_first_try_validity == pytest.approx(1 / 3)
    assert result.solver_success == 0.5
    assert result.citation_correctness == 0.75
    assert result.grounded_answer_rate == 0.5
    assert result.false_refusal_rate == 0.25
    assert (result.refusal_accuracy, result.response_rate) == (1.0, 1.0)
    assert result.answer_safety == 0.8
    assert result.layer_shares == {"hybrid": 0.2, "kag": 0.8}
    assert result.grounded_by_category == {"multi_hop": 0.0, "single_hop": pytest.approx(2 / 3)}
    assert result.p95_latency_ms == 30.0


def test_an_empty_aggregate_has_nothing_to_share() -> None:
    result = aggregate([])
    assert result.plan_validity is None
    assert result.grounded_answer_rate is None
    assert result.citation_correctness == 1.0
    assert result.p95_latency_ms == 0.0


def test_p95_takes_the_nearest_rank() -> None:
    assert p95([float(n) for n in range(1, 101)]) == 95.0
    assert p95([3.0, 1.0]) == 3.0
