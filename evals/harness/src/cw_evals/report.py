"""The run as a Markdown page and a JSON file; the Markdown also goes to the GitHub step summary."""

import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from cw_evals.cases import ExtractionSet
from cw_evals.metrics import Aggregate, CaseScore
from cw_evals.qa.cases import CATEGORIES, QaCase
from cw_evals.qa.suite import QaRun
from cw_evals.relations import RelationAggregate, RelationScore
from cw_evals.thresholds import GateResult

METRICS = (
    "extraction_acceptance",
    "field_accuracy",
    "references_f1",
    "predicates_f1",
    "citation_validity",
    "validator_pass_rate",
    "detector_accuracy",
    "parse_rate",
)
RELATION_METRICS = (
    "relation_recall",
    "relation_precision",
    "evidence_validity",
    "relation_parse_rate",
)
QA_METRICS = (
    "plan_validity",
    "plan_first_try_validity",
    "solver_success",
    "citation_correctness",
    "grounded_answer_rate",
    "refusal_accuracy",
    "false_refusal_rate",
    "answer_safety",
    "response_rate",
)
QA_SUITES = ("qa_kag", "qa_hybrid")
LISTED_CASES = 10
"""Failing qa cases listed per run; the fake provider fails most answerable ones by design."""


@dataclass(frozen=True, slots=True)
class RunResults:
    """Everything one run produced, by suite and provider."""

    profile: str
    gates: Sequence[GateResult]
    extraction: ExtractionSet | None = None
    aggregates: Mapping[str, Aggregate] = field(default_factory=dict)
    scores: Mapping[str, Sequence[CaseScore]] = field(default_factory=dict)
    relations: Mapping[str, RelationAggregate] = field(default_factory=dict)
    relation_scores: Mapping[str, Sequence[RelationScore]] = field(default_factory=dict)
    qa: Mapping[str, Mapping[str, QaRun]] = field(default_factory=dict)
    """Suite (``qa_kag``, ``qa_hybrid``) to provider to run."""
    qa_cases: Sequence[QaCase] = ()


def markdown(results: RunResults) -> str:
    lines = [f"# Eval run ({results.profile})"]
    if results.extraction is not None:
        lines += _extraction(results.extraction, results.aggregates)
    if results.relations:
        lines += _relations(results.relations)
    if results.qa:
        lines += _qa(results)
    lines += _gates(results.gates)
    for name, relation_case_scores in results.relation_scores.items():
        missed = [s for s in relation_case_scores if s.missed]
        if missed:
            lines += ["", f"Relations missed with {name}:", ""]
            lines += [f"- {s.case_id} ({s.label_status}): {', '.join(s.missed)}" for s in missed]
    for name, case_scores in results.scores.items():
        failing = [s for s in case_scores if not s.accepted]
        if failing:
            lines += ["", f"Cases not accepted with {name}:", ""]
            for s in failing:
                wrong = [k for k, ok in s.field_matches.items() if not ok]
                issues = list(s.validator_issues) or "-"
                lines.append(
                    f"- {s.case_id} ({s.label_status}): parsed={s.parsed}, "
                    f"wrong fields={wrong or '-'}, issues={issues}"
                )
    for suite in QA_SUITES:
        for name, run in results.qa.get(suite, {}).items():
            failing_qa = [q for q in run.scores if not q.passed]
            if failing_qa:
                lines += ["", f"QA cases not passed in {suite} with {name}:", ""]
                for q in failing_qa[:LISTED_CASES]:
                    lines.append(
                        f"- {q.case_id} ({q.category}, {q.label_status}): outcome={q.outcome}, "
                        f"layer={q.layer}, reason={q.reason}, "
                        f"problems={'; '.join(q.problems) or '-'}"
                    )
                if len(failing_qa) > LISTED_CASES:
                    more = len(failing_qa) - LISTED_CASES
                    lines.append(f"- and {more} more (every case is in latest.json)")
    return "\n".join(lines) + "\n"


def _extraction(extraction: ExtractionSet, aggregates: Mapping[str, Aggregate]) -> list[str]:
    status = dict(sorted(extraction.by_status().items()))
    lines = [
        "",
        f"Extraction golden set: {extraction.indexed} indexed, {len(extraction.labelled)} labelled "
        f"({', '.join(f'{k} {v}' for k, v in status.items()) or 'none'}), "
        f"{extraction.unlabelled} unlabelled.",
        "",
        "| Metric | " + " | ".join(aggregates) + " |",
        "| --- | " + " | ".join("---" for _ in aggregates) + " |",
    ]
    for metric in METRICS:
        cells = [f"{getattr(aggregates[name], metric):.3f}" for name in aggregates]
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    return lines


def _relations(relations: Mapping[str, RelationAggregate]) -> list[str]:
    cases = next(iter(relations.values())).cases
    lines = [
        "",
        f"Relation golden set: {cases} cases.",
        "",
        "| Relation metric | " + " | ".join(relations) + " |",
        "| --- | " + " | ".join("---" for _ in relations) + " |",
    ]
    for metric in RELATION_METRICS:
        cells = [f"{getattr(relations[name], metric):.3f}" for name in relations]
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    return lines


def _qa(results: RunResults) -> list[str]:
    cases = results.qa_cases
    categories = Counter(case.category for case in cases)
    statuses = Counter(case.label_status for case in cases)
    columns = [(suite, name) for suite in QA_SUITES for name in results.qa.get(suite, {})]
    lines = [
        "",
        f"QA golden set (KAG): {len(cases)} cases "
        f"({', '.join(f'{c} {categories.get(c, 0)}' for c in CATEGORIES)}); "
        f"{statuses.get('reviewed', 0) + statuses.get('approved', 0)} reviewed, "
        f"{statuses.get('draft', 0)} draft. The scripted answers are the labels.",
        "",
        "| QA metric | " + " | ".join(f"{suite} {name}" for suite, name in columns) + " |",
        "| --- | " + " | ".join("---" for _ in columns) + " |",
    ]
    runs = [results.qa[suite][name] for suite, name in columns]
    for metric in QA_METRICS:
        cells = [_number(getattr(run.aggregate, metric)) for run in runs]
        lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    lines.append("| tokens in / out | " + " | ".join(_tokens(run) for run in runs) + " |")
    lines.append(
        "| p95 latency ms | "
        + " | ".join(f"{run.aggregate.p95_latency_ms:.0f}" for run in runs)
        + " |"
    )
    lines.append(
        "| layer shares | " + " | ".join(_shares(run.aggregate.layer_shares) for run in runs) + " |"
    )
    for name in sorted({name for suite in QA_SUITES for name in results.qa.get(suite, {})}):
        kag = results.qa.get("qa_kag", {}).get(name)
        hybrid = results.qa.get("qa_hybrid", {}).get(name)
        if kag is None or hybrid is None:
            continue
        lines += [
            "",
            f"KAG against the hybrid baseline, {name}:",
            "",
            "| Metric | KAG | Hybrid | Delta |",
            "| --- | --- | --- | --- |",
        ]
        for metric in QA_METRICS:
            left, right = getattr(kag.aggregate, metric), getattr(hybrid.aggregate, metric)
            delta = "n/a" if left is None or right is None else f"{left - right:+.3f}"
            lines.append(f"| {metric} | {_number(left)} | {_number(right)} | {delta} |")
        groups = (
            ("category", kag.aggregate.grounded_by_category, hybrid.aggregate.grounded_by_category),
            (
                "fact source",
                kag.aggregate.grounded_by_fact_source,
                hybrid.aggregate.grounded_by_fact_source,
            ),
        )
        for label, by_kag, by_hybrid in groups:
            for key in sorted(set(by_kag) | set(by_hybrid)):
                lines.append(
                    f"| grounded, {label} {key} | {_number(by_kag.get(key))} "
                    f"| {_number(by_hybrid.get(key))} | |"
                )
    return lines


def _gates(gates: Sequence[GateResult]) -> list[str]:
    lines = [
        "",
        "| Gate | Suite | Provider | Minimum | Baseline | Value | Result |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in gates:
        gate = result.gate
        baseline = "-"
        if gate.baseline is not None:
            baseline = f"{gate.baseline} {_number(result.baseline_value)}"
            if gate.tolerance:
                baseline += f" - {gate.tolerance:.2f}"
        lines.append(
            f"| {gate.metric} | {gate.suite} | {gate.provider} | {gate.minimum:.2f} "
            f"| {baseline} | {_number(result.value)} | {'pass' if result.passed else 'FAIL'} |"
        )
    return lines


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _tokens(run: QaRun) -> str:
    return f"{run.aggregate.input_tokens} / {run.aggregate.output_tokens}"


def _shares(shares: Mapping[str, float]) -> str:
    return ", ".join(f"{layer} {share:.2f}" for layer, share in shares.items()) or "-"


def write(out_dir: Path, results: RunResults, text: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    profile = results.profile
    (out_dir / f"{profile}-{stamp}.md").write_text(text, encoding="utf-8")
    (out_dir / "latest.md").write_text(text, encoding="utf-8")
    payload = {
        "profile": profile,
        "ran_at": stamp,
        "aggregates": {name: asdict(a) for name, a in results.aggregates.items()},
        "scores": {name: [asdict(s) for s in items] for name, items in results.scores.items()},
        "relations": {name: asdict(a) for name, a in results.relations.items()},
        "relation_scores": {
            name: [asdict(s) for s in items] for name, items in results.relation_scores.items()
        },
        "qa": {
            suite: {name: asdict(run.aggregate) for name, run in runs.items()}
            for suite, runs in results.qa.items()
        },
        "qa_scores": {
            suite: {name: [asdict(s) for s in run.scores] for name, run in runs.items()}
            for suite, runs in results.qa.items()
        },
        "gates": [
            {
                "suite": g.gate.suite,
                "metric": g.gate.metric,
                "provider": g.gate.provider,
                "minimum": g.gate.minimum,
                "baseline": g.gate.baseline,
                "tolerance": g.gate.tolerance,
                "value": g.value,
                "baseline_value": g.baseline_value,
                "passed": g.passed,
            }
            for g in results.gates
        ],
    }
    path = out_dir / "latest.json"
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    return path
