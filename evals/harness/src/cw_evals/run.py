"""``eval-harness``: run the golden sets, print the scores, exit 1 when a gate fails.

``--profile ci`` (the default) runs the scripted answers and the in-process fake gateway;
``--profile nightly`` runs against ``--gateway-url`` (a gateway configured with a real
provider). ``--provider`` narrows the run to one provider for a quick look. Reports land in
``evals/reports`` (git-ignored) and in the GitHub step summary when there is one.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cw_evals.cases import DEFAULT_GOLDEN, ExtractionSet, load_extraction_set
from cw_evals.metrics import Aggregate, CaseScore, aggregate, score
from cw_evals.providers import PROVIDERS, provider_for
from cw_evals.relations import (
    RelationAggregate,
    RelationScore,
    load_relation_cases,
    run_relations,
)
from cw_evals.report import markdown, write
from cw_evals.thresholds import GATES, PROFILES, GateResult, evaluate
from domain_kernel.documents import ExtractionContext
from ontology import VERSION as ONTOLOGY_VERSION
from ontology import load as load_ontology
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.infrastructure.prompts import load_prompt

PROMPT = ("extraction.rule_candidate", "1")


def run_extraction(
    extraction: ExtractionSet, provider_name: str, *, gateway_url: str
) -> tuple[Aggregate, list[CaseScore]]:
    prompt = load_prompt(*PROMPT)
    ontology = load_ontology()
    cases = extraction.labelled
    scores: list[CaseScore] = []
    with provider_for(provider_name, cases, gateway_url=gateway_url) as provider:
        extractor = LlmRuleExtractor(provider, prompt, ontology)
        for case in cases:
            ctx = ExtractionContext(
                regulator=str(case.source.get("source_key", "unknown")),
                prompt_version=prompt.ref,
                model=provider_name,
                ontology_version=ONTOLOGY_VERSION,
            )
            scores.append(score(case, extractor.run(case.document, ctx)))
    return aggregate(scores), scores


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval-harness", description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="ci")
    parser.add_argument("--provider", choices=PROVIDERS, action="append", default=None)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--reports", type=Path, default=Path("evals/reports"))
    parser.add_argument("--gateway-url", default="http://localhost:8008")
    args = parser.parse_args(argv)
    providers = args.provider or sorted({gate.provider for gate in GATES[args.profile]})
    extraction = load_extraction_set(args.golden)
    if not extraction.labelled:
        sys.stdout.write("eval: no labelled extraction cases; nothing to score\n")
        return 1
    aggregates: dict[str, Aggregate] = {}
    scores: dict[str, list[CaseScore]] = {}
    for name in providers:
        aggregates[name], scores[name] = run_extraction(
            extraction, name, gateway_url=args.gateway_url
        )
    relation_cases = load_relation_cases(args.golden)
    relation_aggregates: dict[str, RelationAggregate] = {}
    relation_scores: dict[str, list[RelationScore]] = {}
    if relation_cases:
        for name in providers:
            relation_aggregates[name], relation_scores[name] = run_relations(
                relation_cases, name, gateway_url=args.gateway_url
            )
    gates: list[GateResult] = evaluate(args.profile, aggregates, relation_aggregates)
    text = markdown(
        args.profile, extraction, aggregates, scores, gates, relation_aggregates, relation_scores
    )
    path = write(
        args.reports,
        args.profile,
        text,
        aggregates,
        scores,
        gates,
        relation_aggregates,
        relation_scores,
    )
    sys.stdout.write(text)
    failed = [g for g in gates if not g.passed]
    sys.stdout.write(f"report: {path}\n")
    if failed:
        names = ", ".join(f"{g.gate.suite}.{g.gate.metric}[{g.gate.provider}]" for g in failed)
        sys.stdout.write(f"eval: FAILED {len(failed)} gate(s): {names}\n")
        return 1
    sys.stdout.write(f"eval: {args.profile} gates passed ({len(gates)})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
