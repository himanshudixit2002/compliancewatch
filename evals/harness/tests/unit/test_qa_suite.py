"""The qa suite end to end with the scripted labels: the gates pass, refusals hold, and a model
call the labels do not cover stops the run."""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from cw_evals.qa.cases import QaCase, Scripted
from cw_evals.qa.providers import ScriptedQaProvider, UnscriptedCallError, qa_model
from cw_evals.qa.suite import QaRun, load_qa_suite, run_qa
from cw_evals.qa.world import WorldSpec
from cw_evals.run import main
from cw_evals.thresholds import GATES, evaluate
from domain_kernel.llm import CompletionRequest

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "golden"
SEED = ROOT.parent / "services" / "rulebook" / "seed" / "gst_calendar.yaml"
UNUSED = "http://unused.test"


@pytest.fixture(scope="module")
def suite() -> tuple[WorldSpec, list[QaCase]]:
    return load_qa_suite(GOLDEN)


@pytest.fixture(scope="module")
def runs(suite: tuple[WorldSpec, list[QaCase]]) -> dict[str, QaRun]:
    spec, cases = suite
    return run_qa(spec, cases, "scripted", gateway_url=UNUSED)


def test_the_scripted_runs_pass_every_ci_qa_gate(runs: dict[str, QaRun]) -> None:
    measured: dict[str, dict[str, object]] = {
        suite: {"scripted": run.aggregate} for suite, run in runs.items()
    }
    gates = [
        g
        for g in evaluate("ci", measured)
        if g.gate.suite.startswith("qa_") and g.gate.provider == "scripted"
    ]
    assert len(gates) == 9
    assert all(g.passed for g in gates), [g for g in gates if not g.passed]
    kag, hybrid = runs["qa_kag"].aggregate, runs["qa_hybrid"].aggregate
    assert kag.grounded_answer_rate == 1.0
    assert hybrid.grounded_answer_rate is not None
    assert hybrid.grounded_answer_rate <= kag.grounded_answer_rate
    assert hybrid.plan_validity is None


def test_every_must_refuse_case_is_refused_by_the_citation_check(runs: dict[str, QaRun]) -> None:
    for run in runs.values():
        refused = [s for s in run.scores if not s.answerable]
        assert len(refused) == 10
        assert all(s.refused for s in refused)
        assert {s.reason for s in refused} <= {"citation_check_failed", "no_evidence"}


def test_the_layers_decide_as_the_cases_expect(runs: dict[str, QaRun]) -> None:
    by_id = {s.case_id: s for s in runs["qa_kag"].scores}
    assert by_id["mh-acme-next-gstr3b"].layer == "structured"
    assert by_id["mh-acme-gstr3b-2026-03"].layer == "kag"
    assert by_id["sh-10-2025-serial-7"].layer == "hybrid"
    assert by_id["mr-listing-12-2025"].reason == "citation_check_failed"
    assert {s.layer for s in runs["qa_hybrid"].scores} == {"structured", "hybrid"}


def test_an_answer_quoting_what_its_clause_lacks_is_refused(
    suite: tuple[WorldSpec, list[QaCase]],
) -> None:
    spec, cases = suite
    case = next(c for c in cases if c.case_id == "sh-01-2026-effect")
    answer = dict(case.scripted.answer or {})
    answer["answer"] = "It came into effect from 1 April 2026."
    answer["citations"] = [
        {"document": "n01_2026", "clause_ref": "en.p4", "quote": "come into effect from 1st April"}
    ]
    bent = replace(case, scripted=replace(case.scripted, answer=answer))
    score = run_qa(spec, [bent], "scripted", gateway_url=UNUSED)["qa_kag"].scores[0]
    assert (score.outcome, score.reason, score.passed) == (
        "not_covered",
        "citation_check_failed",
        False,
    )


def test_a_call_the_labels_do_not_cover_stops_the_run(
    suite: tuple[WorldSpec, list[QaCase]],
) -> None:
    spec, cases = suite
    case = next(c for c in cases if c.case_id == "sh-01-2026-effect")
    unscripted = replace(case, scripted=Scripted(plan=case.scripted.plan))
    with pytest.raises(UnscriptedCallError, match="sh-01-2026-effect has no scripted answer"):
        run_qa(spec, [unscripted], "scripted", gateway_url=UNUSED)


def test_main_exits_2_on_an_unscripted_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    golden = tmp_path / "evals" / "golden"
    shutil.copytree(GOLDEN, golden)
    (tmp_path / "services" / "rulebook" / "seed").mkdir(parents=True)
    shutil.copy(SEED, tmp_path / "services" / "rulebook" / "seed" / SEED.name)
    path = golden / "qa" / "kag" / "cases" / "sh-01-2026-effect.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: text.index("  answer:\n")] + text[text.index("refusal_reason:") :])
    args = ["--suite", "qa", "--provider", "scripted", "--golden", str(golden)]
    assert main([*args, "--reports", str(tmp_path / "reports")]) == 2
    assert "eval: aborted: case sh-01-2026-effect" in capsys.readouterr().out


def test_the_planner_retry_gets_the_retry_plan(suite: tuple[WorldSpec, list[QaCase]]) -> None:
    _, cases = suite
    case = next(c for c in cases if c.case_id == "sh-01-2026-effect")
    retry: dict[str, object] = {"steps": []}
    provider = ScriptedQaProvider(
        [replace(case, scripted=replace(case.scripted, plan_retry=retry))], {}
    )
    provider.current_case = case.case_id
    first, second = (
        provider.complete(
            CompletionRequest(
                feature="qa",
                prompt_version="qa.plan@1",
                system="",
                user="q",
                metadata={"attempt": attempt},
            )
        ).text
        for attempt in ("1", "2")
    )
    assert '"rules_in_force"' in first
    assert second == '{"as_of": null, "steps": []}'


def test_an_unknown_provider_is_refused(suite: tuple[WorldSpec, list[QaCase]]) -> None:
    _, cases = suite
    with (
        pytest.raises(ValueError, match="unknown provider"),
        qa_model("oracle", cases, {}, gateway_url=""),
    ):
        pass


def test_the_ci_profile_reads_the_fake_provider_for_response_and_safety() -> None:
    fake = {
        (g.suite, g.metric)
        for g in GATES["ci"]
        if g.provider == "fake" and g.suite.startswith("qa")
    }
    assert fake == {
        ("qa_kag", "response_rate"),
        ("qa_kag", "answer_safety"),
        ("qa_hybrid", "response_rate"),
        ("qa_hybrid", "answer_safety"),
    }
    assert not [g for g in GATES["nightly"] if g.suite.startswith("qa")]
