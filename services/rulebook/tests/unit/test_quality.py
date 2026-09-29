"""The rulebook data-quality checks: each one finds the violation planted for it, clean facts
pass, and the ``rulebook-quality`` command reports and exits accordingly."""

import json
from dataclasses import replace
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError

import ontology as ontology_package
from domain_kernel.ids import RuleVersionId
from domain_kernel.knowledge import RelationKind
from domain_kernel.ontology import Ontology
from domain_kernel.status import RuleVersionStatus
from rulebook import quality as cli
from rulebook.application.quality import RunDataQualityChecks
from rulebook.domain.quality import (
    QualityCheck,
    QualityFacts,
    QualityReport,
    RelationFacts,
    VersionFacts,
    Violation,
    effective_dates_disordered,
    in_force_without_verified_citation,
    overlapping_in_force_periods,
    run_checks,
    supersession_cycle,
    unknown_predicate_attribute,
)

SPECIFICATION: dict[str, object] = {
    "all_of": [
        {"attribute": "registration_type", "operator": "eq", "value": "regular"},
        {"attribute": "filing_scheme", "operator": "eq", "value": "regular_monthly"},
    ]
}


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


def rv(number: int) -> RuleVersionId:
    return RuleVersionId(UUID(int=number))


def version(
    number: int,
    *,
    rule_key: str = "gstr3b_monthly",
    version_number: int = 1,
    status: RuleVersionStatus = RuleVersionStatus.PUBLISHED,
    effective_from: date = date(2026, 4, 1),
    effective_to: date | None = None,
    specification: dict[str, object] | None = None,
    citations: int = 1,
    verified: int = 1,
    open_questions: int = 0,
) -> VersionFacts:
    return VersionFacts(
        rule_version_id=rv(number),
        rule_key=rule_key,
        version=version_number,
        status=status,
        effective_from=effective_from,
        effective_to=effective_to,
        specification=SPECIFICATION if specification is None else specification,
        citations=citations,
        verified_citations=verified,
        open_questions=open_questions,
    )


def clean_facts() -> QualityFacts:
    """Two rules; the monthly one was superseded on 1 October by version 2, which cites a
    verified clause, and a draft version 3 carries no citation yet."""
    return QualityFacts(
        versions=(
            version(1, effective_to=date(2026, 10, 1), status=RuleVersionStatus.SUPERSEDED),
            version(2, version_number=2, effective_from=date(2026, 10, 1), citations=2, verified=2),
            version(
                3,
                version_number=3,
                status=RuleVersionStatus.DRAFT,
                effective_from=date(2027, 4, 1),
                citations=0,
                verified=0,
            ),
            version(4, rule_key="gstr1_monthly"),
        ),
        relations=(
            RelationFacts(rv(2), RelationKind.SUPERSEDES, rv(1)),
            RelationFacts(rv(3), RelationKind.EXTENDS_DEADLINE, rv(2)),
        ),
    )


def test_clean_facts_pass_every_check(ontology: Ontology) -> None:
    report = run_checks(clean_facts(), ontology)
    assert report == QualityReport(versions_checked=4, relations_checked=2, violations=())
    assert report.ok


def test_an_in_force_version_needs_every_citation_verified() -> None:
    facts = QualityFacts(
        versions=(
            version(1, citations=0, verified=0),
            version(2, rule_key="gstr1_monthly", status=RuleVersionStatus.SUPERSEDED, verified=0),
            version(3, rule_key="gstr9_annual", citations=3, verified=2),
            version(4, rule_key="cmp08_quarterly", status=RuleVersionStatus.APPROVED, citations=0),
            version(5, rule_key="gstr4_annual", status=RuleVersionStatus.WITHDRAWN, verified=0),
        )
    )
    assert in_force_without_verified_citation(facts) == [
        Violation(
            QualityCheck.IN_FORCE_WITHOUT_VERIFIED_CITATION,
            "gstr3b_monthly@1",
            "published with no citation",
        ),
        Violation(
            QualityCheck.IN_FORCE_WITHOUT_VERIFIED_CITATION,
            "gstr1_monthly@1",
            "superseded with 1 of 1 citations not verified",
        ),
        Violation(
            QualityCheck.IN_FORCE_WITHOUT_VERIFIED_CITATION,
            "gstr9_annual@1",
            "published with 1 of 3 citations not verified",
        ),
    ]


def test_in_force_periods_of_one_rule_must_not_overlap() -> None:
    facts = QualityFacts(
        versions=(
            version(1, status=RuleVersionStatus.SUPERSEDED, effective_to=date(2026, 10, 1)),
            version(2, version_number=2, effective_from=date(2026, 7, 1)),
            # Adjacent half-open periods, another rule and a draft do not overlap anything.
            version(3, rule_key="gstr1_monthly", effective_to=date(2026, 10, 1)),
            version(
                4, rule_key="gstr1_monthly", version_number=2, effective_from=date(2026, 10, 1)
            ),
            version(5, version_number=3, status=RuleVersionStatus.DRAFT),
        )
    )
    assert overlapping_in_force_periods(facts) == [
        Violation(
            QualityCheck.OVERLAPPING_IN_FORCE_PERIODS,
            "gstr3b_monthly@1 and gstr3b_monthly@2",
            "[2026-04-01, 2026-10-01) overlaps [2026-07-01, open)",
        )
    ]


def test_two_open_ended_versions_overlap() -> None:
    facts = QualityFacts(
        versions=(
            version(1, effective_from=date(2026, 10, 1)),
            version(2, version_number=2, status=RuleVersionStatus.SUPERSEDED),
        )
    )
    found = overlapping_in_force_periods(facts)
    assert [violation.subject for violation in found] == ["gstr3b_monthly@2 and gstr3b_monthly@1"]


def test_a_cycle_over_supersedes_and_corrects_is_reported_once() -> None:
    facts = QualityFacts(
        versions=(version(1), version(2, version_number=2), version(3, version_number=3)),
        relations=(
            RelationFacts(rv(2), RelationKind.SUPERSEDES, rv(1)),
            RelationFacts(rv(3), RelationKind.CORRECTS, rv(2)),
            RelationFacts(rv(1), RelationKind.SUPERSEDES, rv(3)),
            # Edges of other kinds never close a replacement cycle.
            RelationFacts(rv(1), RelationKind.EXTENDS_DEADLINE, rv(2)),
        ),
    )
    found = supersession_cycle(facts)
    assert len(found) == 1
    assert found[0].check is QualityCheck.SUPERSESSION_CYCLE
    assert found[0].detail == "3 versions replace each other in a cycle"
    nodes = found[0].subject.split(" -> ")
    assert nodes[0] == nodes[-1]
    assert sorted(nodes[:-1]) == ["gstr3b_monthly@1", "gstr3b_monthly@2", "gstr3b_monthly@3"]


def test_an_acyclic_graph_and_a_cycle_of_other_edges_pass() -> None:
    facts = QualityFacts(
        versions=(version(1), version(2, version_number=2)),
        relations=(
            RelationFacts(rv(2), RelationKind.SUPERSEDES, rv(1)),
            RelationFacts(rv(1), RelationKind.AMENDS, rv(2)),
        ),
    )
    assert supersession_cycle(facts) == []


def test_a_self_loop_is_a_cycle_and_unknown_ids_print_as_uuids() -> None:
    facts = QualityFacts(relations=(RelationFacts(rv(9), RelationKind.CORRECTS, rv(9)),))
    [violation] = supersession_cycle(facts)
    assert violation.subject == f"{rv(9)} -> {rv(9)}"
    assert violation.detail == "1 versions replace each other in a cycle"


def test_a_specification_names_only_ontology_attributes(ontology: Ontology) -> None:
    unknown: dict[str, object] = {
        "any_of": [
            {"attribute": "registration_type", "operator": "eq", "value": "regular"},
            {"not": {"attribute": "turnover_band_2019", "operator": "eq", "value": "x"}},
        ]
    }
    facts = QualityFacts(
        versions=(
            version(1, specification=unknown),
            version(2, version_number=2, specification={"attribute": 7}),
            version(3, version_number=3, specification=unknown, status=RuleVersionStatus.DRAFT),
            version(4, version_number=4, specification=unknown, status=RuleVersionStatus.WITHDRAWN),
            version(5, version_number=5),
        )
    )
    found = unknown_predicate_attribute(facts, ontology)
    assert [(violation.subject, violation.detail) for violation in found] == [
        ("gstr3b_monthly@1", f"not in ontology {ontology.version}: turnover_band_2019"),
        ("gstr3b_monthly@2", found[1].detail),
        ("gstr3b_monthly@3", f"not in ontology {ontology.version}: turnover_band_2019"),
    ]
    assert found[1].detail.startswith("specification cannot be read: ")


def test_a_free_text_predicate_may_name_a_new_attribute_while_a_question_is_open(
    ontology: Ontology,
) -> None:
    free_text: dict[str, object] = {
        "all_of": [
            {"attribute": "registration_type", "operator": "eq", "value": "regular"},
            {"attribute": "sends_goods_to_job_workers", "free_text": "Sends goods to job workers."},
        ]
    }
    structured: dict[str, object] = {
        "attribute": "sends_goods_to_job_workers",
        "operator": "eq",
        "value": True,
    }
    facts = QualityFacts(
        versions=(
            version(1, specification=free_text, open_questions=1),
            version(2, version_number=2, specification=free_text),
            version(3, version_number=3, specification=structured, open_questions=1),
        )
    )
    found = unknown_predicate_attribute(facts, ontology)
    assert [violation.subject for violation in found] == ["gstr3b_monthly@2", "gstr3b_monthly@3"]
    assert {violation.detail for violation in found} == {
        f"not in ontology {ontology.version}: sends_goods_to_job_workers"
    }


def test_effective_to_must_follow_effective_from() -> None:
    facts = QualityFacts(
        versions=(
            version(1, effective_to=date(2026, 4, 1)),
            version(2, version_number=2, effective_to=date(2026, 3, 1)),
            version(3, version_number=3, effective_to=date(2026, 4, 2)),
            version(4, version_number=4),
        )
    )
    assert effective_dates_disordered(facts) == [
        Violation(
            QualityCheck.EFFECTIVE_DATES_DISORDERED,
            "gstr3b_monthly@1",
            "effective_to 2026-04-01 is not after effective_from 2026-04-01",
        ),
        Violation(
            QualityCheck.EFFECTIVE_DATES_DISORDERED,
            "gstr3b_monthly@2",
            "effective_to 2026-03-01 is not after effective_from 2026-04-01",
        ),
    ]


class StubReader:
    def __init__(self, facts: QualityFacts) -> None:
        self.facts = facts
        self.calls = 0

    def read(self) -> QualityFacts:
        self.calls += 1
        return self.facts


def dirty_facts() -> QualityFacts:
    """One violation of every check, plus twelve published versions with no citation."""
    base = clean_facts()
    uncited = tuple(
        version(100 + n, rule_key=f"rule_{n:02d}", citations=0, verified=0) for n in range(12)
    )
    return QualityFacts(
        versions=(
            *base.versions,
            version(10, rule_key="gstr9_annual", effective_from=date(2026, 4, 1)),
            version(11, rule_key="gstr9_annual", version_number=2, effective_from=date(2026, 5, 1)),
            version(12, rule_key="itc04_annual", specification={"attribute": "nope"}),
            version(13, rule_key="eway_bill", effective_to=date(2026, 1, 1)),
            *uncited,
        ),
        relations=(*base.relations, RelationFacts(rv(1), RelationKind.CORRECTS, rv(2))),
    )


def test_the_use_case_runs_every_check_on_what_the_reader_returns(ontology: Ontology) -> None:
    reader = StubReader(dirty_facts())
    report = RunDataQualityChecks(reader, ontology).run()
    assert reader.calls == 1
    assert not report.ok
    assert {check: len(report.of(check)) for check in QualityCheck} == {
        QualityCheck.IN_FORCE_WITHOUT_VERIFIED_CITATION: 12,
        QualityCheck.OVERLAPPING_IN_FORCE_PERIODS: 1,
        QualityCheck.SUPERSESSION_CYCLE: 1,
        QualityCheck.UNKNOWN_PREDICATE_ATTRIBUTE: 1,
        QualityCheck.EFFECTIVE_DATES_DISORDERED: 1,
    }
    assert [v.check for v in report.violations] == sorted(
        (v.check for v in report.violations), key=list(QualityCheck).index
    )


def test_the_command_exits_0_on_clean_facts(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([], reader=StubReader(clean_facts())) == 0
    out = capsys.readouterr().out
    assert out.startswith("data quality: 4 rule versions, 2 relations between rule versions\n")
    assert "  supersession_cycle: ok\n" in out
    assert out.endswith("data quality: clean\n")


def test_the_command_exits_1_and_prints_ten_samples_per_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main([], reader=StubReader(dirty_facts())) == 1
    out = capsys.readouterr().out
    assert "  in_force_without_verified_citation: 12 violation(s)\n" in out
    assert out.count("published with no citation") == cli.SAMPLES
    assert "    ... and 2 more\n" in out
    assert "  effective_dates_disordered: 1 violation(s)\n" in out
    assert out.endswith("data quality: 16 violation(s)\n")


def test_the_json_report_names_every_check_with_its_count_and_samples(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["--json"], reader=StubReader(dirty_facts())) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["checked"] == {"rule_versions": 20, "relations": 3}
    assert [check["check"] for check in report["checks"]] == [c.value for c in QualityCheck]
    by_check = {check["check"]: check for check in report["checks"]}
    uncited = by_check["in_force_without_verified_citation"]
    assert uncited["violations"] == 12
    assert len(uncited["samples"]) == cli.SAMPLES
    assert uncited["samples"][0] == {
        "subject": "rule_00@1",
        "detail": "published with no citation",
    }
    assert by_check["overlapping_in_force_periods"]["samples"] == [
        {
            "subject": "gstr9_annual@1 and gstr9_annual@2",
            "detail": "[2026-04-01, open) overlaps [2026-05-01, open)",
        }
    ]


def test_the_json_report_of_clean_facts_is_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--json"], reader=StubReader(clean_facts())) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert all(check["violations"] == 0 and check["samples"] == [] for check in report["checks"])


class BrokenReader:
    def read(self) -> QualityFacts:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_the_command_exits_2_when_the_database_cannot_be_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main([], reader=BrokenReader()) == 2
    assert capsys.readouterr().err == ("data quality: cannot read the rulebook: OperationalError\n")


def test_a_version_label_and_period_read_well() -> None:
    facts = replace(version(1), effective_to=date(2027, 4, 1))
    assert facts.label == "gstr3b_monthly@1"
    assert facts.period == "[2026-04-01, 2027-04-01)"
    assert facts.in_force
