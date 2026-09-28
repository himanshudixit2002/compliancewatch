"""The relation suite: loading the golden cases, the scripted and fake runs, the scores."""

from dataclasses import replace
from pathlib import Path

import pytest

from cw_evals.relations import (
    ExpectedRelation,
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
from pipeline.application.relations import RelationBatch

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "golden"


def test_the_draft_case_loads_with_its_document() -> None:
    (case,) = load_relation_cases(GOLDEN)
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
    (case,) = load_relation_cases(GOLDEN)
    assert '"target_mention": "M2"' in scripted_answer(case)
    assert relation_input(case).change_kind.value == "extension"


def test_scripted_scores_one_and_fake_parses_with_nothing_found() -> None:
    cases = load_relation_cases(GOLDEN)
    scripted, _ = run_relations(cases, "scripted", gateway_url="http://unused.test")
    assert (scripted.relation_recall, scripted.relation_precision) == (1.0, 1.0)
    assert (scripted.evidence_validity, scripted.relation_parse_rate) == (1.0, 1.0)
    fake, scores = run_relations(cases, "fake", gateway_url="http://unused.test")
    assert (fake.relation_parse_rate, fake.relation_recall) == (1.0, 0.0)
    assert scores[0].missed == ("extends_deadline/form/GSTR-3B",)


def test_scores_count_found_proposed_and_evidence() -> None:
    (case,) = load_relation_cases(GOLDEN)
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
