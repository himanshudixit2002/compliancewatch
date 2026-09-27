# eval harness

Part of the ComplianceWatch monorepo. Workspace package `compliancewatch-evals` (import
`cw_evals`, script `eval-harness`), source under `src/cw_evals/`.
Design reference: Project Foundation guide, sections 8, 17 and 19.

- **Owns:** Runner, metrics and thresholds: extraction acceptance, field accuracy, reference and predicate F1, citation validity, validator pass rate, detector accuracy (context recall and precision, grounded-answer rate and applicability precision and recall arrive with the qa and applicability golden sets)
- **Owning team:** AI Platform (guide section 14)
- **Consumes:** evals/golden; services/pipeline/prompts; the llm-gateway (in process with the fake provider, or over HTTP for a real model)
- **Emits / publishes:** `evals/reports/latest.md` and `latest.json` (git-ignored), the GitHub step summary, and an exit code that blocks the merge

## How it runs

```bash
make eval                                  # profile ci: scripted answers + fake gateway, no tokens
make eval ARGS="--provider fake"           # one provider only
make eval EVAL_PROFILE=nightly ARGS="--gateway-url http://localhost:8008"   # a real model behind the gateway
```

Three providers: `scripted` answers every case with its own label and must score 1.0 (it proves
the scoring, the validators and the labels agree); `fake` runs the llm-gateway in process with
its deterministic provider (the plumbing, with placeholders that parse but never match);
`gateway` posts to a running gateway, which is how the nightly run reaches a real model. The
harness never holds a provider key.

| Profile | Gates | When |
| --- | --- | --- |
| `ci` | scripted: extraction_acceptance = 1, citation_validity = 1, validator_pass_rate = 1, detector_accuracy >= 0.9; fake: parse_rate = 1 | every change under `evals/`, the pipeline, the prompts (CI job `evals`) |
| `nightly` | gateway: extraction_acceptance >= 0.90, citation_validity >= 0.95, parse_rate >= 0.98 (guide section 8) | `.github/workflows/nightly.yml`, 02:30 IST, once the `CW_AI_GATEWAY_API_KEY` secret exists |

A case is accepted when every labelled field matches (document kind, change kind, effective
dates, references, predicates, amounts, obligation, recurrence) and the validators raise
nothing. Cases with `label_status: draft` count like the others and are named in the report so
nobody mistakes a draft for a reviewed truth.
