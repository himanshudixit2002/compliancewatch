"""The packaged seed calendar parses, is review-pending and cited, and behaves as expected on
sample profiles and dates."""

from datetime import date
from pathlib import Path

import pytest

import ontology as ontology_package
from domain_kernel.ontology import AttributeLevel, Ontology
from domain_kernel.predicates import Applicability, PredicateKind
from domain_kernel.recurrence import Frequency
from rulebook.application.seed_loader import (
    SeedError,
    check_against_ontology,
    default_seed_path,
    load_calendar,
    parse_calendar,
)
from rulebook.domain.seed import SeedCalendar, SeedStatus

EXPECTED_KEYS = [
    "gstr3b_monthly",
    "gstr3b_quarterly_group_a",
    "gstr3b_quarterly_group_b",
    "gstr1_monthly",
    "gstr1_quarterly",
    "cmp08_quarterly",
    "gstr4_annual",
    "gstr9_annual",
    "gstr9c_annual",
    "itc04_half_yearly",
    "itc04_annual",
    "e_invoicing",
    "eway_bill",
]


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


@pytest.fixture(scope="module")
def calendar(ontology: Ontology) -> SeedCalendar:
    return load_calendar(ontology)


def test_packaged_file_is_where_the_command_expects_it() -> None:
    assert default_seed_path().name == "gst_calendar.yaml"
    assert Path(str(default_seed_path())).parts[-3:] == ("rulebook", "seed", "gst_calendar.yaml")


def test_every_rule_is_pending_review_with_a_citation_and_a_question(
    calendar: SeedCalendar,
) -> None:
    assert list(calendar.keys) == EXPECTED_KEYS
    assert calendar.ontology_version == "0.2.0"
    for rule in calendar.rules:
        assert rule.seed_status is SeedStatus.NEEDS_REVIEW
        assert rule.source.instrument
        assert rule.source.reference
        assert rule.todo, rule.rule_key
        assert rule.regulator == "cbic"
        assert rule.effective_from == date(2026, 4, 1)


def test_recurring_and_one_off_rules(calendar: SeedCalendar) -> None:
    recurring = {rule.rule_key: rule.recurrence for rule in calendar.rules if rule.is_recurring}
    one_off = [rule.rule_key for rule in calendar.rules if not rule.is_recurring]
    assert one_off == ["e_invoicing", "eway_bill"]
    assert {key: r.frequency for key, r in recurring.items() if r} == {
        "gstr3b_monthly": Frequency.MONTHLY,
        "gstr3b_quarterly_group_a": Frequency.QUARTERLY,
        "gstr3b_quarterly_group_b": Frequency.QUARTERLY,
        "gstr1_monthly": Frequency.MONTHLY,
        "gstr1_quarterly": Frequency.QUARTERLY,
        "cmp08_quarterly": Frequency.QUARTERLY,
        "gstr4_annual": Frequency.ANNUAL,
        "gstr9_annual": Frequency.ANNUAL,
        "gstr9c_annual": Frequency.ANNUAL,
        "itc04_half_yearly": Frequency.HALF_YEARLY,
        "itc04_annual": Frequency.ANNUAL,
    }
    for rule in calendar.rules:
        if not rule.is_recurring:
            assert rule.obligation_template.due_in_days is not None


@pytest.mark.parametrize(
    ("rule_key", "on", "period_label", "due"),
    [
        ("gstr3b_monthly", date(2026, 9, 15), "2026-09", date(2026, 10, 20)),
        ("gstr1_monthly", date(2026, 9, 15), "2026-09", date(2026, 10, 11)),
        ("gstr3b_quarterly_group_a", date(2026, 8, 1), "2026-27 Q2", date(2026, 10, 22)),
        ("gstr3b_quarterly_group_b", date(2026, 8, 1), "2026-27 Q2", date(2026, 10, 24)),
        ("gstr1_quarterly", date(2027, 2, 1), "2026-27 Q4", date(2027, 4, 13)),
        ("cmp08_quarterly", date(2026, 5, 1), "2026-27 Q1", date(2026, 7, 18)),
        ("gstr4_annual", date(2026, 9, 1), "2026-27", date(2027, 6, 30)),
        ("gstr9_annual", date(2025, 9, 1), "2025-26", date(2026, 12, 31)),
        ("gstr9c_annual", date(2025, 9, 1), "2025-26", date(2026, 12, 31)),
        ("itc04_half_yearly", date(2026, 6, 1), "2026-27 H1", date(2026, 10, 25)),
        ("itc04_half_yearly", date(2026, 12, 1), "2026-27 H2", date(2027, 4, 25)),
        ("itc04_annual", date(2026, 12, 1), "2026-27", date(2027, 4, 25)),
    ],
)
def test_due_dates_follow_the_cited_calendar(
    calendar: SeedCalendar, rule_key: str, on: date, period_label: str, due: date
) -> None:
    recurrence = calendar.get(rule_key).recurrence
    assert recurrence is not None
    period = recurrence.period_containing(on)
    assert period.label == period_label
    assert recurrence.due_date(period) == due


REGULAR_MONTHLY = {
    "registration_type": "regular",
    "filing_scheme": "regular_monthly",
    "turnover_band": "5_crore_to_10_crore",
    "peak_turnover_band": "5_crore_to_10_crore",
    "state_codes": ["29"],
    "generates_eway_bills": True,
}
QRMP_KARNATAKA = {
    **REGULAR_MONTHLY,
    "filing_scheme": "regular_qrmp",
    "turnover_band": "2_crore_to_5_crore",
    "peak_turnover_band": "2_crore_to_5_crore",
}
QRMP_DELHI = {**QRMP_KARNATAKA, "state_codes": ["07"]}
COMPOSITION = {
    "registration_type": "composition",
    "filing_scheme": "composition",
    "turnover_band": "40_lakh_to_75_lakh",
    "peak_turnover_band": "40_lakh_to_75_lakh",
    "generates_eway_bills": False,
}


@pytest.mark.parametrize(
    ("profile", "applies", "not_applicable"),
    [
        (
            REGULAR_MONTHLY,
            {
                "gstr3b_monthly",
                "gstr1_monthly",
                "gstr9_annual",
                "gstr9c_annual",
                "e_invoicing",
                "eway_bill",
            },
            {"gstr3b_quarterly_group_a", "gstr1_quarterly", "cmp08_quarterly", "gstr4_annual"},
        ),
        (
            QRMP_KARNATAKA,
            {"gstr3b_quarterly_group_a", "gstr1_quarterly", "gstr9_annual"},
            {"gstr3b_quarterly_group_b", "gstr3b_monthly", "gstr9c_annual", "e_invoicing"},
        ),
        (QRMP_DELHI, {"gstr3b_quarterly_group_b"}, {"gstr3b_quarterly_group_a"}),
        (
            COMPOSITION,
            {"cmp08_quarterly", "gstr4_annual"},
            {"gstr3b_monthly", "gstr1_monthly", "gstr9_annual", "e_invoicing", "eway_bill"},
        ),
    ],
)
def test_specifications_decide_sample_profiles(
    calendar: SeedCalendar,
    ontology: Ontology,
    profile: dict[str, object],
    applies: set[str],
    not_applicable: set[str],
) -> None:
    attributes = ontology.validate_attributes(profile)
    outcomes = {
        rule.rule_key: rule.specification.evaluate(attributes, ontology) for rule in calendar.rules
    }
    assert applies <= {k for k, v in outcomes.items() if v is Applicability.APPLIES}
    assert not_applicable <= {k for k, v in outcomes.items() if v is Applicability.NOT_APPLICABLE}


def test_job_work_rules_are_unsure_until_the_analyst_adds_the_attribute(
    calendar: SeedCalendar, ontology: Ontology
) -> None:
    above_5_crore = ontology.validate_attributes(REGULAR_MONTHLY)
    below_5_crore = ontology.validate_attributes(QRMP_KARNATAKA)
    half_yearly = calendar.get("itc04_half_yearly")
    annual = calendar.get("itc04_annual")
    # The turnover predicate decides which of the two could apply; the job-work condition is
    # free text, so the one that could apply stays unsure and the other is ruled out.
    assert half_yearly.specification.evaluate(above_5_crore, ontology) is Applicability.UNSURE
    assert annual.specification.evaluate(above_5_crore, ontology) is Applicability.NOT_APPLICABLE
    assert annual.specification.evaluate(below_5_crore, ontology) is Applicability.UNSURE
    assert (
        half_yearly.specification.evaluate(below_5_crore, ontology) is Applicability.NOT_APPLICABLE
    )
    for rule in (half_yearly, annual):
        free_text = [
            p for p in rule.specification.predicates() if p.kind is PredicateKind.FREE_TEXT
        ]
        assert [p.attribute for p in free_text] == ["sends_goods_to_job_workers"]
    assert any("attribute" in question for question in half_yearly.todo)


def test_levels_and_structured_predicates_match_the_ontology(
    calendar: SeedCalendar, ontology: Ontology
) -> None:
    assert check_against_ontology(calendar, ontology) == []
    assert calendar.get("e_invoicing").level is AttributeLevel.ENTITY
    assert calendar.get("gstr3b_monthly").level is AttributeLevel.REGISTRATION


def test_loader_reports_every_problem_at_once(ontology: Ontology) -> None:
    text = (
        'version: "0.1.0"\nontology_version: "0.2.0"\nrules:\n'
        "  - rule_key: Bad Key\n    title: x\n    summary: x\n    regulator: cbic\n"
        "    level: registration\n"
        "    specification: {attribute: registration_type, operator: eq, value: regular}\n"
        "    obligation_template: {title: x, due_in_days: 1}\n"
        '    effective_from: "2026-04-01"\n    source: {instrument: a, reference: b}\n'
        "    seed_status: needs_review\n    todo: [q]\n"
        "  - rule_key: no_such_attribute\n    title: x\n    summary: x\n    regulator: cbic\n"
        "    level: registration\n"
        "    specification: {attribute: made_up, operator: eq, value: 1}\n"
        "    obligation_template: {title: x, due_in_days: 1}\n"
        '    effective_from: "2026-04-01"\n    source: {instrument: a, reference: b}\n'
        "    seed_status: needs_review\n    todo: [q]\n"
    )
    with pytest.raises(SeedError) as info:
        parse_calendar(text, ontology)
    assert len(info.value.problems) == 1
    assert "snake_case" in info.value.problems[0]
    text_without_bad_key = text.replace("Bad Key", "good_key")
    with pytest.raises(SeedError) as info:
        parse_calendar(text_without_bad_key, ontology)
    assert any("made_up" in problem for problem in info.value.problems)


@pytest.mark.parametrize(
    ("snippet", "message"),
    [
        ("- version\n", "must be a mapping"),
        ("version: x\nrules: 1\n", "rules must be a list"),
        ('version: "0.1.0"\nontology_version: "0.2.0"\nrules: []\n', "at least one rule"),
    ],
)
def test_loader_rejects_the_wrong_shape(ontology: Ontology, snippet: str, message: str) -> None:
    with pytest.raises(SeedError, match=message):
        parse_calendar(snippet, ontology)


def test_ontology_version_mismatch_is_reported(ontology: Ontology) -> None:
    text = (
        default_seed_path()
        .read_text(encoding="utf-8")
        .replace('ontology_version: "0.2.0"', 'ontology_version: "0.1.0"')
    )
    with pytest.raises(SeedError, match=r"written for ontology 0\.1\.0"):
        parse_calendar(text, ontology)
