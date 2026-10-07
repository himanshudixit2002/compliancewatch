"""``eval-harness``: run the golden sets, print the scores, exit 1 when a gate fails.

``--profile ci`` (the default) runs the scripted answers and the in-process fake gateway;
``--profile nightly`` runs against ``--gateway-url`` (a gateway configured with a real
provider). ``--provider`` narrows the run to one provider for a quick look, ``--suite`` to some
of the suites (extraction, relations, qa; all by default). The qa suite runs each provider twice,
with the KAG layer on (``qa_kag``) and off (``qa_hybrid``). Reports land in ``evals/reports``
(git-ignored) and in the GitHub step summary when there is one. A model call the scripted labels
do not cover stops the run with exit 2, and so does a gateway that refuses a call under its
residency policy (``ModelResidencyRefusedError``): asking it again, or scoring what it refused,
says nothing about the prompts.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cw_evals.cases import DEFAULT_GOLDEN, ExtractionSet, load_extraction_set
from cw_evals.metrics import Aggregate, CaseScore, aggregate, score
from cw_evals.providers import PROVIDERS, provider_for
from cw_evals.qa.cases import QaCase
from cw_evals.qa.providers import UnscriptedCallError
from cw_evals.qa.suite import MODES, QaRun, load_qa_suite, run_qa
from cw_evals.relations import (
    RelationAggregate,
    RelationScore,
    load_relation_cases,
    run_relations,
)
from cw_evals.report import RunResults, markdown, write
from cw_evals.thresholds import GATES, PROFILES, evaluate
from domain_kernel.documents import ExtractionContext
from ontology import VERSION as ONTOLOGY_VERSION
from ontology import load as load_ontology
from pipeline.application.extractor import LlmRuleExtractor
from pipeline.domain.errors import ModelResidencyRefusedError
from pipeline.infrastructure.prompts import load_prompt

PROMPT = ("extraction.rule_candidate", "1")
SUITES = ("extraction", "relations", "qa")
GATED_SUITES = {"extraction": ("extraction",), "relations": ("relations",), "qa": tuple(MODES)}
"""The suite names a gate can read, per ``--suite`` choice."""
ABORTED = 2


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
    parser.add_argument("--suite", choices=SUITES, action="append", default=None)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--reports", type=Path, default=Path("evals/reports"))
    parser.add_argument("--gateway-url", default="http://localhost:8008")
    args = parser.parse_args(argv)
    providers = args.provider or sorted({gate.provider for gate in GATES[args.profile]})
    suites = args.suite or list(SUITES)
    try:
        results = _run(args.profile, suites, providers, args.golden, args.gateway_url)
    except (UnscriptedCallError, ModelResidencyRefusedError) as exc:
        sys.stdout.write(f"eval: aborted: {exc}\n")
        return ABORTED
    if results is None:
        sys.stdout.write("eval: no labelled extraction cases; nothing to score\n")
        return 1
    text = markdown(results)
    path = write(args.reports, results, text)
    sys.stdout.write(text)
    failed = [g for g in results.gates if not g.passed]
    sys.stdout.write(f"report: {path}\n")
    if failed:
        names = ", ".join(f"{g.gate.suite}.{g.gate.metric}[{g.gate.provider}]" for g in failed)
        sys.stdout.write(f"eval: FAILED {len(failed)} gate(s): {names}\n")
        return 1
    sys.stdout.write(f"eval: {args.profile} gates passed ({len(results.gates)})\n")
    return 0


def _run(
    profile: str, suites: Sequence[str], providers: Sequence[str], golden: Path, gateway_url: str
) -> RunResults | None:
    extraction = None
    aggregates: dict[str, Aggregate] = {}
    scores: dict[str, list[CaseScore]] = {}
    if "extraction" in suites:
        extraction = load_extraction_set(golden)
        if not extraction.labelled:
            return None
        for name in providers:
            aggregates[name], scores[name] = run_extraction(
                extraction, name, gateway_url=gateway_url
            )
    relation_aggregates: dict[str, RelationAggregate] = {}
    relation_scores: dict[str, list[RelationScore]] = {}
    relation_cases = load_relation_cases(golden) if "relations" in suites else []
    if relation_cases:
        for name in providers:
            relation_aggregates[name], relation_scores[name] = run_relations(
                relation_cases, name, gateway_url=gateway_url
            )
    qa: dict[str, dict[str, QaRun]] = {}
    qa_cases: list[QaCase] = []
    if "qa" in suites:
        spec, qa_cases = load_qa_suite(golden)
        for name in providers:
            for suite, run in run_qa(spec, qa_cases, name, gateway_url=gateway_url).items():
                qa.setdefault(suite, {})[name] = run
    measured: dict[str, dict[str, object]] = {
        "extraction": dict(aggregates),
        "relations": dict(relation_aggregates),
    }
    for suite, runs in qa.items():
        measured[suite] = {name: run.aggregate for name, run in runs.items()}
    gated = {suite for choice in suites for suite in GATED_SUITES[choice]}
    gates = [g for g in evaluate(profile, measured) if g.gate.suite in gated]
    return RunResults(
        profile=profile,
        gates=gates,
        extraction=extraction,
        aggregates=aggregates,
        scores=scores,
        relations=relation_aggregates,
        relation_scores=relation_scores,
        qa=qa,
        qa_cases=qa_cases,
    )


if __name__ == "__main__":
    raise SystemExit(main())
