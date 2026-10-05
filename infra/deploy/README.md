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
6. Identity and access tokens, per environment: the Supabase project and its keys, identity's
   signing key, a service client for each caller and the internal tenant, as listed in
   `services/identity/README.md` ("Supabase: manual steps"). Deploy identity before the services
   that verify its tokens. Run staging with `CW_AUTH_MODE=dual`, then `token`; production refuses
   any other mode and the fake provider.

## Environment matrix

Values: `secret` (set with `fly secrets set`, never in the toml), `env` (in the toml), `-` (unused).

| Variable | identity | profile | rulebook | obligation | notification | llm-gateway | pipeline | applicability-engine, qa, eval | whatsapp-bot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `CW_DATABASE_URL` | secret | secret | secret | secret | secret (API, worker and relay) | secret (`CW_LLM_LEDGER=postgres`) | secret | secret | - |
| `CW_DB_SCHEMA` | env | env | env | env | env | env | env | env | - |
| `CW_KAFKA_BOOTSTRAP` + SASL | - | secret (relay) | secret (relay) | secret (relay) | secret (worker, `python -m notification.worker`, and relay) | - | secret | secret | - |
| `CW_TEMPORAL_*` | - | - | - | - | - | - | secret | - | - |
| `CW_REDIS_URL` | - | - | - | - | - (digests are held in Postgres) | secret (cache, later) | - | - | - |
| `CW_OTEL_ENDPOINT` (+ header) | secret | secret | secret | secret | secret | secret | secret | secret | - |
| `CW_AUTH_MODE` | env | env | env | env | env | env | env | env | - |
| `CW_AUTH_JWKS_URL`, `CW_AUTH_ISSUER`, `CW_AUTH_AUDIENCE`, `CW_AUTH_LEEWAY_SECONDS` | env (issuer and audience only: identity verifies with its own keys) | env | env | env | env | env | env | env | - |
| `CW_IDENTITY_URL`, `CW_SERVICE_CLIENT_ID`, `CW_SERVICE_CLIENT_SECRET` | - | - | - | env / env / secret (assignee checks at identity and business checks at profile, client with tenant:act) | env / env / secret (rulebook reads) | - | env / env / secret (worker and `pipeline-embed`) | env / env / secret (qa) | - |
| `BOT_SERVICE_CLIENT_ID`, `BOT_SERVICE_CLIENT_SECRET` | - | - | - | - | - | - | - | - | env / secret (identity at `IDENTITY_API_URL`) |
| `CW_AUTH_PROVIDER`, `CW_SUPABASE_URL`, `CW_SUPABASE_SERVICE_ROLE_KEY`, `CW_SUPABASE_JWT_SECRET` | env / env / secret / secret (`supabase`; `fake` is refused with `CW_ENV=prod`; the JWT secret only for a project on the legacy HS256 secret; owner identity-partner) | - | - | - | - | - | - | - | - |
| `CW_IDENTITY_SIGNING_KEYS` | secret (one key set per environment, from `identity-admin signing-key new`; required outside local and test) | - | - | - | - | - | - | - | - |
| `CW_ACCESS_TOKEN_TTL_SECONDS`, `CW_SERVICE_TOKEN_TTL_SECONDS` | env (default 600: the longest a revoked session keeps working in the other services) | - | - | - | - | - | - | - | - |
| `CW_IDENTITY_FAKE_PROVIDER_SECRET`, `CW_IDENTITY_DEV_CLIENT_SECRET`, `CW_IDENTITY_DEV_CLIENTS` | never set (local and test only; the dev client secret is refused elsewhere) | - | - | - | - | - | - | - | - |
| `CW_AI_GATEWAY_API_KEY`, `CW_LLM_PROVIDER` | - | - | - | - | - | secret / env | - | - | - |
| `CW_LANGFUSE_*` | - | - | - | - | - | secret | - | - | - |
| `CW_LLM_ROUTES__<FEATURE>` (for example `CW_LLM_ROUTES__RETRIEVAL`), `CW_LLM_EMBEDDING_DIMENSIONS_PARAM` | - | - | - | - | - | env (only to override the routing table; the second defaults to `true`) | - | - | - |
| `CW_WHATSAPP_ENABLED`, `CW_WHATSAPP_PHONE_NUMBER_ID`, `CW_WHATSAPP_ACCESS_TOKEN` | - | - | - | - | env / secret / secret | - | - | - | - |
| `CW_NOTIFICATION_STORE` | - | - | - | - | env (default `postgres`; `memory` only for tests and demos, and the worker refuses it) | - | - | - | - |
| `CW_QUIET_HOURS_START`, `CW_QUIET_HOURS_END`, `CW_NOTIFICATION_BATCH_WINDOW_SECONDS`, `CW_NOTIFICATION_DISPATCH_INTERVAL_SECONDS`, `CW_NOTIFICATION_DIGEST_AT` | - | - | - | - | env (defaults `21:00` and `08:00` IST, 300 s, 5 s, `09:00` IST) | - | - | - | - |
| `CW_WEB_BASE_URL` | - | - | - | - | env (the web app's public URL, which messages link to) | - | - | - | - |
| `CW_NOTIFICATION_BOT_TOKEN` (notification), `NOTIFICATION_BOT_TOKEN` (bot) | - | - | - | - | secret (unset, the WhatsApp receipt route answers 503; accepted in `header` and `dual` mode only) | - | - | - | secret (the same value; unset, the bot forwards no delivery statuses unless it has its service token) |
| `CW_EMAIL_ENABLED`, `CW_SMTP_HOST`, `CW_SMTP_PORT`, `CW_SMTP_USERNAME`, `CW_SMTP_PASSWORD`, `CW_EMAIL_FROM` | - | - | - | - | env / env / env / secret / secret / env (flag default `false`; owner core-product; on once the in-region SES or SMTP sending domain is verified with SPF, DKIM and DMARC; removed after email has run in production for 30 days, when the channel is wired whenever `CW_SMTP_HOST` is set) | - | - | - | - |
| `CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN`, `CW_NOTIFICATION_SES_TOPIC_ARN` | - | - | - | - | secret / env (the password of the SNS subscription's basic credentials, and the SES feedback topic it must come from; unset token, the email receipt route answers 503) | - | - | - | - |
| `CW_BILLING_PROVIDER`, `CW_RAZORPAY_*` | env / secret | - | - | - | - | - | - | - | - |
| `CW_IDENTITY_STORE`, `CW_PROFILE_STORE`, `CW_PROFILE_GSTIN_LOOKUP` | env | env | - | - | - | - | - | - | - |
| `CW_RULEBOOK_STORE` | - | - | env | - | - | - | - | - | - |
| `CW_RULEBOOK_SEED_ON_START` | - | - | never set (local and test only: the memory store starts with the seed calendar's drafts; refused with `CW_ENV` staging or prod and with the Postgres store) | - | - | - | - | - | - |
| `CW_PROFILE_GSTIN_LOOKUP_URL`, `CW_PROFILE_GSTIN_LOOKUP_API_KEY`, `CW_PROFILE_GSTIN_LOOKUP_TIMEOUT_SECONDS` | - | env / secret / env (read with `CW_PROFILE_GSTIN_LOOKUP=http`, which waits for the provider account and a check of the field mapping against the provider's sandbox; until then `manual`) | - | - | - | - | - | - | - |
| `CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL`, `CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL__TENANTS` | - | env (default `false`, every tenant when the list is empty; owner core-product; on only after an analyst reviews the nature-of-business mapping, a few tenants first; removed once it has been on for every tenant for 30 days) | - | - | - | - | - | - | - |
| `CW_FLAGS_PROVIDER`, `CW_UNLEASH_URL`, `CW_UNLEASH_API_TOKEN` | - | env / env / secret (default `env`, flags from the variables in this table; `unleash` once a hosted Unleash runs, self-hosted on the MVP platform or an Unleash account, with a client token; owner platform). Only flags read through `py_common.flags` follow it, today `profile.gstin_category_prefill` alone; `CW_RULEBOOK_PUBLISH_ENABLED`, `CW_QA_KAG_ENABLED` and the other switches in this table stay environment variables whichever provider is chosen | - | - | - | - | - | - | - |
| `CW_RULEBOOK_WRITE_TOKEN` | - | - | secret (`header` and `dual` mode; in `token` mode the pipeline's service token with `rulebook:write` replaces it) | - | - | - | secret | - | - |
| `CW_RULEBOOK_REVIEW_TOKEN` | - | - | secret (analyst actions in `header` and `dual` mode; the workbench holds the same value; in `token` mode the analyst's own access token replaces it) | - | - | - | - | - | - |
| `CW_RULEBOOK_PUBLISH_ENABLED` | - | - | env (default `false`; owner regulatory-intelligence; removed once the workbench publishes in production and the obligation consumer of the rule events is live) | - | - | - | - | - | - |
| `CW_PIPELINE_KNOWLEDGE_ENABLED` | - | - | - | - | - | - | env | - | - |
| `CW_RULEBOOK_URL`, `CW_LLM_GATEWAY_URL` | - | - | - | - | env (`CW_RULEBOOK_URL` only: the published facts of change cards) | - | env | env (qa) | - |
| `CW_PROFILE_URL`, `CW_OBLIGATION_URL`, `CW_QA_HTTP_TIMEOUT_SECONDS`, `CW_QA_LLM_TIMEOUT_SECONDS`, `CW_QA_EMBEDDING_TIMEOUT_SECONDS` | - | - | - | env (`CW_PROFILE_URL` only: whether a business with an empty page of the public list is the tenant's) | - | - | - | env (qa; reads time out after 5 s by default, the model calls after 20 s, longer than the gateway's budget for the call) | - |
| `CW_QA_KAG_ENABLED`, `CW_QA_KAG_TENANTS` | - | - | - | - | - | - | - | env (qa; default `false` and every tenant; owner ai-platform; removed when ADR-017 is Accepted) | - |
| `CW_QA_PROMPTS_DIR` | - | - | - | - | - | - | - | set by the qa image (`/app/prompts`) | - |
| `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_SEND_ENABLED`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `NOTIFICATION_API_URL` | - | - | - | - | - | - | - | - | secret / secret / env / secret / secret / env |
| `CW_IDENTITY_CHANNEL_TOKEN` | secret (`header` and `dual` mode only; in `token` mode the bot's service token with `identity:channel-consents` replaces it) | - | - | - | - | - | - | - | - |
| `WHATSAPP_CONSENT_RECORDING_ENABLED`, `IDENTITY_API_URL`, `IDENTITY_SERVICE_TOKEN`, `WHATSAPP_NOTICE_VERSION` | - | - | - | - | - | - | - | - | env / env / secret / env |

The pipeline writes regulator documents to the rulebook (ADR-018), so deploy the rulebook before
the pipeline and give both the same `CW_RULEBOOK_WRITE_TOKEN`; a rulebook without one refuses
every write. The analyst's actions (review decisions, relation approvals, citations, the version
lifecycle and the sweep route) need a second secret, `CW_RULEBOOK_REVIEW_TOKEN`, with a different
value: the pipeline never gets it, and a rulebook without it refuses those actions. A request that
opens them with the shared secret (in `header` mode, or `dual` mode without an access token) names
its own approver ids. In `token` mode neither shared token opens anything: the pipeline sends its
service token, the analyst signs in, and the rulebook takes the approver from the analyst's access
token.

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

The WhatsApp bot records keyword opt-ins and opt-outs in identity: give identity
`CW_IDENTITY_CHANNEL_TOKEN` and the bot the same value as `IDENTITY_SERVICE_TOKEN`, with
`IDENTITY_API_URL` pointing at identity. `WHATSAPP_CONSENT_RECORDING_ENABLED` stays `false` until
the lawyer confirms that the keyword opt-in is valid consent (`docs/legal/README.md`) and
identity runs in the deployed profile; with it `true` and no token the bot refuses to start.

Every service also reads `CW_ENV`, `CW_LOG_LEVEL` and `CW_LOG_JSON` (env). With
`CW_AUTH_MODE=header`, the default, the tenant comes from the `x-tenant-id` header and nothing
checks who sent it, so a deployment in that mode must sit behind an authenticating proxy or an
allow-list. `CW_ENV=prod` refuses any mode but `token` (ADR-014's addendum). Identity signs access
tokens with `CW_IDENTITY_SIGNING_KEYS` and publishes the public keys at
`/v1/identity/.well-known/jwks.json`; every other service fetches them from `CW_AUTH_JWKS_URL`
(identity's internal URL plus that path) and keeps them for an hour. The callers that send service
tokens (notification, the pipeline, qa and the WhatsApp bot) each need a service client created in
that environment with `identity-admin service-client create`. Who holds each secret, and how it
rotates, is in `docs/runbooks/secret-rotation.md`.

## Promotion and rollback

`fly deploy` builds and releases; `fly releases` lists them and `fly deploy --image <previous>`
rolls back. The migration release command runs before the new machines start, so a migration
must be backward compatible with the previous image (add columns, never drop in the same
release). Vercel keeps every deployment; promote or roll back from its dashboard.

## What the MVP profile does not give

Canary rollouts with automatic rollback on SLO breach, network policies and mTLS, node pools for
GPU work, Aurora PITR with 15-minute RPO (Fly Postgres and Neon offer PITR; confirm the window).
The guide's EKS path replaces this profile when the pilot outgrows it.
