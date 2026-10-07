import hashlib
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx2
import pytest

from cw_evals import providers
from cw_evals.cases import load_extraction_set
from cw_evals.metrics import aggregate, score
from cw_evals.providers import fake_gateway, provider_for, scripted
from cw_evals.qa.cases import load_qa_cases
from cw_evals.relations import load_relation_cases, run_relations
from cw_evals.report import RunResults, markdown
from cw_evals.run import main, run_extraction
from cw_evals.thresholds import GATES, evaluate
from domain_kernel.documents import ExtractionContext
from ontology import load
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.domain.prompt import PromptText
from pipeline.infrastructure.gateway import RESIDENCY_PROBLEM, GatewayProvider

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "golden"
REGISTRY = ROOT.parent / "services" / "llm-gateway" / "prompts" / "registry.toml"
PROMPT_DIRS = {
    "extraction": ROOT.parent / "services" / "pipeline" / "prompts",
    "qa": ROOT.parent / "services" / "qa" / "prompts",
}
"""Where each prompt area's files are, by the part of the name before the dot."""
PROMPT = PromptText("extraction.rule_candidate", "1", "regulatory-intelligence", "Extract.")
CTX = ExtractionContext("cbic_notifications", PROMPT.ref, "test", "0.2.0")
QA_SUITES = ("qa_kag", "qa_hybrid")


def test_golden_set_loads_with_its_unlabelled_count() -> None:
    extraction = load_extraction_set(GOLDEN)
    assert extraction.indexed == 50
    assert len(extraction.labelled) >= 1
    assert extraction.unlabelled == extraction.indexed - len(extraction.labelled)
    assert extraction.by_status().get("draft", 0) >= 1


def test_scripted_answers_score_one() -> None:
    extraction = load_extraction_set(GOLDEN)
    extractor = LlmRuleExtractor(scripted(extraction.labelled), PROMPT, load())
    scores = [score(case, extractor.run(case.document, CTX)) for case in extraction.labelled]
    result = aggregate(scores)
    assert result.extraction_acceptance == 1.0
    assert result.citation_validity == 1.0
    assert result.detector_accuracy == 1.0
    assert all(s.accepted for s in scores)


def test_fake_gateway_answers_parse_but_do_not_match() -> None:
    extraction = load_extraction_set(GOLDEN)
    with fake_gateway() as provider:
        extractor = LlmRuleExtractor(provider, PROMPT, load())
        outcomes = [extractor.run(case.document, CTX) for case in extraction.labelled]
    scores = [
        score(case, outcome) for case, outcome in zip(extraction.labelled, outcomes, strict=True)
    ]
    result = aggregate(scores)
    assert result.parse_rate == 1.0
    assert result.extraction_acceptance == 0.0
    assert all(o.needs_review for o in outcomes)


def test_gates_and_report() -> None:
    extraction = load_extraction_set(GOLDEN)
    aggregates = {
        name: run_extraction(extraction, name, gateway_url="http://unused.test")[0]
        for name in ("scripted", "fake")
    }
    relation_cases = load_relation_cases(GOLDEN)
    relations = {
        name: run_relations(relation_cases, name, gateway_url="http://unused.test")[0]
        for name in ("scripted", "fake")
    }
    suites: dict[str, dict[str, object]] = {
        "extraction": dict(aggregates),
        "relations": dict(relations),
    }
    gates = evaluate("ci", suites)
    assert {g.gate.suite for g in gates if not g.passed} == set(QA_SUITES)
    assert all(g.passed for g in gates if g.gate.suite in ("extraction", "relations"))
    without_relations = evaluate("ci", {"extraction": aggregates})
    assert {g.gate.suite for g in without_relations if not g.passed} == {"relations", *QA_SUITES}
    missing = evaluate("nightly", suites)
    assert all(g.value is None and not g.passed for g in missing)
    text = markdown(
        RunResults("ci", gates, extraction=extraction, aggregates=aggregates, relations=relations)
    )
    assert "| extraction_acceptance |" in text
    assert "| relation_recall |" in text
    assert "Relation golden set: 3 cases." in text
    assert "50 indexed" in text
    assert "| Gate | Suite | Provider | Minimum | Baseline | Value | Result |" in text
    assert {g.provider for g in GATES["ci"]} == {"scripted", "fake"}


def test_unknown_provider_is_refused() -> None:
    with (
        pytest.raises(ValueError, match="unknown provider"),
        provider_for("oracle", [], gateway_url=""),
    ):
        pass


def test_main_ci_profile_passes_and_writes_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--profile", "ci", "--golden", str(GOLDEN), "--reports", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "ci gates passed (22)" in out
    assert "KAG against the hybrid baseline, scripted:" in out
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()


def test_main_runs_the_suites_it_is_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--suite", "relations", "--golden", str(GOLDEN), "--reports", str(tmp_path)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "Relation golden set" in out
    assert "Extraction golden set" not in out
    assert "QA golden set" not in out
    assert "ci gates passed (4)" in out


def test_main_fails_when_a_gate_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--profile",
            "nightly",
            "--provider",
            "fake",
            "--suite",
            "extraction",
            "--golden",
            str(GOLDEN),
            "--reports",
            str(tmp_path),
        ]
    )
    assert code == 1
    assert "FAILED" in capsys.readouterr().out


def test_main_exits_2_when_the_gateway_refuses_under_its_residency_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run stops at the first refusal: asking again gets the same answer."""
    asked: list[httpx2.Request] = []

    def refuse(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        problem = {"type": RESIDENCY_PROBLEM, "detail": "CW_LLM_RESIDENCY=india_only"}
        return httpx2.Response(503, json=problem)

    @contextmanager
    def refusing(_: str) -> Iterator[GatewayProvider]:
        transport = httpx2.MockTransport(refuse)
        yield GatewayProvider(client=httpx2.Client(transport=transport, base_url="http://gw"))

    monkeypatch.setattr(providers, "http_gateway", refusing)
    args = ["--profile", "nightly", "--provider", "gateway", "--suite", "extraction"]
    assert main([*args, "--golden", str(GOLDEN), "--reports", str(tmp_path)]) == 2
    out = capsys.readouterr().out
    assert "eval: aborted: the llm-gateway refuses the call under its residency policy" in out
    assert len(asked) == 1


def test_main_needs_labelled_cases(tmp_path: Path) -> None:
    (tmp_path / "extraction").mkdir()
    assert main(["--golden", str(tmp_path), "--reports", str(tmp_path / "r")]) == 1


REGISTERED_PROMPTS = [
    entry
    for entry in tomllib.loads(REGISTRY.read_text())["prompts"]
    if entry.get("sha256") is not None
]
LABELLED_CASES = {
    "extraction.rule_candidate": lambda: len(load_extraction_set(GOLDEN).labelled),
    "extraction.rule_relations": lambda: len(load_relation_cases(GOLDEN)),
    "qa.plan": lambda: sum(c.scripted.plan is not None for c in load_qa_cases(GOLDEN)),
    "qa.answer": lambda: sum(c.scripted.answer is not None for c in load_qa_cases(GOLDEN)),
}


def prompt_file(name: str, version: str) -> Path:
    area = name.partition(".")[0]
    assert area in PROMPT_DIRS, f"no prompt directory for the {area!r} area"
    return PROMPT_DIRS[area] / f"{name}.v{version}.md"


@pytest.mark.parametrize("entry", REGISTERED_PROMPTS, ids=lambda e: f"{e['name']}@{e['version']}")
def test_registry_digest_matches_the_prompt_file(entry: dict[str, object]) -> None:
    name, version = str(entry["name"]), str(entry["version"])
    digest = hashlib.sha256(prompt_file(name, version).read_bytes()).hexdigest()
    assert entry["sha256"] == digest, "update sha256 in services/llm-gateway/prompts/registry.toml"
    eval_cases = entry["eval_cases"]
    assert isinstance(eval_cases, int)
    assert eval_cases >= 1
    assert LABELLED_CASES[name]() >= eval_cases, f"{name} needs {eval_cases} labelled case(s)"


def test_every_prompt_with_a_digest_is_checked() -> None:
    assert {str(e["name"]) for e in REGISTERED_PROMPTS} == set(LABELLED_CASES)


def test_the_qa_prompts_count_their_scripted_cases() -> None:
    counts = {str(e["name"]): e["eval_cases"] for e in REGISTERED_PROMPTS}
    assert counts["qa.plan"] == LABELLED_CASES["qa.plan"]()
    assert counts["qa.answer"] == LABELLED_CASES["qa.answer"]()


def test_an_unmapped_prompt_area_fails() -> None:
    with pytest.raises(AssertionError, match="no prompt directory"):
        prompt_file("billing.invoice", "1")
