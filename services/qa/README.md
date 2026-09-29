# qa service

Part of the ComplianceWatch monorepo. **Grounded answers to GST questions: an answer cites
regulator clauses published by the question's date, each quote checked against its clause, or
the answer is "not covered".**
Design reference: Project Foundation guide, sections 7, 8 and 14; ADR-012 (layered retrieval) and
ADR-017 (KAG-style reasoning).

- **Owns:** Answering questions in layers: structured answers from obligations, a KAG plan and solve over the rulebook, hybrid clause search; the citation post-check
- **Owning team:** AI Platform (guide section 14); `prompts/` is owned by AI Platform
- **Consumes:** Chat UI; WhatsApp replies; rulebook read API; profile snapshots; obligation reads; LLM gateway API
- **Emits / publishes:** qa API; one trace per question

## Layers

A question passes through the layers in order and stops at the first that decides (ADR-012).
Every layer that ran is in the response as `{layer, result, reason}`.

1. **Structured** (`application/structured.py`). No model call. With a `business_node_id`, it
   answers two phrasings from the business's own obligations: "when is my `<form>` due" (the
   earliest open obligation of that form due within a year) and "what is due this month" or
   "next month". Only obligations of rule versions in force on the date count, and the answer
   cites the rule version's verified citations, each checked again against its clause. Anything
   else passes the question on; this layer never answers "not covered".
2. **KAG** (`application/kag.py`, behind the flag). The planner (`qa.plan@1`) turns the question
   into a plan of at most 8 typed steps; the solver runs it with repository calls only; the
   answerer (`qa.answer@1`) phrases the answer from the evidence the solver collected. A plan
   that fails validation twice, a deferral (`steps: []`), a failed step, a budget overrun or no
   clause to cite falls back to hybrid with the reason. Once the answerer has run, its outcome
   is final.
3. **Hybrid** (`application/retrieval.py`). The question is embedded through the gateway and the
   rulebook's `/search` fuses full text and vectors by reciprocal rank, `k=8`. If embedding
   fails, the search runs on full text alone. No hit is "not covered" (`no_evidence`). The
   search keeps documents published on or before the question's date; a hit is not yet
   followed to the rule version in force (ADR-012, Evaluation).

Not built: the fourth, agentic layer of ADR-012 (reciprocal rank fusion gives no meaningful low
score to trigger it), the cross-encoder rerank (hybrid keeps the fused order), and a router that
sends single-hop questions past the planner. While the flag is on for a tenant, every question
that gets past the structured layer costs one planner call.

Result codes: `answered`, `not_covered`, `passed` (the layer did not apply), `fallback` (it tried
and handed on). Reasons, closed: `plan_invalid`, `planner_unavailable`, `planner_deferred`,
`step_budget_exceeded`, `step_failed`, `no_evidence`, `answerer_declined`,
`citation_check_failed`.

## The plan and the solver

Operators (`domain/plan.py`): `find_entity`, `rules_in_force`, `follow` (depth 1 to 3, `out` or
`in`), `evaluate_applicability`, `get_obligations`, `aggregate`, `compare`, `retrieve_clauses`,
`answer`. The planner's JSON schema is built per call (`domain/plan_schema.py`) with every choice
closed, including the rule keys and regulators in force on the date; `parse_plan` checks the
rest (ids in order, references to earlier steps, input kinds, one `answer` last, business steps
only with a business, a date no later than the question's) and lists every problem for the one
retry.

The solver (`application/solver.py`) is deterministic:

- It sees exactly the rule versions `GET /v1/rulebook/rule-versions?as_of` returns. A version
  reached any other way (the far end of a relation, an obligation's version) is dropped, and the
  drop is counted on the step's span.
- `follow` is breadth first with a visited set, so a cycle of relations ends.
- A question may make 40 upstream calls in all and a step may produce 50 items.
- Applicability is the kernel's `Specification.evaluate` with the packaged ontology, standing in
  until the applicability engine has an API. A specification that does not parse or names an
  unknown attribute gives an `unsure` fact, never a crash.

The evidence bundle (`domain/evidence.py`) labels clauses `C1..C12` and facts `F1..F40`; labels,
not clause refs, because every notification has an `en.p1`. The answer may cite only labels,
and `check_citations` (`domain/answer.py`) holds each quote to its clause: a fuzzy match of at
least 0.85 and no number, form code or month the clause lacks. A covered answer cites at least
once; two failed checks are "not covered".

## The flag

`CW_QA_KAG_ENABLED` (default `false`) turns the KAG layer on; `CW_QA_KAG_TENANTS`, a comma list of
tenant UUIDs, targets it, and empty means every tenant. Owner ai-platform; the flag is removed
when ADR-017 is Accepted. Off, or for a tenant not listed, there is no planner call.

## API

`POST /v1/qa/ask` with `x-tenant-id` (required):

```json
{"question": "When is my GSTR-3B due?", "as_of": "2026-04-10",
 "business_node_id": "<profile node uuid>", "fy": "2026-27"}
```

`as_of` defaults to today in India and `fy` to the financial year of `as_of`. The response:

```json
{"outcome": "answered", "answer": "...",
 "citations": [{"clause_ref": "en.p3", "document_id": "<uuid>", "quote": "..."}],
 "layer": "kag",
 "layers": [{"layer": "structured", "result": "passed", "reason": null},
            {"layer": "kag", "result": "answered", "reason": null}],
 "plan": {"as_of": null, "steps": ["..."]}, "reason": null, "as_of": "2026-04-10"}
```

`plan` is the validated plan whenever there was one, even when hybrid answered. Problems: 401
`qa-tenant-required`, 404 `qa-business-not-found` (a `business_node_id` the tenant does not
have), 422 `qa-question-invalid` or `request-invalid`, 503 `qa-dependency-unavailable` (a
service the answer depends on failed, including the gateway while answering). The spec is
`packages/contracts/openapi/qa.v1.json`.

## Ports, prompts, traces and evals

- **Ports** (`domain/ports.py`): `RulebookReader` and `ClauseSearch` (`HttpRulebook`),
  `ProfileReader` (`HttpProfiles`), `ObligationReader` (`HttpObligations`), `Embedder`
  (`HttpEmbedder`, which checks for 512 dimensions), the kernel's `LLMProvider`
  (`GatewayProvider`, the tenant per request) and `Tracer` (`OtelTracer`). A transport error
  or a 5xx is `DependencyUnavailableError`; a 404 is nothing. `testing.py` has the memory fakes,
  a `ScriptedProvider` keyed by `(question_id, prompt ref)`, a `RecordingTracer` and
  `memory_ports()`; `build_app(settings, ports=..., ontology=...)` takes them.
- **Prompts**: `prompts/qa.plan.v1.md` and `prompts/qa.answer.v1.md`, read when the app starts
  (from `CW_QA_PROMPTS_DIR` in the image) and by the `prompts` readiness check. Both are in the
  gateway's registry with owner ai-platform, the digest of the file and, as `eval_cases`, the
  number of golden cases under `evals/golden/qa/kag` that script them; the harness's registry
  test fails when a file changes without a new version and digest.
- **Spans**: `qa.ask` (question id, tenant, deciding layer, outcome, reason), `qa.layer` (layer,
  result, reason), `qa.solve.step` (`qa.step.id`, `op`, `items`, `hidden`, `status`) and
  `qa.retrieve` (`k`, hits, `lexical_only`). Attributes carry ids, codes and counts, never
  question or regulator text.
- **Eval tags**: every model call carries metadata `question_id` (the request's `x-request-id`),
  `stage` (`plan` or `answer`), `attempt` (`1` or `2`) and `layer`, so the eval harness can
  script each call per case.

## How to run

From the repo root:

```bash
make dev                          # infrastructure (Docker Compose)
make run SERVICE=qa               # http://localhost:8007/health, /ready, /v1/qa/ask
make test                         # unit + contract tests with the coverage gate
make openapi SERVICE=qa           # regenerate packages/contracts/openapi/qa.v1.json
docker build -f services/qa/Dockerfile -t compliancewatch-qa .
```

The service reads the rulebook (`CW_RULEBOOK_URL`, 8003), profile (`CW_PROFILE_URL`, 8002),
obligation (`CW_OBLIGATION_URL`, 8005) and gateway (`CW_LLM_GATEWAY_URL`, 8008) services. Reads
time out after `CW_QA_HTTP_TIMEOUT_SECONDS` (5); completions after `CW_QA_LLM_TIMEOUT_SECONDS` and
the question's embedding after `CW_QA_EMBEDDING_TIMEOUT_SECONDS` (20 each), longer than the
gateway's own budget for the call (the qa route gives its primary and its fallback 8 s each, the
retrieval route 15 s), so a fallback model has time to answer. Package `qa`, dev port 8007,
Postgres schema `qa` (no tables yet). Details:
[docs/onboarding/local-dev.md](../../docs/onboarding/local-dev.md).
