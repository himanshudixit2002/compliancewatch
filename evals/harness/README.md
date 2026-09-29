# eval harness

Part of the ComplianceWatch monorepo. Workspace package `compliancewatch-evals` (import
`cw_evals`, scripts `eval-harness` and `eval-golden-check`), source under `src/cw_evals/`.
Design reference: Project Foundation guide, sections 8, 17 and 19.

- **Owns:** Runner, metrics and thresholds: extraction acceptance, field accuracy, reference and predicate F1, citation validity, validator pass rate, detector accuracy; for the relation stage (`cw_evals.relations`), relation recall and precision against the label, evidence validity and parse rate; for question answering (`cw_evals.qa`), plan validity, solver success, citation correctness, grounded-answer rate, refusal accuracy, answer safety and response rate, with the KAG layer on and off (context recall and precision and applicability precision and recall arrive with their golden sets)
- **Owning team:** AI Platform (guide section 14)
- **Consumes:** evals/golden; services/pipeline/prompts and services/qa/prompts; the llm-gateway (in process with the fake or a scripted provider, or over HTTP for a real model); the rulebook, profile, obligation and qa services, in process, for the qa suite
- **Emits / publishes:** `evals/reports/latest.md` and `latest.json` (git-ignored), the GitHub step summary, and an exit code that blocks the merge

## How it runs

```bash
make eval                                  # profile ci: scripted answers + fake gateway, no tokens
make eval ARGS="--provider fake"           # one provider only
make eval ARGS="--suite qa"                # one suite only (extraction, relations, qa; repeatable)
make eval EVAL_PROFILE=nightly ARGS="--gateway-url http://localhost:8008"   # a real model behind the gateway
make eval-check                            # the QA golden set and its world are well formed
```

Three providers: `scripted` answers every case with its own label and must score 1.0 (it proves
the scoring, the validators and the labels agree); `fake` runs the llm-gateway in process with
its deterministic provider (the plumbing, with placeholders that parse but never match);
`gateway` posts to a running gateway, which is how the nightly run reaches a real model. The
harness never holds a provider key.

The qa suite (`cw_evals.qa`) builds its world from `evals/golden/qa/kag/world.yaml` once per
provider: the rulebook, profile, obligation and gateway apps in process, seeded through their
own APIs, and the qa service on HTTP clients bound to them. It asks every case twice, with the
KAG layer on (`qa_kag`) and off (`qa_hybrid`, the baseline), and the report compares the two.
The scripted provider is served through the gateway (`build_app(completion_provider=...)`), so
the registry check, masking and ledger run; it answers by the case in flight, declines when the
evidence in the prompt does not give a date the case expects, and a model call the case does not
script stops the run with exit 2. An exception while asking one case counts
against the response rate and the run goes on.

| Profile | Gates | When |
| --- | --- | --- |
| `ci` | scripted: extraction_acceptance = 1, citation_validity = 1, validator_pass_rate = 1, detector_accuracy >= 0.9, relation_recall = 1, relation_precision = 1, evidence_validity = 1; qa_kag plan_validity, solver_success, citation_correctness, refusal_accuracy, answer_safety and grounded_answer_rate = 1, and grounded_answer_rate >= qa_hybrid's; qa_hybrid refusal_accuracy = 1, answer_safety = 1. fake: parse_rate = 1, relation_parse_rate = 1; qa_kag and qa_hybrid response_rate = 1, answer_safety = 1 | every change under `evals/`, the pipeline, the rulebook, the qa, profile and obligation services, the gateway, the prompts (CI job `evals`, after `make label ARGS="check"` and `make eval-check`) |
| `nightly` | gateway: extraction_acceptance >= 0.90, citation_validity >= 0.95, parse_rate >= 0.98 (guide section 8); relation and qa numbers reported, not gated, until their cases are reviewed | `.github/workflows/nightly.yml`, 02:30 IST, once the `CW_AI_GATEWAY_API_KEY` secret exists |

The baseline gate (qa_kag's grounded_answer_rate at least qa_hybrid's) cannot fail on its own in
`ci`, where the KAG run's minimum is already 1; it only bites under a profile whose minimum is
below 1, as the nightly one will be once its qa cases are reviewed and gated.
`plan_first_try_validity` is reported, not gated: one case (`sh-15-2025-power`) scripts a first
plan that refers to a later step and a valid `plan_retry`, so every CI run takes the planner's
retry path and the scripted first-try share reads below 1.0.

A case is accepted when every labelled field matches (document kind, change kind, effective
dates, references, predicates, amounts, obligation, recurrence) and the validators raise
nothing. A qa case is grounded when it is answered, every citation holds in a clause published by
the question's date, an expected citation is among them, the expected facts are in the answer
and nothing it must not mention is; with the KAG layer on, a case whose scripted plan has steps
must also be decided by the KAG layer, and a valid plan with steps that finds no clause for an
answerable case counts as a solver failure. Cases with `label_status: draft` count like the others and
are named in the report so nobody mistakes a draft for a reviewed truth. The scripted qa answers
are the labels, so the CI qa numbers prove the harness and the service agree with them, not
that a model answers well.
