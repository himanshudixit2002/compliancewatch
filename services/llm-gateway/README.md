# llm-gateway service

Part of the ComplianceWatch monorepo. The only service that talks to a language model provider.
Design reference: Project Foundation guide, sections 7, 8 and 14; decision record
[ADR-008](../../docs/adr/ADR-008-own-llm-gateway-no-langchain.md).

- **Owns:** provider routing per feature with a fallback model, the prompt registry, an exact-match
  response cache, the cost ledger in USD and INR, per-tenant and per-feature monthly budgets, PII
  masking, a circuit breaker per provider and model, and tracing to Langfuse
- **Owning team:** AI Platform
- **Consumes:** every LLM call from every service; the Vercel AI Gateway when a key is configured
- **Emits / publishes:** `llm.call.completed` and `llm.budget.alarmed` (log publisher for now),
  the `/v1/llm-gateway` API, and its OpenAPI spec in `packages/contracts/openapi/llm-gateway.v1.json`

## What a caller sends and gets back

A caller names a feature, a registered prompt (`name@version`) and the text. It never sees a
provider SDK, a model id it did not ask for, or an unmasked trace.

```bash
make run SERVICE=llm-gateway          # http://localhost:8008, fake provider, in-memory ledger

curl -s -X POST http://localhost:8008/v1/llm-gateway/completions \
  -H 'content-type: application/json' \
  -H 'x-tenant-id: 6b0c5a1e-3e0c-4a6f-9d2f-1c2b3a4d5e6f' \
  -d '{"feature":"smoke","prompt":"smoke.echo@1","user":"hello from curl"}'
```

```json
{
  "text": "fake:hello from curl",
  "model_requested": "fake/echo",
  "model_served": "fake/echo",
  "provider": "fake",
  "input_tokens": 4,
  "output_tokens": 5,
  "cached": false,
  "cost_usd": "0.000002",
  "cost_inr": "0.0002",
  "cost_source": "estimate",
  "latency_ms": 1,
  "trace_id": "8a5b...",
  "generation_id": "fake-2f1c...",
  "correlation_id": "c0ffee...",
  "pii_masked": { "gstin": 0, "pan": 0, "aadhaar": 0, "phone": 0, "email": 0 }
}
```

Send the same body again and `cached` is `true` with zero cost. The other routes:

```bash
# Spend this month for the tenant in the header (scope tenant), optionally narrowed to one feature
curl -s http://localhost:8008/v1/llm-gateway/usage -H 'x-tenant-id: 6b0c5a1e-3e0c-4a6f-9d2f-1c2b3a4d5e6f'
# Spend for one feature across all tenants (scope feature), for a given month
curl -s 'http://localhost:8008/v1/llm-gateway/usage?feature=extraction&month=2026-09'
# The routing table with overrides applied, and the registered prompts
curl -s http://localhost:8008/v1/llm-gateway/models
curl -s http://localhost:8008/v1/llm-gateway/prompts
# Liveness, readiness (checks: ledger, prompt_registry, provider), router ping
curl -s http://localhost:8008/health; curl -s http://localhost:8008/ready; curl -s http://localhost:8008/v1/llm-gateway/ping
```

### Routes

| Route | What it does |
| --- | --- |
| `POST /v1/llm-gateway/completions` | One completion through prompt check, PII masking, budget check, cache, breaker, provider (with fallback), ledger, trace and event. Synchronous. |
| `GET /v1/llm-gateway/usage` | Spend for one UTC month. `tenant_id` (query, defaults to the header) gives the tenant scope; `feature` alone gives the feature scope; neither is a 422. `month=YYYY-MM` defaults to the current month. |
| `GET /v1/llm-gateway/models` | The routing table: per feature the primary and fallback model, provider filters, sort, reasoning effort, timeout and whether the row is a default or an override. |
| `GET /v1/llm-gateway/prompts` | The prompt registry: name, version, owner, eval case count, sha256 and description. |
| `GET /health`, `GET /ready`, `GET /v1/llm-gateway/ping` | From py-common and the router. `/ready` runs the checks `ledger`, `prompt_registry` and `provider`. |

Request body of `POST /completions` (unknown fields are rejected):

| Field | Meaning |
| --- | --- |
| `feature` | `extraction`, `judgement`, `qa`, `classification` or `smoke`; picks the route and the budget bucket |
| `prompt` | Registered prompt reference `name@version`, for example `smoke.echo@1` |
| `system`, `user` | Prompt text; `user` is required. Both are masked before they leave the process |
| `model` | Optional model id override, `creator/model` of at most 120 characters (anything else is a 422 `request-invalid`); disables the fallback |
| `temperature` (0 to 2, default 0), `max_tokens` (1 to 32768, default 1024) | Only calls with temperature 0 are cached |
| `json_schema` | Strict structured output; the fake provider returns a typed placeholder object |
| `metadata` | String map copied onto the trace, for example a document id |

Headers: `x-tenant-id` (UUID) attributes the call to a tenant; absent means a regulatory call with
no tenant, which only the feature budget governs. A value that is not a UUID is a 422 problem.
`x-request-id` is reused as the correlation id when it is 1 to 64 characters of `A-Z a-z 0-9 . _ -`
and minted otherwise (the client value is then not echoed); it comes back in the response header
and body and in every log line.

The tenant header is a dev-stage limitation: the identity service and Keycloak will replace it
with a token, and the header will stop being trusted.

### Errors

Every error is `application/problem+json` (RFC 9457) with a stable `type` URI, the `status`, a
`detail`, the `instance` path and the `correlation_id`.

| `type` (`urn:compliancewatch:problem:` + slug) | Status | When |
| --- | --- | --- |
| `request-invalid` | 422 | Body or header validation failed; `errors[].loc` names the field |
| `llm-prompt-unregistered` | 422 | The `name@version` is not in the registry |
| `llm-feature-unknown` | 422 | Startup only: a `CW_LLM_ROUTES__*` override naming an unknown feature stops the process from wiring. The API answers an unknown `feature` with `request-invalid` |
| `llm-budget-exceeded` | 429 | Tenant or feature monthly budget spent, or the Vercel quota; `Retry-After` counts to the first of next month UTC |
| `llm-provider-response-invalid` | 502 | The provider answered with something the gateway cannot use (no choices, empty content, bad request rejected upstream) |
| `llm-provider-unavailable` | 503 | Every candidate model failed, the breaker is open, or the gateway has no credits; `Retry-After` when the provider gave one |
| `internal-error` | 500 | Anything else; the detail never carries internals |

## Settings

`GatewaySettings` extends `py_common.settings.Settings` (`CW_` prefix, `.env`, then defaults;
empty means unset). Everything below is read at process start.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CW_LLM_PROVIDER` | `fake` | `fake` serves every route from the deterministic provider; `vercel` uses the Vercel AI Gateway and requires the key |
| `CW_LLM_LEDGER` | `memory` | `memory` (per process) or `postgres` (table `llm_gateway.cost_ledger`, after `make migrate SERVICE=llm-gateway`) |
| `CW_AI_GATEWAY_API_KEY` | unset | Vercel AI Gateway key. Never committed; the process refuses to start with `vercel` and no key |
| `CW_AI_GATEWAY_BASE_URL` | `https://ai-gateway.vercel.sh/v1` | OpenAI-compatible endpoint |
| `CW_AI_GATEWAY_ZERO_DATA_RETENTION` | `true` | Asks the gateway for providers with zero data retention; needs a Vercel Pro plan, set `false` on Hobby |
| `CW_AI_GATEWAY_MAX_RETRIES` | `0` | SDK retries per attempt, off by default: the fallback model and the breaker are the retry policy, and an SDK retry would sleep for the server's `Retry-After` (up to 120 s) inside the request |
| `CW_LLM_USD_INR` | `88.00` | Conversion rate for the ledger |
| `CW_LLM_TENANT_MONTHLY_BUDGET_INR` | `1500` | Monthly ceiling per tenant |
| `CW_LLM_FEATURE_MONTHLY_BUDGET_INR` | `20000` | Monthly ceiling per feature across tenants |
| `CW_LLM_BUDGET_ALARM_RATIO` | `0.8` | Ratio at which `llm.budget.alarmed` fires once per scope and month |
| `CW_LLM_CACHE_TTL_SECONDS` | `3600` | Exact-match cache TTL; `0` disables the cache |
| `CW_LLM_CACHE_MAX_ENTRIES` | `1000` | Cache size; least recently used entries go first |
| `CW_LLM_BREAKER_THRESHOLD` | `3` | Consecutive failures that open the breaker for one provider and model |
| `CW_LLM_BREAKER_OPEN_SECONDS` | `60` | Time the breaker stays open before one probe call is let through |
| `CW_LLM_ALLOW_UNREGISTERED_PROMPTS` | `false` | Local experiments only; never in a shared environment |
| `CW_LLM_PROMPT_REGISTRY_PATH` | `services/llm-gateway/prompts/registry.toml` | The image sets `/app/prompts/registry.toml` |
| `CW_LLM_ROUTES__<FEATURE>` | unset | Route override, one variable per feature. Naming one model (`CW_LLM_ROUTES__QA=zai/glm-4.7-flash`) drops the fallback; name `primary,fallback` to keep failover. Provider filters and timeouts stay |
| `CW_LANGFUSE_HOST`, `CW_LANGFUSE_PUBLIC_KEY`, `CW_LANGFUSE_SECRET_KEY` | unset | All three set enables the Langfuse tracer |

## Routing

One route per feature, primary model then fallback, both reached through the Vercel AI Gateway
(`creator/model` ids; `fake/...` ids go to the fake provider). The fallback is tried when the
primary is unavailable or its breaker is open; an explicit `model` in the request disables it.

| Feature | Primary | Fallback | Provider filter (`only`) | Extras | Timeout |
| --- | --- | --- | --- | --- | --- |
| `extraction` | `deepseek/deepseek-v4-pro-0813` | `zai/glm-5.3` | deepinfra, parasail, digitalocean, morph, togetherai | `has structured-output`, reasoning effort `none` | 120 s |
| `judgement` | `alibaba/qwen3.7-flash` | `deepseek/deepseek-v4-flash-0731` | alibaba, runware, digitalocean | | 20 s |
| `qa` | `deepseek/deepseek-v4.1-flash` | `google/gemini-3.1-flash-lite` | togetherai, runware, deepinfra, parasail, fireworks, google, vertex | `sort ttft`, reasoning effort `none` | 8 s |
| `classification` | `alibaba/qwen3.7-flash` | `zai/glm-4.7-flash` | alibaba, bedrock, deepinfra | | 15 s |
| `smoke` | `fake/echo` | none | | | 5 s |

Why these: the calls are high volume and low margin, so the table prefers cheap, efficient
models, Chinese-origin ones where they are adequate, and pins a bigger model only where the
output is structured and judged by evals (extraction). Rule extraction needs strict JSON, so its
route asks the gateway for providers with structured output and a long timeout. Judgement and
classification are short and cheap. Question answering is latency bound, so the gateway sorts
providers by time to first token, and the fallback is a Gemini model as a safety net for Hindi.
The `only` lists leave out the native `deepseek` endpoint and the Alibaba-hosted DeepSeek because
both double their price during Indian working hours. No provider runs inference in India; text
leaves the country on every real call, which is why masking happens before the call and zero
data retention is requested.

Model quality and Hindi rankings are judgement, not measurement. Run a bake-off on gold
documents before the extraction and question-answering pipelines rely on these defaults, and
change a route with `CW_LLM_ROUTES__<FEATURE>` rather than code.

The Vercel provider sends `providerOptions.gateway` (`only`, `has`, `sort`, `zeroDataRetention`,
the route's other model as `models`), a strict `response_format` when a schema is given, and the
route's timeout per call. A request `model` outside the route gets `zeroDataRetention` only: the
filters, sort and reasoning effort were chosen for the route's own models. It reads the real cost,
the final provider and the generation id from the gateway's response metadata.

The SDK does not retry (`CW_AI_GATEWAY_MAX_RETRIES=0`): a retry would sleep for the server's
`Retry-After`, up to 120 s, inside the request, while the fallback model and the breaker already
decide what happens after a failure. The worst case for one call is therefore the route timeout
once per candidate: 240 s for `extraction`, 16 s for `qa`. `latency_ms` covers the whole call,
failed primary attempt included.

## Cost ledger and budgets

Every call, successful or not, is one ledger row: tenant, feature, prompt name and version, model
requested and served, provider, tokens, `cached`, `cost_usd`, `cost_inr`, `cost_source`, latency,
correlation, trace and generation ids, status and error type. Cost in USD is what the gateway
reports (`cost_source: gateway`); when it reports nothing, a pinned price table estimates it
(`estimate`); a cache hit costs nothing (`cache`). INR is USD times `CW_LLM_USD_INR`, kept to four
decimal places (USD to six). Money is decimal text in the API, never a float.

The ledger is in memory by default and in Postgres with `CW_LLM_LEDGER=postgres`
(`llm_gateway.cost_ledger`, migration `0001`, indexed by tenant and by feature over time). The
table has no row-level security on purpose: it is cross-tenant metering and `tenant_id` is null
for regulatory calls. The tenant RLS convention arrives with the first customer-data table.

Budgets are monthly, in INR, per UTC month. Before a call the gateway sums the month for the
tenant (when there is one) and for the feature. At the alarm ratio it logs a warning and emits
`llm.budget.alarmed` once per scope and month; at the limit it refuses with 429 and a
`Retry-After` to the first of next month. Queueing non-urgent work when a budget is exhausted is
the caller's job and is not built yet. `GET /usage` reports spend, limit, ratio and the reset time
for one scope.

## PII masking

Before any text reaches a provider, `system` and `user` are scrubbed for GSTINs, PANs, Aadhaar
numbers, ten-digit Indian phone numbers and email addresses, in that order (a GSTIN contains a
PAN). The count per kind comes back as `pii_masked` and goes onto the trace; the masked text is
what the cache key, the trace and the provider see. This is pattern matching, not a guarantee:
callers still keep personal data out of prompts where they can. Phone numbers are masked as ten digits with an optional `+91` or `0` prefix; the split form (`98765 43210`) is masked only behind that prefix, so two adjacent five-digit amounts in regulator text are left alone.

## Prompt registry

`prompts/registry.toml` lists every prompt the gateway accepts, one `[[prompts]]` table each
with `name` (dotted, lower case), `version`, `owner`, `eval_cases` (at least one), an optional
`sha256` of the prompt text and a `description`. A completion names a prompt as `name@version`
and an entry that is not there is a 422. Two entries exist today: `smoke.echo@1`, served by the
fake provider, and `extraction.rule_candidate@0`, a placeholder until the extraction pipeline
brings its prompt text. Prompt wording changes are reviewed by a Regulatory Analyst and merged
with a green eval run; the eval harness that enforces the registry is not built yet.

## Cache and breaker

The cache is exact match, in memory, per process: key over model, prompt, masked system and
user text, schema, temperature and `max_tokens`; only temperature 0 calls are cached, and only
when the model that answered is the one the key names, so a fallback's answer is never served as
the primary's. `CW_LLM_CACHE_TTL_SECONDS=0` turns the cache off. A Redis adapter comes later.

The breaker is keyed by provider and model; after `CW_LLM_BREAKER_THRESHOLD`
consecutive failures it stays open for `CW_LLM_BREAKER_OPEN_SECONDS`, then lets one probe through.
An open primary sends the call to the fallback; when every candidate's circuit is open, the 503
carries `Retry-After` with the seconds until the last candidate's probe.

## Tracing and events

Every call logs one `llm.call.completed` line with feature, prompt, models, provider, tokens,
cost, cache hit, masked counts, tenant and correlation id. With the three `CW_LANGFUSE_*`
variables set, the same call becomes a Langfuse trace named `llm.<feature>` (user = tenant,
session = correlation id, tags for feature, cost source, cached or live, status) with one
generation carrying the prompt reference, the model served, model parameters, masked input and
output, token usage and cost. The response's `trace_id` is the ledger row id and the Langfuse
trace id. Traces are flushed on shutdown.

Locally: `make dev-observability`, set `CW_LANGFUSE_HOST=http://localhost:3010` with the
`pk-lf-dev` / `sk-lf-dev` keys in `.env`, make a call, and open http://localhost:3010. The dev
stack runs Langfuse v2, so the service pins the v2 SDK; moving to v3 means ClickHouse, Redis,
MinIO and a worker in the stack.

The `llm.call.completed` and `llm.budget.alarmed` domain events go to a log publisher until the
Kafka outbox exists.

## Layout

```
src/llm_gateway/
  settings.py       # GatewaySettings (CW_LLM_*, CW_AI_GATEWAY_*, CW_LANGFUSE_*)
  wiring.py         # GatewayWiring: what main.py builds and the API reads from app.state
  main.py           # composition root: wire(settings) -> create_app(...) from py-common
  domain/           # features, errors, prompts, routing, pricing, budgets, breaker, cache key,
                    # scrub, ledger entry, tracing record, events, config; stdlib + domain-kernel only
  application/      # Complete (the call pipeline) and Usage (budget reports)
  infrastructure/   # providers/{fake,vercel}, ledger/{memory,sqlalchemy,models}, cache/memory,
                    # prompts/toml, tracing/{log,langfuse,composite}, events/log
  api/              # schemas, dependencies (tenant header, correlation id), router
prompts/registry.toml
migrations/         # alembic; 0001 creates cost_ledger
tests/
  unit/             # domain, application and adapters with stubs; API tests through TestClient
  contract/         # the served OpenAPI must equal packages/contracts/openapi/llm-gateway.v1.json
  integration/      # testcontainers Postgres: migration, round trip, monthly sums
```

## How to run

From the repo root:

```bash
make run SERVICE=llm-gateway                 # fake provider, memory ledger, port 8008
make dev && make migrate SERVICE=llm-gateway # then persist the ledger:
CW_LLM_LEDGER=postgres make run SERVICE=llm-gateway
make dev-llm                                 # the container: http://localhost:8090 (compose profile llm)
make openapi SERVICE=llm-gateway             # regenerate the committed spec after an API change
```

Real models: put a Vercel AI Gateway key in `.env` as `CW_AI_GATEWAY_API_KEY` and set
`CW_LLM_PROVIDER=vercel`. An explicit environment variable beats `.env`. The `fake-llm` container
is what other services and CI call when no real model is wanted; it never has a key.

## Tests

```bash
uv run pytest services/llm-gateway -q       # unit, API and contract tests, no Docker
make py-test-integration                    # testcontainers Postgres for the SQLAlchemy ledger
make check                                  # ruff, mypy --strict, import-linter, coverage gate
```

The domain and application layers are covered by the 80 percent gate. The provider tests use a
stub OpenAI client and real SDK response objects; the Langfuse tests use a stub client. CI builds
the image and smokes `/health`, `/ready` and one `smoke.echo@1` completion.

## Not built yet

- Real prompt texts for extraction, judgement, question answering and classification, and the
  bake-off that would justify the default routes
- Redis cache and semantic cache; the cache is exact match in memory per process
- Kafka outbox for `llm.call.completed`; events are logged only
- Tenant from a token: `x-tenant-id` is trusted until the identity service exists
- Queueing non-urgent work when a budget is exhausted; callers get a 429 today
- `Idempotency-Key`, streaming responses, a second real provider adapter
- Eval harness that refuses an unregistered prompt; the gateway does, the harness does not exist
- Langfuse v3 server and SDK; a cost dashboard over the ledger; Helm values for the settings above
