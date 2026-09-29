"""``eval-golden-check``: the shipped set passes, and each kind of broken label is reported."""

import shutil
from pathlib import Path

import pytest

from cw_evals.qa.check import check, main, quote_in, seed_value
from cw_evals.qa.world import load_world

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "golden"
SEED = ROOT.parent / "services" / "rulebook" / "seed" / "gst_calendar.yaml"
CASES = Path("qa") / "kag" / "cases"


@pytest.fixture
def golden(tmp_path: Path) -> Path:
    """A copy of evals/golden with the seed calendar where the world file expects it."""
    copy = tmp_path / "evals" / "golden"
    shutil.copytree(GOLDEN, copy)
    seed = tmp_path / "services" / "rulebook" / "seed"
    seed.mkdir(parents=True)
    shutil.copy(SEED, seed / SEED.name)
    return copy


def edit(golden: Path, name: str, old: str, new: str) -> None:
    path = golden / CASES / name if name.endswith(".yaml") and "/" not in name else golden / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def problems_of(golden: Path) -> list[str]:
    return check(golden)[0]


def test_the_shipped_golden_set_has_no_problem() -> None:
    problems, cases = check(GOLDEN)
    assert problems == []
    assert len(cases) == 56


def test_main_prints_the_counts_and_exits_on_problems(
    golden: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--golden", str(golden)]) == 0
    out = capsys.readouterr().out
    assert "56 cases (single_hop 20, multi_hop 16, date_threshold 10, must_refuse 10" in out
    assert "draft 56, reviewed 0, approved 0), 0 problems" in out
    edit(golden, "sh-01-2026-effect.yaml", "reviewed_by: ''", "reviewed_by: someone")
    assert main(["--golden", str(golden)]) == 1
    assert "problem: sh-01-2026-effect.yaml: a draft has labelled_by" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("name", "old", "new", "problem"),
    [
        (
            "sh-01-2026-effect.yaml",
            "quote: come into effect from 20th day of April, 2026",
            "quote: come into effect from 21st day of April, 2026",
            "is not in n01_2026 en.p4",
        ),
        (
            "mh-acme-next-gstr3b.yaml",
            "due_day: 20",
            "due_day: 21",
            "seed gstr3b_monthly.recurrence is",
        ),
        (
            "mh-acme-next-gstr3b.yaml",
            "seed_rule: gstr3b_monthly",
            "seed_rule: gstr3b_weekly",
            "no seed rule 'gstr3b_weekly'",
        ),
        (
            "sh-01-2026-effect.yaml",
            "label_status: draft",
            "label_status: approved",
            "an approved label names a reviewed_by other than labelled_by",
        ),
        (
            "sh-01-2026-effect.yaml",
            "case_id: sh-01-2026-effect",
            "case_id: sh-01-2026-effects",
            "must match the file name",
        ),
        (
            "mh-acme-annual-return.yaml",
            "business: acme_monthly",
            "business: acme_weekly",
            "business 'acme_weekly' is not in the world",
        ),
        (
            "sh-15-2025-threshold.yaml",
            "rule_key: gstr9_annual",
            "rule_key: gstr1_monthly",
            "scripted.plan is not a valid plan",
        ),
        (
            "sh-01-2026-effect.yaml",
            "      clause_ref: en.p4\n      quote: This notification",
            "      clause_ref: en.p2\n      quote: This notification",
            "is not an expected citation",
        ),
        (
            "sh-01-2026-effect.yaml",
            "value: 2026-04-20",
            "value: 2026-04-21",
            "date 2026-04-21 is not in its quote 'come into effect from 20th day",
        ),
        (
            "dt-acme-april-2026-and-march.yaml",
            "value: 2026-04-21",
            "value: 2026-04-22",
            "date 2026-04-22 is not in its quote 'till the twenty -first day of April, 2026'",
        ),
        (
            "sh-15-2025-threshold.yaml",
            "value: two crore rupees",
            "value: three crore rupees",
            "'three crore rupees' is not in its quote 'up to two crore rupees'",
        ),
        (
            "mr-listing-08-2025.yaml",
            "covered: true",
            "covered: false",
            "a must-refuse case scripts covered: true with at least one citation",
        ),
        (
            "mr-listing-12-2025.yaml",
            "    citations:\n    - clause: C13\n"
            "      quote: extended the due date for the return\n",
            "    citations: []\n",
            "a must-refuse case scripts covered: true with at least one citation",
        ),
        (
            "mr-listing-08-2025.yaml",
            "quote: the late fee is waived in full",
            "quote: section 3 read with section 5",
            "cites a quote that holds",
        ),
        (
            "mr-listing-12-2025.yaml",
            "answer: The notification extended the due date for the return.",
            "answer: The due date moved to 27 August 2025.",
            "states no date or amount",
        ),
        (
            "mr-out-of-domain-fssai.yaml",
            "clause: C13",
            "clause: thirteen",
            "a label looks like C13",
        ),
        (
            "mr-injection-gstin.yaml",
            "refusal_reason: injection",
            "refusal_reason: null",
            "names its refusal_reason",
        ),
        (
            "sh-01-2026-effect.yaml",
            "category: single_hop",
            "category: trivia",
            "category 'trivia' is not one of",
        ),
        (
            "sh-01-2026-effect.yaml",
            "outcome: answered",
            "outcome: not_covered",
            "must_refuse cases, and only they, expect not_covered",
        ),
        (
            "qa/kag/world.yaml",
            'quote: "This notification shall come into effect from 20th day of April, 2026."',
            'quote: "This notification shall come into effect from 19th day of April, 2026."',
            "world.yaml: 'This notification shall come into effect from 19th day",
        ),
        (
            "qa/kag/world.yaml",
            "Seeks to extend date of filing GSTR-3B.",
            "Seeks to extend every date.",
            "gstr3b_extension_2025_09 is titled with its notification's listing title",
        ),
        (
            "qa/kag/world.yaml",
            "rule_key: gstr9_annual\n    seed: true",
            "rule_key: gstr9_monthly\n    seed: true",
            "world.yaml",
        ),
    ],
)
def test_a_broken_label_is_reported(
    golden: Path, name: str, old: str, new: str, problem: str
) -> None:
    edit(golden, name, old, new)
    found = problems_of(golden)
    assert any(problem in item for item in found), found


def test_a_question_past_the_structured_layer_needs_a_plan(golden: Path) -> None:
    path = golden / CASES / "sh-01-2026-effect.yaml"
    text = path.read_text(encoding="utf-8")
    start, end = text.index("  plan:\n"), text.index("  answer:\n")
    path.write_text(text[:start] + text[end:], encoding="utf-8")
    assert any("needs scripted.plan" in item for item in problems_of(golden))


def test_duplicate_ids_and_unreadable_cases_are_reported(golden: Path) -> None:
    cases = golden / CASES
    shutil.copy(cases / "sh-01-2026-effect.yaml", cases / "sh-01-2026-effect-copy.yaml")
    (cases / "broken.yaml").write_text("- not a case\n", encoding="utf-8")
    found = problems_of(golden)
    assert "case_id sh-01-2026-effect is used 2 times" in found
    assert any("broken.yaml: a case is a mapping" in item for item in found)


def test_an_unreadable_world_is_one_problem(tmp_path: Path) -> None:
    problems, cases = check(tmp_path)
    assert cases == []
    assert len(problems) == 1
    assert problems[0].startswith("world.yaml:")


def test_quotes_compare_word_for_word_with_whitespace_aside() -> None:
    assert quote_in("due date  for", "the due\ndate for the return")
    assert not quote_in("due dates", "the due date")
    assert not quote_in("anything", None)


def test_seed_values_are_read_by_dotted_path() -> None:
    spec = load_world(GOLDEN)
    assert seed_value(spec, "gstr3b_monthly", "recurrence.due_day") == 20
    assert seed_value(spec, "gstr3b_monthly", "effective_from") == "2026-04-01"
    with pytest.raises(KeyError, match="has no"):
        seed_value(spec, "gstr3b_monthly", "recurrence.weekday")
