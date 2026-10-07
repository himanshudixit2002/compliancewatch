# ADR-020: Model calls and data residency

- **Status:** Proposed
- **Date:** 2026-10-07
- **Deciders:** the maintainer as product owner, with counsel; AI Platform (owner of `services/llm-gateway`)

## Context

Every model call goes through `services/llm-gateway` (ADR-008), which reaches the models through
the Vercel AI Gateway with one key. Rule extraction, applicability judgement, question answering
and document classification call a completion model; retrieval calls an embedding model
(ADR-013). As the gateway's routing section records, no routed model runs inference in India: the
AI Gateway sends each call to a host in the route's provider list, and the gateway names no region
for it to keep to. Every real model call therefore sends text out of the country.

What leaves:

- Regulator documents (public text) for extraction, classification and embedding, and for
  question answering the user's question with the evidence the retrieval found.
- The gateway masks GSTINs, PANs, Aadhaar numbers, phone numbers and email addresses before the
  call (`domain_kernel.pii`), and asks the AI Gateway for providers with zero data retention
  (`CW_AI_GATEWAY_ZERO_DATA_RETENTION`, which needs a paid plan). Masking is pattern matching:
  a name, an address or a detail written in a question's free text still leaves.
- The traces of those calls go to Langfuse with the same masked text, wherever
  `CW_LANGFUSE_HOST` points, and log lines go wherever the log collector sends them; both are
  masked the same way.

Everything else the product stores is planned for the Mumbai region (the data map; ADR-013 and
ADR-014 apply the residency assumption of the guide's privacy section, section 16, to every
managed provider). The Digital Personal Data Protection Act, 2023 has its own provision on
processing personal data outside India. What it, the rules made under it and the customers'
contracts require of these calls is a question for counsel, and the guide's decision log
(section 21) leaves residency open. The engineering side is built so that either answer is a
setting, not a code change.

## Options

### Option A: masked calls to models outside India, with zero data retention

Keep `CW_LLM_RESIDENCY=global` (the default). Text leaves India masked, to providers asked to
retain none of it, under the AI Gateway's terms.

- Needs: the paid plan with zero data retention on in every environment; a data processing
  agreement with Vercel covering the providers it routes to; the privacy notice and the data map
  saying that model providers outside India process the masked text; counsel's view that the Act
  and the customers' contracts allow it.
- Gains: the product works as built, with the cheap models the routing table chose, and no new
  provider to run.
- Risks: what masking misses leaves the country. Zero retention is the providers' promise, which
  we cannot verify. A restriction on transfers to a country could force a change at short notice.

### Option B: providers that run inference in India only

Set `CW_LLM_RESIDENCY=india_only`. The gateway refuses every call to a real model with 503
`llm-residency-unavailable` before it is made, so no text leaves for a model call; `fake/...`
models, served in process, still answer.

- Needs: a provider that runs suitable models in India (for example a cloud's Mumbai region,
  where its models and terms allow, or open-weight models served on GPUs in India), wired behind
  the gateway as a second provider adapter that the guard lets through; the routing table, the
  eval gates and the budgets redone for its models and prices.
- Gains: no personal data leaves India for a model call, whatever masking misses; the simplest
  statement in the privacy notice.
- Risks: until that provider exists, every model feature stops: extraction finds no rule
  candidates, judgement and question answering answer 503, retrieval embeds nothing. The models
  on offer in the region may cost more and do worse at Hindi or strict JSON; the evals have to
  show they are good enough.

## Decision

Not taken yet. It is the maintainer's, with counsel. Until it is taken:

- Every environment runs `global`, which is option A as built; `make product` and the image keep
  it, and staging and production set it explicitly only once the decision is made.
- The privacy notice and the data map each carry a draft line on cross-border model processing,
  marked for counsel's review.
- Neither option changes the masking of prompts, log lines and audit rows, which stays on.

## What is built (2026-10-07)

- `CW_LLM_RESIDENCY` in the gateway's settings (`global` or `india_only`, default `global`), the
  policy's one source: read once at start, refused when set but empty (any other setting would
  read that as unset, here `global`), and refused alongside a `CW_FLAG_LLM_GATEWAY_RESIDENCY`
  override. The registry entry `llm_gateway.residency` (owner ai-platform) is its record and
  nothing reads the flag, so a flag provider cannot hold another policy than the one that runs;
  a policy taken with counsel is changed by configuration, not from Unleash.
- Under `india_only` the composition root wraps every registered provider that is not an
  adapter in India (`IN_INDIA` in `infrastructure/providers/residency.py`: the fake provider
  alone) in `ResidencyBlockedProvider`, whatever it is, so a provider added later or one the
  guard does not know is refused too. It refuses completions and embeddings with
  `ResidencyUnavailableError` (503 `llm-residency-unavailable`, no `Retry-After`) without calling
  the provider. The ledger books each refusal at no cost and the tracer records it; no fallback
  model is tried and the breaker does not count it.
- Under `india_only` the Langfuse tracer sends no prompt, answer or error text, only each call's
  metadata (names, ids, model, tokens, cost, masked counts, an error's problem type).
- `GET /v1/llm-gateway/models` reports the policy on every route as
  `residency: {policy, real_models_allowed}`; the `gateway_wired` line at start logs it.
- `cw-mvp check-config` accepts either policy, and still refuses `CW_LLM_PROVIDER=fake` in staging
  and production under `india_only`.

## Consequences

- Choosing option A: the setting is deleted with its flag and the gateway stays as it is; the
  draft lines in the privacy notice and the data map become final text with counsel.
- Choosing option B: `india_only` becomes fixed configuration, every model feature waits for the
  in-region provider, and that provider's adapter joins `IN_INDIA`, the only way past the guard.
  Langfuse already gets no prompt or answer text under `india_only`, only each call's metadata,
  so a trace host outside India holds no text of a call; the log collector has to be in India
  too, or carry no text it should not.
- Either way the decision is recorded here and this ADR becomes Accepted.
- Revisit when a provider offers suitable models in India, when counsel's view or the rules under
  the Act change, or when a customer's contract asks for data to stay in India.
