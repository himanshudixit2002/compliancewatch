"""The qa suite end to end with the scripted labels: the gates pass, refusals hold, and a model
call the labels do not cover stops the run."""

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from cw_evals.qa.cases import QaCase, Scripted
from cw_evals.qa.providers import DECLINED, ScriptedQaProvider, UnscriptedCallError, qa_model
from cw_evals.qa.suite import QaRun, load_qa_suite, run_qa
from cw_evals.qa.world import WorldSpec
from cw_evals.run import main
from cw_evals.thresholds import GATES, evaluate
from domain_kernel.llm import CompletionRequest
from qa.application.solver import StepValue
from qa.domain.plan import ValueKind

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


def test_one_case_needs_the_planner_retry(runs: dict[str, QaRun]) -> None:
    """Its first plan refers to a later step; the retry validates. The first-try share is
    reported below 1.0 and gates nothing."""
    retried = next(s for s in runs["qa_kag"].scores if s.case_id == "sh-15-2025-power")
    assert (retried.plan_valid, retried.plan_first_try, retried.grounded) == (True, False, True)
    first_try = runs["qa_kag"].aggregate.plan_first_try_validity
    assert first_try is not None
    assert first_try < 1.0
    assert "plan_first_try_validity" not in {g.metric for gates in GATES.values() for g in gates}


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


def failed_gates(runs: dict[str, QaRun]) -> set[tuple[str, str]]:
    measured: dict[str, dict[str, object]] = {
        suite: {"scripted": run.aggregate} for suite, run in runs.items()
    }
    return {
        (g.gate.suite, g.gate.metric)
        for g in evaluate("ci", measured)
        if g.gate.suite.startswith("qa_") and g.gate.provider == "scripted" and not g.passed
    }


def test_a_broken_operator_fails_the_kag_gates(
    suite: tuple[WorldSpec, list[QaCase]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """retrieve_clauses finding nothing leaves the KAG layer no clause; hybrid search still
    answers, but that answer does not count for the KAG run and the empty bundle is a solver
    failure."""
    spec, cases = suite
    chosen = [c for c in cases if c.case_id in {"sh-01-2026-effect", "sh-15-2025-threshold"}]
    monkeypatch.setattr(
        "qa.application.solver._Run.retrieve", lambda *_: StepValue(ValueKind.CLAUSES)
    )
    runs = run_qa(spec, chosen, "scripted", gateway_url=UNUSED)
    for score in runs["qa_kag"].scores:
        assert (score.layer, score.outcome, score.reason) == ("hybrid", "answered", None)
        assert score.solver_failed
        assert not score.grounded
        assert "decided by the hybrid layer after no_evidence, not kag" in score.problems
    assert runs["qa_hybrid"].aggregate.grounded_answer_rate == 1.0
    assert {("qa_kag", "solver_success"), ("qa_kag", "grounded_answer_rate")} <= failed_gates(runs)


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


def answer_prompt(clause: str) -> str:
    return "\n".join(
        [
            "Question: Was it extended till 21 April 2026?",
            "Date of the question: 2026-04-22",
            "",
            "Clauses:",
            "[C1] en.p3 (01/2026-Central Tax)",
            clause,
            "",
            "Facts:",
            "F1: gstr3b_monthly (File GSTR-3B) is in force on 2026-04-22",
        ]
    )


def test_a_scripted_answer_needs_its_dates_in_the_evidence(
    suite: tuple[WorldSpec, list[QaCase]],
) -> None:
    """The date the case expects must be written in the evidence, not only in the question."""
    _, cases = suite
    case = next(c for c in cases if c.case_id == "mh-acme-gstr3b-2026-03")
    provider = ScriptedQaProvider([case], {"n01_2026": "01/2026-Central Tax"})
    provider.current_case = case.case_id
    clause = "extends the due date for March, 2026 till the {} day of April, 2026"

    def reply(prompt: str) -> str:
        request = CompletionRequest(
            feature="qa",
            prompt_version="qa.answer@1",
            system="",
            user=prompt,
            metadata={"layer": "kag"},
        )
        return provider.complete(request).text

    assert '"clause": "C1"' in reply(answer_prompt(clause.format("twenty -first")))
    assert provider.notes == []
    for shifted in ("twentieth", "twenty-second"):
        assert reply(answer_prompt(clause.format(shifted))) == DECLINED
    assert provider.notes == ["scripted answer withheld: 2026-04-21 not in the kag evidence"] * 2


def test_an_operator_that_finds_no_obligation_fails_the_kag_gates(
    suite: tuple[WorldSpec, list[QaCase]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_obligations finding nothing still leaves the clauses the plan follows, but the due
    dates only the obligations give are missing, so the scripted answers are withheld."""
    spec, cases = suite
    chosen = [c for c in cases if c.case_id.startswith(("dt-acme-", "dt-delhi-", "mh-acme-annual"))]
    monkeypatch.setattr(
        "qa.application.solver._Run.get_obligations",
        lambda *_: StepValue(ValueKind.OBLIGATIONS),
    )
    runs = run_qa(spec, chosen, "scripted", gateway_url=UNUSED)
    withheld = {
        s.case_id
        for s in runs["qa_kag"].scores
        if s.reason == "answerer_declined" and "scripted answer withheld" in s.problems[0]
    }
    assert withheld == {
        "dt-acme-april-2026-and-march",
        "dt-delhi-q1-2026-and-last-extension",
        "mh-acme-annual-return-due",
    }
    assert ("qa_kag", "grounded_answer_rate") in failed_gates(runs)


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
