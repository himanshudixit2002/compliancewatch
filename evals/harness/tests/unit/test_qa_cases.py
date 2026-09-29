"""KAG golden cases: loading, the planner's JSON shape and the labels of scripted citations."""

import json
from datetime import date
from pathlib import Path

import pytest

from cw_evals.qa.cases import (
    CaseError,
    ClauseSupport,
    SeedSupport,
    by_category,
    load_qa_case,
    load_qa_cases,
    plan_text,
    planner_json,
    scripted_answer,
)
from domain_kernel.knowledge import EntityType
from qa.domain.plan_schema import FIELDS

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "golden"
CASES = GOLDEN / "qa" / "kag" / "cases"
SOURCES = {"n01_2026": "01/2026-Central Tax", "n17_2025": "17/2025-Central Tax"}


def test_the_golden_set_has_its_draft_cases_by_category() -> None:
    cases = load_qa_cases(GOLDEN)
    assert by_category(cases) == {
        "single_hop": 20,
        "multi_hop": 16,
        "date_threshold": 10,
        "must_refuse": 10,
    }
    assert {case.label_status for case in cases} == {"draft"}
    assert {case.reviewed_by for case in cases} == {""}
    assert all(case.path.stem == case.case_id for case in cases)


def test_a_case_reads_its_facts_supports_and_scripts() -> None:
    case = load_qa_case(CASES / "mh-acme-gstr3b-2026-03.yaml")
    assert (case.category, case.business, case.as_of) == (
        "multi_hop",
        "acme_monthly",
        date(2026, 4, 22),
    )
    assert case.answerable
    (fact,) = case.expected.facts
    assert (fact.kind, fact.value) == ("date", "2026-04-21")
    assert isinstance(fact.support, ClauseSupport)
    assert case.scripted.plan is not None
    assert case.scripted.answer is not None
    seeded = load_qa_case(CASES / "mh-delhi-next-gstr3b.yaml")
    assert isinstance(seeded.expected.facts[0].support, SeedSupport)
    assert seeded.scripted.plan is None
    entity = load_qa_case(CASES / "sh-10-2025-amends.yaml").expected.facts[0]
    assert (entity.kind, entity.entity_type) == ("entity", EntityType.NOTIFICATION)
    refused = load_qa_case(CASES / "mr-injection-gstin.yaml")
    assert not refused.answerable
    assert refused.refusal_reason == "injection"


def test_planner_json_writes_every_field_of_every_step() -> None:
    plan = {
        "as_of": date(2026, 4, 1),
        "steps": [
            {"id": "s1", "op": "get_obligations", "due_from": date(2026, 5, 1)},
            {"id": "s2", "op": "answer", "sources": ["s1"]},
        ],
    }
    written = planner_json(plan)
    assert written["as_of"] == "2026-04-01"
    assert [list(step) for step in written["steps"]] == [list(FIELDS), list(FIELDS)]
    assert written["steps"][0]["due_from"] == "2026-05-01"
    assert written["steps"][0]["text"] is None
    assert json.loads(plan_text({"steps": []})) == {"as_of": None, "steps": []}


PROMPT = "\n".join(
    [
        "Question: when?",
        "",
        "Clauses:",
        "[C1] en.p5 (17/2025-Central Tax)",
        "(i) sub-section (1) of section 39 ...",
        "",
        "[C2] en.p3 (01/2026-Central Tax)",
        "G.S.R ... hereby extends ...",
    ]
)


def test_a_scripted_citation_gets_the_label_the_evidence_gives_its_clause() -> None:
    answer = {
        "covered": True,
        "answer": "Extended.",
        "citations": [
            {"document": "n01_2026", "clause_ref": "en.p3", "quote": "hereby extends"},
            {"document": "n17_2025", "clause_ref": "en.p6", "quote": "proviso"},
            {"clause": "C13", "quote": "not in any clause"},
        ],
    }
    written = scripted_answer(answer, PROMPT, SOURCES)
    assert written == {
        "covered": True,
        "answer": "Extended.",
        "citations": [
            {"clause": "C2", "quote": "hereby extends"},
            {"clause": "n17_2025/en.p6", "quote": "proviso"},
            {"clause": "C13", "quote": "not in any clause"},
        ],
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("- a list\n", "a case is a mapping"),
        ("case_id: [unclosed\n", "not YAML"),
        ("case_id: x\n", "missing"),
    ],
)
def test_a_malformed_case_file_is_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "x.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CaseError, match=message):
        load_qa_case(path)


def test_unknown_keys_and_bad_shapes_are_refused(tmp_path: Path) -> None:
    source = (CASES / "sh-01-2026-effect.yaml").read_text(encoding="utf-8")
    path = tmp_path / "sh-01-2026-effect.yaml"
    path.write_text(source + "extra: 1\n", encoding="utf-8")
    with pytest.raises(CaseError, match="unknown \\['extra'\\]"):
        load_qa_case(path)
    path.write_text(source.replace("scripted:\n", "scripted:\n  guess: 1\n"), encoding="utf-8")
    with pytest.raises(CaseError, match="unknown keys"):
        load_qa_case(path)
    path.write_text(source.replace("as_of: 2026-09-28", "as_of: someday"), encoding="utf-8")
    with pytest.raises(CaseError, match=r"sh-01-2026-effect\.yaml"):
        load_qa_case(path)
