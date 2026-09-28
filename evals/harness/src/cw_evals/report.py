"""The run as a Markdown page and a JSON file; the Markdown also goes to the GitHub step summary."""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from cw_evals.cases import ExtractionSet
from cw_evals.metrics import Aggregate, CaseScore
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


def markdown(
    profile: str,
    extraction: ExtractionSet,
    aggregates: Mapping[str, Aggregate],
    scores: Mapping[str, Sequence[CaseScore]],
    gates: Sequence[GateResult],
    relations: Mapping[str, RelationAggregate] | None = None,
    relation_scores: Mapping[str, Sequence[RelationScore]] | None = None,
) -> str:
    status = dict(sorted(extraction.by_status().items()))
    lines = [
        f"# Eval run ({profile})",
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
    if relations:
        cases = next(iter(relations.values())).cases
        lines += [
            "",
            f"Relation golden set: {cases} cases.",
            "",
            "| Relation metric | " + " | ".join(relations) + " |",
            "| --- | " + " | ".join("---" for _ in relations) + " |",
        ]
        for metric in RELATION_METRICS:
            cells = [f"{getattr(relations[name], metric):.3f}" for name in relations]
            lines.append(f"| {metric} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "| Gate | Suite | Provider | Minimum | Value | Result |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in gates:
        value = "n/a" if result.value is None else f"{result.value:.3f}"
        verdict = "pass" if result.passed else "FAIL"
        lines.append(
            f"| {result.gate.metric} | {result.gate.suite} | {result.gate.provider} "
            f"| {result.gate.minimum:.2f} | {value} | {verdict} |"
        )
    for name, relation_case_scores in (relation_scores or {}).items():
        missed = [s for s in relation_case_scores if s.missed]
        if missed:
            lines += ["", f"Relations missed with {name}:", ""]
            lines += [f"- {s.case_id} ({s.label_status}): {', '.join(s.missed)}" for s in missed]
    for name, case_scores in scores.items():
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
    return "\n".join(lines) + "\n"


def write(
    out_dir: Path,
    profile: str,
    text: str,
    aggregates: Mapping[str, Aggregate],
    scores: Mapping[str, Sequence[CaseScore]],
    gates: Sequence[GateResult],
    relations: Mapping[str, RelationAggregate] | None = None,
    relation_scores: Mapping[str, Sequence[RelationScore]] | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"{profile}-{stamp}.md").write_text(text, encoding="utf-8")
    (out_dir / "latest.md").write_text(text, encoding="utf-8")
    payload = {
        "profile": profile,
        "ran_at": stamp,
        "aggregates": {name: asdict(a) for name, a in aggregates.items()},
        "scores": {name: [asdict(s) for s in items] for name, items in scores.items()},
        "relations": {name: asdict(a) for name, a in (relations or {}).items()},
        "relation_scores": {
            name: [asdict(s) for s in items] for name, items in (relation_scores or {}).items()
        },
        "gates": [
            {
                "suite": g.gate.suite,
                "metric": g.gate.metric,
                "provider": g.gate.provider,
                "minimum": g.gate.minimum,
                "value": g.value,
                "passed": g.passed,
            }
            for g in gates
        ],
    }
    path = out_dir / "latest.json"
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    return path
