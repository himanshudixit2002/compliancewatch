# deploy (MVP profile)

Part of the ComplianceWatch monorepo.
Design reference: Project Foundation guide, section 17. The guide's target is EKS with Terraform,
Helm and Argo CD (`infra/terraform`, `infra/helm`, `infra/argocd`, still placeholders). The MVP
profile here runs the same images on managed platforms so a pilot can start without a cluster.
Nothing in this directory has been applied: every account is the maintainer's to open.

| Piece | Where | Config |
| --- | --- | --- |
| Web app (`apps/web`) | Vercel, region `bom1` | `apps/web/vercel.json`; project root `apps/web`, monorepo install from the repo root |
| Ten Python services | Fly.io, region `bom` (Mumbai), one app each | `infra/deploy/fly/<service>.toml`, image from the service's Dockerfile, `/ready` health check, `alembic upgrade head` as the release command where the service has migrations |
| WhatsApp bot | Fly.io, `bom` | `infra/deploy/fly/whatsapp-bot.toml`, `apps/whatsapp-bot/Dockerfile` |
| Postgres | Fly Postgres (or Neon) in Mumbai, one database, one schema per service, PITR on | `CW_DATABASE_URL` secret per service with `?options=-csearch_path%3D<schema>%2Cpublic` |
| Kafka | Redpanda Cloud (serverless) or Upstash Kafka, Mumbai | `CW_KAFKA_BOOTSTRAP` plus SASL secrets (relay and consumers only) |
| Temporal | Temporal Cloud namespace | `CW_TEMPORAL_ADDRESS`, `CW_TEMPORAL_NAMESPACE`, client certificate secrets (pipeline worker) |
| Redis | Upstash Redis, Mumbai | `CW_REDIS_URL` |
| Observability | Grafana Cloud (OTLP endpoint) | `CW_OTEL_ENDPOINT` and its auth header; the dev dashboard JSON imports as is |
| Model provider | Vercel AI Gateway | `CW_AI_GATEWAY_API_KEY` on the llm-gateway only |

## Manual steps (in order)

1. Accounts: Fly.io organisation, Vercel team, Postgres provider, Redpanda Cloud or Upstash,
   Temporal Cloud, Grafana Cloud, Vercel AI Gateway. Region Mumbai everywhere the provider offers it
   (data residency assumption of the guide).
2. `fly apps create` for each app named in the toml files; `fly secrets set` per app from the
   matrix below; `fly deploy --config infra/deploy/fly/<service>.toml .` from the repo root.
3. Vercel: import the repository, set the project root to `apps/web`, add the public API base URL
   as `NEXT_PUBLIC_API_URL` when the web app starts calling services.
4. DNS: `app.<domain>` to Vercel, `api.<domain>` to the gateway app (the identity service fronts the
   API until an API gateway exists), `hooks.<domain>` to the bot; point the Meta webhook at
   `https://hooks.<domain>/webhook`.
5. Wire the flags once the accounts exist: `CW_WHATSAPP_ENABLED`, `WHATSAPP_SEND_ENABLED`,
   `CW_BILLING_PROVIDER=razorpay`, `CW_PROFILE_GSTIN_LOOKUP`, `CW_LLM_PROVIDER=vercel`.

## Environment matrix

Values: `secret` (set with `fly secrets set`, never in the toml), `env` (in the toml), `-` (unused).

| Variable | identity | profile | rulebook | obligation | notification | llm-gateway | pipeline | applicability-engine, qa, eval | whatsapp-bot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `CW_DATABASE_URL` | secret | secret | secret | secret | secret (once it has tables) | secret (`CW_LLM_LEDGER=postgres`) | secret | secret | - |
| `CW_DB_SCHEMA` | env | env | env | env | env | env | env | env | - |
| `CW_KAFKA_BOOTSTRAP` + SASL | - | secret (relay) | secret (relay) | secret (relay) | secret | - | secret | secret | - |
| `CW_TEMPORAL_*` | - | - | - | - | - | - | secret | - | - |
| `CW_REDIS_URL` | - | - | - | - | secret (digests, later) | secret (cache, later) | - | - | - |
| `CW_OTEL_ENDPOINT` (+ header) | secret | secret | secret | secret | secret | secret | secret | secret | - |
| `CW_AI_GATEWAY_API_KEY`, `CW_LLM_PROVIDER` | - | - | - | - | - | secret / env | - | - | - |
| `CW_LANGFUSE_*` | - | - | - | - | - | secret | - | - | - |
| `CW_LLM_ROUTES__<FEATURE>` (for example `CW_LLM_ROUTES__RETRIEVAL`), `CW_LLM_EMBEDDING_DIMENSIONS_PARAM` | - | - | - | - | - | env (only to override the routing table; the second defaults to `true`) | - | - | - |
| `CW_WHATSAPP_ENABLED`, `CW_WHATSAPP_PHONE_NUMBER_ID`, `CW_WHATSAPP_ACCESS_TOKEN` | - | - | - | - | env / secret / secret | - | - | - | - |
| `CW_BILLING_PROVIDER`, `CW_RAZORPAY_*` | env / secret | - | - | - | - | - | - | - | - |
| `CW_IDENTITY_STORE`, `CW_PROFILE_STORE`, `CW_PROFILE_GSTIN_LOOKUP` | env | env | - | - | - | - | - | - | - |
| `CW_RULEBOOK_STORE` | - | - | env | - | - | - | - | - | - |
| `CW_RULEBOOK_WRITE_TOKEN` | - | - | secret | - | - | - | secret | - | - |
| `CW_RULEBOOK_REVIEW_TOKEN` | - | - | secret (analyst actions; the workbench holds the same value) | - | - | - | - | - | - |
| `CW_RULEBOOK_PUBLISH_ENABLED` | - | - | env (default `false`; owner regulatory-intelligence; removed once the workbench publishes in production and the obligation consumer of the rule events is live) | - | - | - | - | - | - |
| `CW_PIPELINE_KNOWLEDGE_ENABLED` | - | - | - | - | - | - | env | - | - |
| `CW_RULEBOOK_URL`, `CW_LLM_GATEWAY_URL` | - | - | - | - | - | - | env | env (qa) | - |
| `CW_PROFILE_URL`, `CW_OBLIGATION_URL`, `CW_QA_HTTP_TIMEOUT_SECONDS`, `CW_QA_LLM_TIMEOUT_SECONDS`, `CW_QA_EMBEDDING_TIMEOUT_SECONDS` | - | - | - | - | - | - | - | env (qa; the model timeouts default to 20 s, longer than the gateway's budget for the call) | - |
| `CW_QA_KAG_ENABLED`, `CW_QA_KAG_TENANTS` | - | - | - | - | - | - | - | env (qa; default `false` and every tenant; owner ai-platform; removed when ADR-017 is Accepted) | - |
| `CW_QA_PROMPTS_DIR` | - | - | - | - | - | - | - | set by the qa image (`/app/prompts`) | - |
| `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_SEND_ENABLED`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `NOTIFICATION_API_URL` | - | - | - | - | - | - | - | - | secret / secret / env / secret / secret / env |

The pipeline writes regulator documents to the rulebook (ADR-018), so deploy the rulebook before
the pipeline and give both the same `CW_RULEBOOK_WRITE_TOKEN`; a rulebook without one refuses
every write. The analyst's actions (review decisions, relation approvals, citations, the version
lifecycle and the sweep route) need a second secret, `CW_RULEBOOK_REVIEW_TOKEN`, with a different
value: the pipeline never gets it, and a rulebook without it refuses those actions. It is a shared
secret until the identity service exists, so the approver ids are asserted by the caller.

The rulebook writes its rule events (`rule.published`, `rule.superseded`, `rule.withdrawn`,
`rule.deadline_changed`) to its own `outbox_event` table, so it needs the outbox relay like the
profile and obligation services: a process running `python -m py_common.outbox` with the
rulebook's `CW_DATABASE_URL` and the Kafka secrets. A version replaced by one dated in the future
moves to superseded or withdrawn, with its event, only when the daily sweep runs: schedule a Fly
machine from the rulebook image running `rulebook-transitions` once a day (for example
`fly machine run <rulebook image> rulebook-transitions --schedule daily`, with the rulebook's
secrets and `CW_RULEBOOK_PUBLISH_ENABLED`). The in-force reads do not wait for it, because
publication already cut the replaced version's `effective_to`; a late run only delays the status
and the event. The command is idempotent and, with the flag off, moves nothing. Neither the relay
nor the machine is needed while `CW_RULEBOOK_PUBLISH_ENABLED` is off.

The rulebook's search index needs pgvector: its migration 0006, run by the release command,
creates the extension with `CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public`. Check that
the Postgres provider offers pgvector, and either let the rulebook's database role create
extensions or have an administrator run that statement once before the first deploy. `public`
must stay on the search path, as the `CW_DATABASE_URL` options above keep it. Clauses registered
before the pipeline embedded them are caught up by running `pipeline-embed` once from the
pipeline image, with the pipeline's secrets.

Every service also reads `CW_ENV`, `CW_LOG_LEVEL` and `CW_LOG_JSON` (env). The tenant comes from
the `x-tenant-id` header until Supabase Auth issues tokens (ADR-014): the MVP must sit behind
an authenticating proxy or an allow-list before it faces customers.

## Promotion and rollback

`fly deploy` builds and releases; `fly releases` lists them and `fly deploy --image <previous>`
rolls back. The migration release command runs before the new machines start, so a migration
must be backward compatible with the previous image (add columns, never drop in the same
release). Vercel keeps every deployment; promote or roll back from its dashboard.

## What the MVP profile does not give

Canary rollouts with automatic rollback on SLO breach, network policies and mTLS, node pools for
GPU work, Aurora PITR with 15-minute RPO (Fly Postgres and Neon offer PITR; confirm the window).
The guide's EKS path replaces this profile when the pilot outgrows it.
