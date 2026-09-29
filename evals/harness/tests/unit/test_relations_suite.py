"""The relation suite: loading the golden cases, the scripted and fake runs, the scores."""

from dataclasses import replace
from pathlib import Path

import pytest

from cw_evals.relations import (
    PROMPT,
    ExpectedRelation,
    RelationCase,
    RelationScore,
    aggregate_relations,
    load_relation_cases,
    relation_input,
    relation_provider,
    run_relations,
    score_relations,
    scripted_answer,
)
from domain_kernel.knowledge import EntityType, RelationKind
from pipeline.application.relations import LlmRelationExtractor, RelationBatch, RelationStage
from pipeline.infrastructure.prompts import load_prompt

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "golden"


def first_case() -> RelationCase:
    return next(c for c in load_relation_cases(GOLDEN) if c.case_id == "01-2026-central-tax")


def test_the_draft_cases_load_with_their_documents() -> None:
    cases = load_relation_cases(GOLDEN)
    assert [(c.case_id, c.label_status) for c in cases] == [
        ("01-2026-central-tax", "draft"),
        ("10-2025-central-tax", "draft"),
        ("17-2025-central-tax", "draft"),
    ]
    for case in cases:
        for expected in case.expected:
            clause = case.document.find_clause(expected.evidence_clause_ref)
            assert clause is not None
            assert " ".join(expected.evidence_quote.split()) in " ".join(clause.text.split())
    case = cases[0]
    assert (case.case_id, case.label_status, case.own_ref) == (
        "01-2026-central-tax",
        "draft",
        "01/2026-Central Tax",
    )
    assert case.document.find_clause("en.p3") is not None
    (expected,) = case.expected
    assert expected.key == ("extends_deadline", "form", "GSTR-3B")
    assert expected.evidence_quote in case.document.find_clause("en.p3").text  # type: ignore[union-attr]


def test_the_scripted_answer_names_targets_by_mention_id() -> None:
    case = first_case()
    assert '"target_mention": "M2"' in scripted_answer(case)
    assert relation_input(case).change_kind.value == "extension"


def test_scripted_scores_one_and_fake_parses_with_nothing_found() -> None:
    cases = load_relation_cases(GOLDEN)
    scripted, _ = run_relations(cases, "scripted", gateway_url="http://unused.test")
    assert (scripted.relation_recall, scripted.relation_precision) == (1.0, 1.0)
    assert (scripted.evidence_validity, scripted.relation_parse_rate) == (1.0, 1.0)
    fake, scores = run_relations(cases, "fake", gateway_url="http://unused.test")
    assert (fake.relation_parse_rate, fake.relation_recall) == (1.0, 0.0)
    assert [s.missed for s in scores] == [
        ("extends_deadline/form/GSTR-3B",),
        ("amends/notification/02/2017-central tax",),
        ("extends_deadline/form/GSTR-3B",),
    ]


def test_the_17_2025_candidates_carry_only_the_review_flag() -> None:
    """Both relations of 17/2025 stage with their quote and date verified; the form is named in
    en.p4, the lead-in, not in the list items, which the validators flag for review."""
    cases = [c for c in load_relation_cases(GOLDEN) if c.case_id == "17-2025-central-tax"]
    with relation_provider("scripted", cases, gateway_url="http://unused.test") as provider:
        stage = RelationStage(LlmRelationExtractor(provider, load_prompt(*PROMPT)))
        batch = stage.execute(relation_input(cases[0])).output
    assert [(c.evidence_clause_ref, c.period_label) for c in batch.candidates] == [
        ("en.p5", "2025-09"),
        ("en.p6", "2025-26 Q2"),
    ]
    assert {i.code for c in batch.candidates for i in c.issues} == {"target_not_in_evidence"}


def test_scores_count_found_proposed_and_evidence() -> None:
    case = first_case()
    empty = score_relations(case, RelationBatch("needs_review"))
    assert (empty.expected, empty.found, empty.proposed, empty.evidence_ok) == (1, 0, 0, 0)
    unparseable = score_relations(case, RelationBatch("unparseable"))
    result = aggregate_relations([empty, unparseable])
    assert result.relation_parse_rate == 0.5
    assert result.relation_precision == 1.0
    assert aggregate_relations([]).relation_recall == 0.0


def test_a_score_without_expectations_does_not_divide_by_zero() -> None:
    score = RelationScore("c", "draft", "ok", 0, 0, 0, 0)
    assert aggregate_relations([score]).relation_recall == 0.0


def test_an_expected_relation_keys_on_kind_and_target() -> None:
    expected = ExpectedRelation(
        RelationKind.AMENDS, EntityType.NOTIFICATION, "02/2017-central tax", "en.p1", "amends x"
    )
    assert expected.key == ("amends", "notification", "02/2017-central tax")
    assert replace(expected, evidence_quote="other").key == expected.key


def test_an_unknown_provider_is_refused() -> None:
    with (
        pytest.raises(ValueError, match="unknown provider"),
        relation_provider("nope", [], gateway_url="http://unused.test"),
    ):
        pass


def test_evidence_validity_counts_every_candidate() -> None:
    both_valid = RelationScore("c", "draft", "ok", 1, 1, 1, 2, candidates=2)
    one_valid = RelationScore("d", "draft", "ok", 1, 1, 1, 1, candidates=2)
    assert aggregate_relations([both_valid]).evidence_validity == 1.0
    assert aggregate_relations([both_valid, one_valid]).evidence_validity == 0.75
